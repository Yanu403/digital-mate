"""Tests for image/vision input capability.

Covers:
- LLMClient.chat_with_image() — verifies image_url is injected into messages
- LLMClient.chat_with_image_stream() — verifies streaming with image
- LLMClient._build_vision_messages() — message construction logic
- DigitalMateBot._handle_photo() — end-to-end photo handler with mocks
- Photo handler registration in build_application()
- Image base64 encoding utility (encode_image_file / encode_image_bytes)
- BasePillar.handle_image() default implementation
"""

from __future__ import annotations

import base64
import json
import io
import os
import tempfile
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

from digital_mate.llm.client import LLMClient, LLMError
from digital_mate.bot import DigitalMateBot, IMAGE_ANALYSIS_SYSTEM_PROMPT
from digital_mate.router import IntentRouter
from digital_mate.memory.session import SessionManager
from digital_mate.memory.brand_profile import BrandProfileManager
from digital_mate.utils.image import encode_image_file, encode_image_bytes
from digital_mate.pillars.base import BasePillar


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_httpx_response(content: str) -> MagicMock:
    """Build a mock httpx.Response returning the given content."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = {
        "choices": [{"message": {"content": content}}]
    }
    resp.raise_for_status = MagicMock()
    return resp


def _make_stream_lines(chunks: list[str]) -> "list[str]":
    """Build SSE-formatted lines from text chunks."""
    lines = []
    for text in chunks:
        chunk = {"choices": [{"delta": {"content": text}}]}
        lines.append(f"data: {json.dumps(chunk)}")
    lines.append("data: [DONE]")
    return lines


class _MockStreamResponse:
    """Mock for httpx stream context manager yielding SSE lines."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines
        self.status_code = 200

    def raise_for_status(self) -> None:
        pass

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass
def _make_photo_update(
    chat_id: int = 123456789,
    caption: str = "",
    file_id: str = "test_file_123",
) -> AsyncMock:
    """Create a mock Telegram Update with a photo message.

    ``photo`` is a list of mock PhotoSize objects (smallest to largest).
    ``caption`` is the user's caption text.
    """
    update = AsyncMock()
    update.effective_chat.id = chat_id

    # Photo sizes (smallest → largest)
    photo_sizes = []
    for i, (w, h) in enumerate([(160, 160), (320, 320), (640, 640), (1280, 1280)]):
        ps = MagicMock()
        ps.file_id = f"{file_id}_{i}"
        ps.width = w
        ps.height = h
        ps.file_size = w * h
        photo_sizes.append(ps)

    update.message.photo = photo_sizes
    update.message.caption = caption if caption else None
    update.message.text = None

    sent_messages: list[AsyncMock] = []
    update._sent_messages = sent_messages

    def _make_msg() -> AsyncMock:
        msg = AsyncMock()
        msg.edit_text = AsyncMock()
        msg.reply_text = AsyncMock()
        sent_messages.append(msg)
        return msg

    update.message.reply_text = AsyncMock(side_effect=lambda *a, **kw: _make_msg())
    update.message.chat.send_action = AsyncMock()
    return update


def _make_bot(
    sample_settings,
    mock_llm_client,
    session_mgr: SessionManager | None = None,
    brand_mgr: BrandProfileManager | None = None,
) -> DigitalMateBot:
    """Build a DigitalMateBot with mocked dependencies."""
    router = IntentRouter(mock_llm_client)

    if session_mgr is None:
        session_mgr = AsyncMock(spec=SessionManager)
        session_mgr.get_context = AsyncMock(return_value=[])
        session_mgr.add_message = AsyncMock()
        session_mgr.clear = AsyncMock(return_value=0)

    if brand_mgr is None:
        brand_mgr = AsyncMock(spec=BrandProfileManager)
        brand_mgr.get = AsyncMock(return_value=None)
        brand_mgr.create_or_update = AsyncMock()

    return DigitalMateBot(
        settings=sample_settings,
        llm_client=mock_llm_client,
        router=router,
        session_manager=session_mgr,
        brand_manager=brand_mgr,
    )


# ---------------------------------------------------------------------------
# 1. LLMClient._build_vision_messages
# ---------------------------------------------------------------------------


