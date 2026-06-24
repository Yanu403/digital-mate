"""Tests for digital_mate.llm.client module.

Covers chat() and chat_json() success paths, retry logic with exponential
backoff on transient errors, error handling for non-retryable failures,
edge cases like None content and non-dict JSON, and model selection.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from digital_mate.llm.client import LLMClient, LLMError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def llm_client() -> LLMClient:
    """Create a real LLMClient with test configuration."""
    client = LLMClient(
        base_url="http://test.api/v1",
        api_key="test-key",
        model="test-model",
        router_model="test-router-model",
        max_retries=3,
        timeout=10.0,
    )
    return client


def _make_httpx_response(content: str) -> MagicMock:
    """Build a mock httpx.Response returning the given content."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = {
        "choices": [{"message": {"content": content}}]
    }
    resp.raise_for_status = MagicMock()
    return resp


def _make_httpx_response_none_content() -> MagicMock:
    """Build a mock httpx.Response with None content."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = {
        "choices": [{"message": {"content": None}}]
    }
    resp.raise_for_status = MagicMock()
    return resp


def _make_httpx_status_error(status_code: int = 400) -> httpx.HTTPStatusError:
    """Build an httpx.HTTPStatusError for the given status code."""
    request = httpx.Request("POST", "http://test.api/v1/chat/completions")
    response = httpx.Response(status_code=status_code, request=request)
    return httpx.HTTPStatusError(
        message=f"HTTP {status_code}",
        request=request,
        response=response,
    )


# ---------------------------------------------------------------------------
# chat() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_success_strips_whitespace(llm_client: LLMClient) -> None:
    """chat() returns stripped content."""
    llm_client._client.post = AsyncMock(
        return_value=_make_httpx_response("  Hello world  ")
    )
    result = await llm_client.chat([{"role": "user", "content": "hi"}])
    assert result == "Hello world"


@pytest.mark.asyncio
async def test_chat_retries_on_timeout(llm_client: LLMClient) -> None:
    """chat() retries on httpx.TimeoutException with exponential backoff."""
    mock_success = _make_httpx_response("recovered")
    llm_client._client.post = AsyncMock(
        side_effect=[
            httpx.ReadTimeout("timeout"),
            httpx.ReadTimeout("timeout"),
            mock_success,
        ]
    )

    with patch(
        "digital_mate.llm.client._jittered_backoff",
        side_effect=[1.0, 2.0],
    ) as mock_backoff, patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await llm_client.chat([{"role": "user", "content": "test"}])

    assert result == "recovered"
    assert llm_client._client.post.call_count == 3
    # Jittered exponential backoff: attempt 1 → 1.0s, attempt 2 → 2.0s
    mock_backoff.assert_any_call(1)
    mock_backoff.assert_any_call(2)
    mock_sleep.assert_any_call(1.0)
    mock_sleep.assert_any_call(2.0)


@pytest.mark.asyncio
async def test_chat_retries_on_connection_error(llm_client: LLMClient) -> None:
    """chat() retries on httpx.ConnectError with exponential backoff."""
    mock_success = _make_httpx_response("connected")
    llm_client._client.post = AsyncMock(
        side_effect=[
            httpx.ConnectError("connection refused"),
            mock_success,
        ]
    )

    with patch(
        "digital_mate.llm.client._jittered_backoff",
        side_effect=[1.0],
    ) as mock_backoff, patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await llm_client.chat([{"role": "user", "content": "test"}])

    assert result == "connected"
    assert llm_client._client.post.call_count == 2
    # Jittered backoff: attempt 1 → 1.0s
    mock_backoff.assert_called_once_with(1)
    mock_sleep.assert_called_once_with(1.0)


@pytest.mark.asyncio
async def test_chat_raises_after_max_retries(llm_client: LLMClient) -> None:
    """chat() raises LLMError after exhausting all retry attempts."""
    llm_client._client.post = AsyncMock(
        side_effect=httpx.ReadTimeout("timeout")
    )

    with patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(LLMError, match="failed after 3 attempts"):
            await llm_client.chat([{"role": "user", "content": "test"}])

    assert llm_client._client.post.call_count == 3


@pytest.mark.asyncio
async def test_chat_raises_on_api_error_no_retry(llm_client: LLMClient) -> None:
    """chat() raises LLMError immediately on HTTPStatusError (no retry)."""
    llm_client._client.post = AsyncMock(
        side_effect=_make_httpx_status_error(400)
    )

    with pytest.raises(LLMError, match="AI service error"):
        await llm_client.chat([{"role": "user", "content": "test"}])

    # Should NOT retry — only 1 attempt
    assert llm_client._client.post.call_count == 1


@pytest.mark.asyncio
async def test_chat_raises_on_none_content(llm_client: LLMClient) -> None:
    """chat() raises LLMError when the response has None content.

    Note: chat() has a general ``except Exception`` handler that wraps any
    non-HTTPStatusError (including the ``LLMError("LLM returned empty response.")``
    raised on None content) into a generic message.
    """
    llm_client._client.post = AsyncMock(
        return_value=_make_httpx_response_none_content()
    )

    with pytest.raises(LLMError, match="empty response"):
        await llm_client.chat([{"role": "user", "content": "test"}])


@pytest.mark.asyncio
async def test_chat_uses_specified_model(llm_client: LLMClient) -> None:
    """chat() passes the model override to the API call."""
    llm_client._client.post = AsyncMock(
        return_value=_make_httpx_response("ok")
    )
    await llm_client.chat(
        [{"role": "user", "content": "test"}],
        model="custom-model",
    )
    call_kwargs = llm_client._client.post.call_args
    body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
    assert body["model"] == "custom-model"


@pytest.mark.asyncio
async def test_chat_defaults_to_self_model(llm_client: LLMClient) -> None:
    """chat() uses self.model when no model override is given."""
    llm_client._client.post = AsyncMock(
        return_value=_make_httpx_response("ok")
    )
    await llm_client.chat([{"role": "user", "content": "test"}])
    call_kwargs = llm_client._client.post.call_args
    body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
    assert body["model"] == "test-model"


# ---------------------------------------------------------------------------
# chat_json() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_json_success(llm_client: LLMClient) -> None:
    """chat_json() returns a parsed dict on valid JSON response."""
    llm_client._client.post = AsyncMock(
        return_value=_make_httpx_response(json.dumps({"pillar": "content", "action": "caption"}))
    )
    result = await llm_client.chat_json([{"role": "user", "content": "test"}])
    assert result == {"pillar": "content", "action": "caption"}


@pytest.mark.asyncio
async def test_chat_json_retries_on_invalid_json(llm_client: LLMClient) -> None:
    """chat_json() retries on JSONDecodeError, then succeeds."""
    llm_client._client.post = AsyncMock(
        side_effect=[
            _make_httpx_response("not valid json {{{"),
            _make_httpx_response(json.dumps({"ok": True})),
        ]
    )

    with patch(
        "digital_mate.llm.client._jittered_backoff",
        side_effect=[1.0],
    ) as mock_backoff, patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await llm_client.chat_json([{"role": "user", "content": "test"}])

    assert result == {"ok": True}
    assert llm_client._client.post.call_count == 2
    mock_backoff.assert_called_once_with(1)
    mock_sleep.assert_called_once_with(1.0)


@pytest.mark.asyncio
async def test_chat_json_raises_on_non_dict_json(llm_client: LLMClient) -> None:
    """chat_json() raises LLMError when JSON is not a dict (e.g. array)."""
    llm_client._client.post = AsyncMock(
        return_value=_make_httpx_response(json.dumps([1, 2, 3]))
    )

    with pytest.raises(LLMError, match="non-object JSON"):
        await llm_client.chat_json([{"role": "user", "content": "test"}])


@pytest.mark.asyncio
async def test_chat_json_uses_router_model_by_default(llm_client: LLMClient) -> None:
    """chat_json() uses self.router_model when no model override is given."""
    llm_client._client.post = AsyncMock(
        return_value=_make_httpx_response(json.dumps({"result": "ok"}))
    )
    await llm_client.chat_json([{"role": "user", "content": "test"}])
    call_kwargs = llm_client._client.post.call_args
    body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
    assert body["model"] == "test-router-model"


@pytest.mark.asyncio
async def test_chat_json_raises_on_none_content(llm_client: LLMClient) -> None:
    """chat_json() raises LLMError when the response has None content."""
    llm_client._client.post = AsyncMock(
        return_value=_make_httpx_response_none_content()
    )

    with pytest.raises(LLMError, match="empty response"):
        await llm_client.chat_json([{"role": "user", "content": "test"}])


@pytest.mark.asyncio
async def test_chat_json_raises_on_timeout_after_retries(llm_client: LLMClient) -> None:
    """chat_json() raises LLMError after max retries on timeout."""
    llm_client._client.post = AsyncMock(
        side_effect=httpx.ReadTimeout("timeout")
    )

    with patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(LLMError, match="failed after 3 attempts"):
            await llm_client.chat_json([{"role": "user", "content": "test"}])


@pytest.mark.asyncio
async def test_chat_json_raises_on_api_error(llm_client: LLMClient) -> None:
    """chat_json() raises LLMError immediately on HTTPStatusError."""
    llm_client._client.post = AsyncMock(
        side_effect=_make_httpx_status_error(400)
    )

    with pytest.raises(LLMError, match="AI service error"):
        await llm_client.chat_json([{"role": "user", "content": "test"}])

    assert llm_client._client.post.call_count == 1


# ---------------------------------------------------------------------------
# chat_stream() tests
# ---------------------------------------------------------------------------


def _make_sse_lines(chunks: list[dict[str, Any] | None]) -> list[str]:
    """Convert content delta dicts to SSE-formatted lines.

    Each chunk is either:
    - A dict with delta content, e.g. {"choices": [{"delta": {"content": "Hello"}}]}
    - None for final/empty chunks
    Returns lines in "data: {...}" format, plus a final "data: [DONE]" line.
    """
    lines = []
    for chunk in chunks:
        if chunk is None:
            lines.append("data: [DONE]")
        else:
            lines.append(f"data: {json.dumps(chunk)}")
    return lines


def _sse_chunk(content: str | None) -> dict:
    """Build an SSE chat completion chunk dict."""
    return {"choices": [{"delta": {"content": content}}]}


class _MockStreamResponse:
    """Mock for httpx stream context manager that yields SSE lines."""

    def __init__(self, lines: list[str], *, raise_on_status: bool = False) -> None:
        self._lines = lines
        self._raise_on_status = raise_on_status
        self.status_code = 200

    def raise_for_status(self) -> None:
        if self._raise_on_status:
            raise _make_httpx_status_error(500)

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


@pytest.mark.asyncio
async def test_chat_stream_yields_chunks(llm_client: LLMClient) -> None:
    """chat_stream() yields text delta chunks in order."""
    sse_lines = _make_sse_lines([
        _sse_chunk("Hello"),
        _sse_chunk(", "),
        _sse_chunk("world"),
        _sse_chunk("!"),
        _sse_chunk(None),  # no-content delta (ignored)
        None,  # [DONE]
    ])
    llm_client._client.stream = MagicMock(
        return_value=_MockStreamResponse(sse_lines)
    )

    chunks = [c async for c in llm_client.chat_stream([{"role": "user", "content": "hi"}])]

    assert chunks == ["Hello", ", ", "world", "!"]
    # stream=True must be in the request body
    call_kwargs = llm_client._client.stream.call_args
    body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
    assert body.get("stream") is True


@pytest.mark.asyncio
async def test_chat_stream_retries_on_timeout_then_success(llm_client: LLMClient) -> None:
    """chat_stream() retries on httpx.TimeoutException and succeeds on a later attempt."""
    good_lines = _make_sse_lines([_sse_chunk("recovered"), None])
    llm_client._client.stream = MagicMock(
        side_effect=[
            httpx.ReadTimeout("timeout"),
            _MockStreamResponse(good_lines),
        ]
    )

    with patch(
        "digital_mate.llm.client._jittered_backoff",
        side_effect=[1.0],
    ) as mock_backoff, patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        chunks = [c async for c in llm_client.chat_stream([{"role": "user", "content": "hi"}])]

    assert chunks == ["recovered"]
    assert llm_client._client.stream.call_count == 2
    mock_backoff.assert_called_once_with(1)
    mock_sleep.assert_called_once_with(1.0)


@pytest.mark.asyncio
async def test_chat_stream_detects_stale_and_retries(llm_client: LLMClient) -> None:
    """chat_stream() kills a stale stream (no data within stale_timeout) and retries."""
    good_lines = _make_sse_lines([_sse_chunk("fresh"), None])
    stale_lines = _make_sse_lines([_sse_chunk(None), _sse_chunk("late"), None])
    llm_client._client.stream = MagicMock(
        side_effect=[
            _MockStreamResponse(stale_lines),
            _MockStreamResponse(good_lines),
        ]
    )
    llm_client.stale_timeout = 5.0

    # monotonic sequence: stream start, first chunk check (stale!), retry start,
    # then good-stream checks (all fresh).
    t = iter([0.0, 10.0, 0.0, 0.1, 0.2])

    with patch("digital_mate.llm.client.time.monotonic", side_effect=lambda: next(t)), patch(
        "digital_mate.llm.client._jittered_backoff", side_effect=[1.0]
    ), patch("asyncio.sleep", new_callable=AsyncMock):
        chunks = [c async for c in llm_client.chat_stream([{"role": "user", "content": "hi"}])]

    assert chunks == ["fresh"]
    assert llm_client._client.stream.call_count == 2


@pytest.mark.asyncio
async def test_chat_stream_exhausts_retries(llm_client: LLMClient) -> None:
    """chat_stream() raises LLMError after all retry attempts are exhausted."""
    llm_client._client.stream = MagicMock(
        side_effect=httpx.ReadTimeout("timeout")
    )

    with patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(LLMError, match="failed after 3 attempts"):
            async for _ in llm_client.chat_stream([{"role": "user", "content": "hi"}]):
                pass

    assert llm_client._client.stream.call_count == 3