class TestBuildVisionMessages:
    """Test the _build_vision_messages static method."""

    def test_injects_image_into_last_user_message(self) -> None:
        """Image_url content is injected into the last user message."""
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Analyze this image"},
        ]
        result = LLMClient._build_vision_messages(messages, "base64data", "image/jpeg")

        assert len(result) == 2
        assert result[0] == {"role": "system", "content": "You are a helpful assistant."}

        # Last user message should be a content array
        assert result[1]["role"] == "user"
        content = result[1]["content"]
        assert isinstance(content, list)
        assert len(content) == 2
        assert content[0] == {"type": "text", "text": "Analyze this image"}
        assert content[1]["type"] == "image_url"
        assert "data:image/jpeg;base64,base64data" in content[1]["image_url"]["url"]

    def test_preserves_context_messages(self) -> None:
        """System and assistant messages are preserved unchanged."""
        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "First question"},
            {"role": "assistant", "content": "First answer"},
            {"role": "user", "content": "Analyze this screenshot"},
        ]
        result = LLMClient._build_vision_messages(messages, "imgdata")

        assert result[0] == {"role": "system", "content": "System prompt"}
        assert result[1] == {"role": "user", "content": "First question"}
        assert result[2] == {"role": "assistant", "content": "First answer"}
        # Last user message converted to vision format
        assert isinstance(result[3]["content"], list)

    def test_uses_correct_mime_type(self) -> None:
        """Custom MIME type appears in the data URL."""
        messages = [{"role": "user", "content": "test"}]
        result = LLMClient._build_vision_messages(messages, "data", "image/png")
        url = result[0]["content"][1]["image_url"]["url"]
        assert url.startswith("data:image/png;base64,")

    def test_default_mime_type_is_jpeg(self) -> None:
        """Default MIME type is image/jpeg."""
        messages = [{"role": "user", "content": "test"}]
        result = LLMClient._build_vision_messages(messages, "data")
        url = result[0]["content"][1]["image_url"]["url"]
        assert url.startswith("data:image/jpeg;base64,")

    def test_raises_on_empty_messages(self) -> None:
        """ValueError when messages list is empty."""
        with pytest.raises(ValueError, match="at least one user message"):
            LLMClient._build_vision_messages([], "data")

    def test_raises_on_no_user_message(self) -> None:
        """ValueError when no user message is present."""
        messages = [{"role": "system", "content": "system only"}]
        with pytest.raises(ValueError, match="No user message"):
            LLMClient._build_vision_messages(messages, "data")

    def test_does_not_mutate_original_messages(self) -> None:
        """Original messages list is not modified."""
        messages = [{"role": "user", "content": "test"}]
        original = [dict(m) for m in messages]
        LLMClient._build_vision_messages(messages, "data")
        assert messages == original


# ---------------------------------------------------------------------------
# 2. LLMClient.chat_with_image
# ---------------------------------------------------------------------------


@pytest.fixture
def llm_client() -> LLMClient:
    """Create a real LLMClient with test configuration."""
    return LLMClient(
        base_url="http://test.api/v1",
        api_key="test-key",
        model="test-model",
        router_model="test-router-model",
        max_retries=3,
        timeout=10.0,
    )


class TestChatWithImage:
    """Test chat_with_image() method."""

    @pytest.mark.asyncio
    async def test_returns_response_text(self, llm_client: LLMClient) -> None:
        """chat_with_image returns the LLM response text."""
        llm_client._client.post = AsyncMock(
            return_value=_make_httpx_response("This image shows a dashboard.")
        )
        messages = [{"role": "user", "content": "Analyze this"}]
        result = await llm_client.chat_with_image(messages, "base64data")

        assert result == "This image shows a dashboard."

    @pytest.mark.asyncio
    async def test_passes_vision_messages_to_api(self, llm_client: LLMClient) -> None:
        """The messages sent to the API contain image_url content."""
        llm_client._client.post = AsyncMock(
            return_value=_make_httpx_response("response")
        )
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "analyze"},
        ]
        await llm_client.chat_with_image(messages, "imgbase64")

        call_args = llm_client._client.post.call_args
        sent_messages = (call_args.kwargs.get("json") or call_args[1].get("json"))["messages"]
        # Last message should have content array with image_url
        last_msg = sent_messages[-1]
        assert isinstance(last_msg["content"], list)
        assert any(c.get("type") == "image_url" for c in last_msg["content"])

    @pytest.mark.asyncio
    async def test_strips_whitespace(self, llm_client: LLMClient) -> None:
        """Response is stripped of whitespace."""
        llm_client._client.post = AsyncMock(
            return_value=_make_httpx_response("  Padded response  ")
        )
        result = await llm_client.chat_with_image(
            [{"role": "user", "content": "test"}], "data"
        )
        assert result == "Padded response"

    @pytest.mark.asyncio
    async def test_raises_on_empty_response(self, llm_client: LLMClient) -> None:
        """LLMError raised on empty response."""
        llm_client._client.post = AsyncMock(
            return_value=_make_httpx_response("   ")
        )
        with pytest.raises(LLMError, match="empty response"):
            await llm_client.chat_with_image(
                [{"role": "user", "content": "test"}], "data"
            )

    @pytest.mark.asyncio
    async def test_retries_on_timeout(self, llm_client: LLMClient) -> None:
        """chat_with_image retries on httpx.ReadTimeout."""
        llm_client._client.post = AsyncMock(
            side_effect=[
                httpx.ReadTimeout("timeout"),
                _make_httpx_response("recovered"),
            ]
        )
        with patch(
            "digital_mate.llm.client._jittered_backoff",
            side_effect=[1.0],
        ), patch("asyncio.sleep", new_callable=AsyncMock):
            result = await llm_client.chat_with_image(
                [{"role": "user", "content": "test"}], "data"
            )
        assert result == "recovered"
        assert llm_client._client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_raises_on_no_user_message(self, llm_client: LLMClient) -> None:
        """ValueError when messages has no user message."""
        with pytest.raises(ValueError):
            await llm_client.chat_with_image(
                [{"role": "system", "content": "sys"}], "data"
            )

    @pytest.mark.asyncio
    async def test_uses_model_override(self, llm_client: LLMClient) -> None:
        """Model parameter overrides self.model."""
        llm_client._client.post = AsyncMock(
            return_value=_make_httpx_response("ok")
        )
        await llm_client.chat_with_image(
            [{"role": "user", "content": "test"}], "data", model="vision-model"
        )
        call_args = llm_client._client.post.call_args
        body = call_args.kwargs.get("json") or call_args[1].get("json")
        assert body["model"] == "vision-model"


# ---------------------------------------------------------------------------
# 3. LLMClient.chat_with_image_stream
# ---------------------------------------------------------------------------


class TestChatWithImageStream:
    """Test chat_with_image_stream() method."""

    @pytest.mark.asyncio
    async def test_yields_chunks(self, llm_client: LLMClient) -> None:
        """chat_with_image_stream yields text chunks."""
        stream_chunks = _make_stream_lines(["Hello ", "world", "!"])
        llm_client._client.stream = MagicMock(
            return_value=_MockStreamResponse(stream_chunks)
        )
        messages = [{"role": "user", "content": "analyze"}]
        chunks = []
        async for chunk in llm_client.chat_with_image_stream(messages, "data"):
            chunks.append(chunk)

        assert chunks == ["Hello ", "world", "!"]

    @pytest.mark.asyncio
    async def test_passes_vision_messages(self, llm_client: LLMClient) -> None:
        """Stream request contains vision messages with image_url."""
        stream_chunks = _make_stream_lines(["resp"])
        llm_client._client.stream = MagicMock(
            return_value=_MockStreamResponse(stream_chunks)
        )
        messages = [{"role": "user", "content": "test"}]
        async for _ in llm_client.chat_with_image_stream(messages, "imgdata"):
            pass

        call_args = llm_client._client.stream.call_args
        body = call_args.kwargs.get("json") or call_args[1].get("json")
        assert body["stream"] is True
        sent_messages = body["messages"]
        last_msg = sent_messages[-1]
        assert isinstance(last_msg["content"], list)
        assert any(c.get("type") == "image_url" for c in last_msg["content"])

    @pytest.mark.asyncio
    async def test_empty_stream_produces_no_chunks(self, llm_client: LLMClient) -> None:
        """An empty stream yields nothing without error."""
        stream_chunks = _make_stream_lines([])
        llm_client._client.stream = MagicMock(
            return_value=_MockStreamResponse(stream_chunks)
        )
        chunks = []
        async for chunk in llm_client.chat_with_image_stream(
            [{"role": "user", "content": "test"}], "data"
        ):
            chunks.append(chunk)
        assert chunks == []


# ---------------------------------------------------------------------------
# 4. Image encoding utilities
# ---------------------------------------------------------------------------


class TestImageEncoding:
    """Test image encoding utilities."""

    def test_encode_image_file_jpeg(self) -> None:
        """encode_image_file reads a JPEG and returns base64 + mime."""
        from PIL import Image as PILImage

        # Create a small test image
        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        tmp.close()
        img = PILImage.new("RGB", (100, 100), color=(255, 0, 0))
        img.save(tmp.name, format="JPEG")

        try:
            b64, mime = encode_image_file(tmp.name)
            assert mime == "image/jpeg"
            # Verify it's valid base64
            decoded = base64.b64decode(b64)
            assert len(decoded) > 0
            # Verify it starts with JPEG magic bytes
            assert decoded[:2] == b"\xff\xd8"
        finally:
            os.unlink(tmp.name)

    def test_encode_image_file_resizes_large_image(self) -> None:
        """Large images are resized to max 1024x1024."""
        from PIL import Image as PILImage

        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        tmp.close()
        img = PILImage.new("RGB", (2048, 2048), color=(0, 255, 0))
        img.save(tmp.name, format="JPEG")

        try:
            b64, mime = encode_image_file(tmp.name)
            assert mime == "image/jpeg"
            # Decode and check dimensions
            decoded = base64.b64decode(b64)
            result_img = PILImage.open(io.BytesIO(decoded))
            assert result_img.size[0] <= 1024
            assert result_img.size[1] <= 1024
        finally:
            os.unlink(tmp.name)

    def test_encode_image_file_maintains_aspect_ratio(self) -> None:
        """Resized images maintain aspect ratio."""
        from PIL import Image as PILImage

        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        tmp.close()
        # 2000x1000 → should resize to 1024x512
        img = PILImage.new("RGB", (2000, 1000), color=(0, 0, 255))
        img.save(tmp.name, format="JPEG")

        try:
            b64, _ = encode_image_file(tmp.name)
            decoded = base64.b64decode(b64)
            result_img = PILImage.open(io.BytesIO(decoded))
            # Aspect ratio 2:1 should be preserved
            assert result_img.size == (1024, 512)
        finally:
            os.unlink(tmp.name)

    def test_encode_image_file_nonexistent_raises(self) -> None:
        """FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            encode_image_file("/nonexistent/path/to/image.jpg")

    def test_encode_image_bytes(self) -> None:
        """encode_image_bytes processes raw bytes."""
        from PIL import Image as PILImage

        buf = io.BytesIO()
        img = PILImage.new("RGB", (200, 200), color=(128, 128, 128))
        img.save(buf, format="JPEG")
        data = buf.getvalue()

        b64, mime = encode_image_bytes(data)
        assert mime == "image/jpeg"
        decoded = base64.b64decode(b64)
        assert decoded[:2] == b"\xff\xd8"

    def test_encode_small_image_not_resized(self) -> None:
        """Small images are not resized."""
        from PIL import Image as PILImage

        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        tmp.close()
        img = PILImage.new("RGB", (200, 200), color=(255, 255, 0))
        img.save(tmp.name, format="JPEG")

        try:
            b64, _ = encode_image_file(tmp.name)
            decoded = base64.b64decode(b64)
            result_img = PILImage.open(io.BytesIO(decoded))
            # Small image should remain 200x200
            assert result_img.size == (200, 200)
        finally:
            os.unlink(tmp.name)


# ---------------------------------------------------------------------------
# 5. Bot photo handler
# ---------------------------------------------------------------------------


class TestPhotoHandler:
    """Test _handle_photo() method."""

    @pytest.mark.asyncio
    async def test_photo_handler_calls_vision_llm(
        self, sample_settings, mock_llm_client
    ) -> None:
        """_handle_photo downloads the image and calls chat_with_image_stream."""
        bot = _make_bot(sample_settings, mock_llm_client)

        # Mock chat_with_image_stream as an async generator
        async def mock_stream(*args, **kwargs):
            yield "This is "
            yield "an analysis."

        mock_llm_client.chat_with_image_stream = mock_stream

        # Mock file download
        from PIL import Image as PILImage

        update = _make_photo_update(caption="What is this?")
        update.effective_chat.id = 999

        # Create a temp image file for the download mock
        tmp_img = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        tmp_img.close()
        PILImage.new("RGB", (100, 100), color=(255, 0, 0)).save(tmp_img.name, format="JPEG")

        mock_file = AsyncMock()
        mock_file.download_to_drive = AsyncMock()

        # Patch get_file and download_to_drive to write our test image
        async def fake_download(path):
            import shutil
            shutil.copy(tmp_img.name, path)

        mock_file.download_to_drive = AsyncMock(side_effect=fake_download)

        ctx = AsyncMock()
        ctx.bot.get_file = AsyncMock(return_value=mock_file)

        with patch("digital_mate.bot.encode_image_file", return_value=("b64", "image/jpeg")):
            await bot._handle_photo(update, ctx)

        # Verify LLM was called (chat_with_image_stream is a real async generator, not a mock)
        # Verify session was updated
        bot.session_manager.add_message.assert_any_await(999, "user", "What is this?")
        bot.session_manager.add_message.assert_any_await(999, "assistant", "This is an analysis.")

        # Cleanup
        os.unlink(tmp_img.name)

    @pytest.mark.asyncio
    async def test_photo_handler_no_caption_uses_default(
        self, sample_settings, mock_llm_client
    ) -> None:
        """Photo without caption uses default analysis prompt."""
        bot = _make_bot(sample_settings, mock_llm_client)

        async def mock_stream(*args, **kwargs):
            yield "General analysis result"

        mock_llm_client.chat_with_image_stream = mock_stream

        from PIL import Image as PILImage

        update = _make_photo_update(caption="")
        update.effective_chat.id = 888

        tmp_img = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        tmp_img.close()
        PILImage.new("RGB", (50, 50), color=(0, 255, 0)).save(tmp_img.name, format="JPEG")

        async def fake_download(path):
            import shutil
            shutil.copy(tmp_img.name, path)

        mock_file = AsyncMock()
        mock_file.download_to_drive = AsyncMock(side_effect=fake_download)

        ctx = AsyncMock()
        ctx.bot.get_file = AsyncMock(return_value=mock_file)

        with patch("digital_mate.bot.encode_image_file", return_value=("b64", "image/jpeg")):
            await bot._handle_photo(update, ctx)

        bot.session_manager.add_message.assert_any_await(888, "user", "[Image shared for analysis]")
        bot.session_manager.add_message.assert_any_await(888, "assistant", "General analysis result")

        os.unlink(tmp_img.name)

    @pytest.mark.asyncio
    async def test_photo_handler_routes_to_analytics_pillar(
        self, sample_settings, mock_llm_client
    ) -> None:
        """Caption with 'analytics' routes to AnalyticsPillar.handle_image()."""
        bot = _make_bot(sample_settings, mock_llm_client)

        # Mock handle_image on analytics pillar
        bot.analytics_pillar.handle_image = AsyncMock(
            return_value="Analytics-specific analysis"
        )

        from PIL import Image as PILImage

        update = _make_photo_update(caption="analyze this analytics dashboard")
        update.effective_chat.id = 777

        tmp_img = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        tmp_img.close()
        PILImage.new("RGB", (50, 50)).save(tmp_img.name, format="JPEG")

        async def fake_download(path):
            import shutil
            shutil.copy(tmp_img.name, path)

        mock_file = AsyncMock()
        mock_file.download_to_drive = AsyncMock(side_effect=fake_download)

        ctx = AsyncMock()
        ctx.bot.get_file = AsyncMock(return_value=mock_file)

        with patch("digital_mate.bot.encode_image_file", return_value=("b64", "image/jpeg")):
            await bot._handle_photo(update, ctx)

        bot.analytics_pillar.handle_image.assert_awaited_once()
        call_kwargs = bot.analytics_pillar.handle_image.call_args.kwargs
        assert call_kwargs["image_base64"] == "b64"
        assert call_kwargs["image_mime_type"] == "image/jpeg"

        os.unlink(tmp_img.name)

    @pytest.mark.asyncio
    async def test_photo_handler_error_graceful(
        self, sample_settings, mock_llm_client
    ) -> None:
        """Photo handler shows error message on failure."""
        bot = _make_bot(sample_settings, mock_llm_client)

        update = _make_photo_update(caption="test")
        update.effective_chat.id = 666

        ctx = AsyncMock()
        # Make get_file raise an error
        ctx.bot.get_file = AsyncMock(side_effect=Exception("Download failed"))

        await bot._handle_photo(update, ctx)

        # Should have sent an error message
        update.message.reply_text.assert_called()
        last_call = update.message.reply_text.call_args
        assert "couldn't analyze" in last_call.args[0] or "sorry" in last_call.args[0].lower()

    @pytest.mark.asyncio
    async def test_photo_handler_no_photo_returns_early(
        self, sample_settings, mock_llm_client
    ) -> None:
        """Handler returns immediately if no photo in update."""
        bot = _make_bot(sample_settings, mock_llm_client)

        update = AsyncMock()
        update.message.photo = None
        update.message.caption = None
        ctx = AsyncMock()

        await bot._handle_photo(update, ctx)

        ctx.bot.get_file.assert_not_called()


# ---------------------------------------------------------------------------
# 6. Photo handler registration
# ---------------------------------------------------------------------------


class TestPhotoHandlerRegistration:
    """Test that the photo handler is registered in build_application()."""

    def test_photo_handler_registered(self, sample_settings, mock_llm_client) -> None:
        """build_application() registers a MessageHandler for photos."""
        bot = _make_bot(sample_settings, mock_llm_client)
        app = bot.build_application()

        # Check that handlers include one for photos
        # python-telegram-bot stores handlers in groups
        found_photo = False
        for group_handlers in app.handlers.values():
            for handler in group_handlers:
                # Check if it's a MessageHandler with photo filter
                if hasattr(handler, "filters"):
                    handler_str = str(handler.filters)
                    if "photo" in handler_str.lower() or "Photo" in handler_str:
                        found_photo = True
                        break
            if found_photo:
                break

        assert found_photo, "Photo handler (filters.PHOTO) not found in registered handlers"

    def test_photo_handler_callback_is_handle_photo(
        self, sample_settings, mock_llm_client
    ) -> None:
        """The registered photo handler's callback is _handle_photo."""
        bot = _make_bot(sample_settings, mock_llm_client)
        app = bot.build_application()

        found = False
        for group_handlers in app.handlers.values():
            for handler in group_handlers:
                if hasattr(handler, "filters") and hasattr(handler, "callback"):
                    handler_str = str(handler.filters)
                    if "photo" in handler_str.lower() or "Photo" in handler_str:
                        assert handler.callback == bot._handle_photo
                        found = True
                        break
            if found:
                break

        assert found, "Photo handler with _handle_photo callback not found"


# ---------------------------------------------------------------------------
# 7. BasePillar.handle_image
# ---------------------------------------------------------------------------


class TestBasePillarHandleImage:
    """Test the default handle_image() on BasePillar."""

    @pytest.mark.asyncio
    async def test_handle_image_calls_chat_with_image(
        self, mock_llm_client
    ) -> None:
        """Default handle_image calls llm_client.chat_with_image."""
        # Create a minimal concrete pillar
        class TestPillar(BasePillar):
            PILLAR_NAME = "test"
            MAX_RESPONSE_TOKENS = 1024

            async def handle(self, user_message, action, context, brand_profile=None, **kwargs):
                return "test"

        mock_llm_client.chat_with_image = AsyncMock(return_value="Image analysis result")
        pillar = TestPillar(mock_llm_client)

        result = await pillar.handle_image(
            user_message="Analyze this",
            image_base64="base64data",
            image_mime_type="image/jpeg",
        )

        assert result == "Image analysis result"
        mock_llm_client.chat_with_image.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_image_handles_llm_error(
        self, mock_llm_client
    ) -> None:
        """handle_image returns error message on LLMError."""
        class TestPillar(BasePillar):
            PILLAR_NAME = "test"
            MAX_RESPONSE_TOKENS = 1024

            async def handle(self, user_message, action, context, brand_profile=None, **kwargs):
                return "test"

        mock_llm_client.chat_with_image = AsyncMock(side_effect=LLMError("API down"))
        pillar = TestPillar(mock_llm_client)

        result = await pillar.handle_image(
            user_message="test",
            image_base64="data",
        )

        assert "error" in result.lower() or "sorry" in result.lower()

    @pytest.mark.asyncio
    async def test_handle_image_passes_brand_context(
        self, mock_llm_client
    ) -> None:
        """handle_image includes brand context when brand_profile is provided."""
        from digital_mate.memory.brand_profile import BrandProfile

        class TestPillar(BasePillar):
            PILLAR_NAME = "content"
            MAX_RESPONSE_TOKENS = 1024

            async def handle(self, user_message, action, context, brand_profile=None, **kwargs):
                return "test"

        mock_llm_client.chat_with_image = AsyncMock(return_value="ok")
        pillar = TestPillar(mock_llm_client)

        profile = BrandProfile(
            chat_id=1,
            name="TestBrand",
            industry="Tech",
            audience="Developers",
            tone="Professional",
            products="Software",
            hashtags="#tech",
            competitors="",
            language_pref="bilingual",
            platform_preference="",
            budget_range="",
            business_stage="",
        )

        await pillar.handle_image(
            user_message="test",
            image_base64="data",
            brand_profile=profile,
        )

        call_args = mock_llm_client.chat_with_image.call_args
        messages = call_args.args[0]
        # System message should contain brand context
        system_msg = messages[0]["content"]
        assert "TestBrand" in system_msg or "Brand" in system_msg


# ---------------------------------------------------------------------------
# 8. Config vision model
# ---------------------------------------------------------------------------


class TestConfigVisionModel:
    """Test vision model config settings."""

    def test_vision_model_default_empty(self, sample_settings) -> None:
        """Default llm_vision_model is empty string."""
        assert sample_settings.llm_vision_model == ""

    def test_vision_model_effective_falls_back(self, sample_settings) -> None:
        """vision_model_effective falls back to llm_model when empty."""
        assert sample_settings.vision_model_effective == sample_settings.llm_model

    def test_vision_model_effective_uses_override(self) -> None:
        """vision_model_effective uses llm_vision_model when set."""
        from digital_mate.config import Settings

        settings = Settings(
            _env_file=None,
            telegram_bot_token="test-token",
            llm_api_key="test-key",
            llm_model="text-model",
            llm_vision_model="vision-model",
        )
        assert settings.vision_model_effective == "vision-model"


# ---------------------------------------------------------------------------
# 9. Image analysis system prompt
# ---------------------------------------------------------------------------


class TestImageAnalysisPrompt:
    """Test the image analysis system prompt constant."""

    def test_prompt_contains_marketing_context(self) -> None:
        """System prompt mentions marketing perspective."""
        assert "marketing" in IMAGE_ANALYSIS_SYSTEM_PROMPT.lower()
        assert "Digital Mate" in IMAGE_ANALYSIS_SYSTEM_PROMPT

    def test_prompt_covers_image_types(self) -> None:
        """Prompt mentions analytics, competitor ads, design drafts, social media."""
        prompt_lower = IMAGE_ANALYSIS_SYSTEM_PROMPT.lower()
        assert "analytics" in prompt_lower
        assert "competitor" in prompt_lower
        assert "design" in prompt_lower
        assert "social media" in prompt_lower

    def test_prompt_instructs_language_matching(self) -> None:
        """Prompt instructs to match user's language."""
        assert "language" in IMAGE_ANALYSIS_SYSTEM_PROMPT.lower()
