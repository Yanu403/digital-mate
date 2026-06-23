"""Tests for digital_mate.llm.client module.

Covers chat() and chat_json() success paths, retry logic with exponential
backoff on transient errors, error handling for non-retryable failures,
edge cases like None content and non-dict JSON, and model selection.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from openai import APIConnectionError, APIError, APITimeoutError

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


def _make_response(content: str) -> MagicMock:
    """Build a mock OpenAI ChatCompletion response with given content."""
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=content))]
    return resp


# ---------------------------------------------------------------------------
# chat() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_success_strips_whitespace(llm_client: LLMClient) -> None:
    """chat() returns stripped content."""
    llm_client._client.chat.completions.create = AsyncMock(
        return_value=_make_response("  Hello world  ")
    )
    result = await llm_client.chat([{"role": "user", "content": "hi"}])
    assert result == "Hello world"


@pytest.mark.asyncio
async def test_chat_retries_on_timeout(llm_client: LLMClient) -> None:
    """chat() retries on APITimeoutError with exponential backoff."""
    mock_success = _make_response("recovered")
    llm_client._client.chat.completions.create = AsyncMock(
        side_effect=[
            APITimeoutError(request=MagicMock()),
            APITimeoutError(request=MagicMock()),
            mock_success,
        ]
    )

    with patch(
        "digital_mate.llm.client._jittered_backoff",
        side_effect=[1.0, 2.0],
    ) as mock_backoff, patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await llm_client.chat([{"role": "user", "content": "test"}])

    assert result == "recovered"
    assert llm_client._client.chat.completions.create.call_count == 3
    # Jittered exponential backoff: attempt 1 → 1.0s, attempt 2 → 2.0s
    mock_backoff.assert_any_call(1)
    mock_backoff.assert_any_call(2)
    mock_sleep.assert_any_call(1.0)
    mock_sleep.assert_any_call(2.0)


@pytest.mark.asyncio
async def test_chat_retries_on_connection_error(llm_client: LLMClient) -> None:
    """chat() retries on APIConnectionError with exponential backoff."""
    mock_success = _make_response("connected")
    llm_client._client.chat.completions.create = AsyncMock(
        side_effect=[
            APIConnectionError(request=MagicMock()),
            mock_success,
        ]
    )

    with patch(
        "digital_mate.llm.client._jittered_backoff",
        side_effect=[1.0],
    ) as mock_backoff, patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await llm_client.chat([{"role": "user", "content": "test"}])

    assert result == "connected"
    assert llm_client._client.chat.completions.create.call_count == 2
    # Jittered backoff: attempt 1 → 1.0s
    mock_backoff.assert_called_once_with(1)
    mock_sleep.assert_called_once_with(1.0)


@pytest.mark.asyncio
async def test_chat_raises_after_max_retries(llm_client: LLMClient) -> None:
    """chat() raises LLMError after exhausting all retry attempts."""
    llm_client._client.chat.completions.create = AsyncMock(
        side_effect=APITimeoutError(request=MagicMock())
    )

    with patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(LLMError, match="failed after 3 attempts"):
            await llm_client.chat([{"role": "user", "content": "test"}])

    assert llm_client._client.chat.completions.create.call_count == 3


@pytest.mark.asyncio
async def test_chat_raises_on_api_error_no_retry(llm_client: LLMClient) -> None:
    """chat() raises LLMError immediately on APIError (no retry)."""
    mock_request = MagicMock()
    mock_request.url = "http://test"
    llm_client._client.chat.completions.create = AsyncMock(
        side_effect=APIError(
            message="rate limited",
            request=mock_request,
            body=None,
        )
    )

    with pytest.raises(LLMError, match="AI service error"):
        await llm_client.chat([{"role": "user", "content": "test"}])

    # Should NOT retry — only 1 attempt
    assert llm_client._client.chat.completions.create.call_count == 1


@pytest.mark.asyncio
async def test_chat_raises_on_none_content(llm_client: LLMClient) -> None:
    """chat() raises LLMError when the response has None content.

    Note: chat() has a general ``except Exception`` handler that wraps any
    non-APIError (including the ``LLMError("LLM returned empty response.")``
    raised on None content) into a generic message.
    """
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=None))]
    llm_client._client.chat.completions.create = AsyncMock(return_value=resp)

    with pytest.raises(LLMError, match="unexpected error"):
        await llm_client.chat([{"role": "user", "content": "test"}])


@pytest.mark.asyncio
async def test_chat_uses_specified_model(llm_client: LLMClient) -> None:
    """chat() passes the model override to the API call."""
    llm_client._client.chat.completions.create = AsyncMock(
        return_value=_make_response("ok")
    )
    await llm_client.chat(
        [{"role": "user", "content": "test"}],
        model="custom-model",
    )
    call_kwargs = llm_client._client.chat.completions.create.call_args
    assert call_kwargs.kwargs["model"] == "custom-model"


@pytest.mark.asyncio
async def test_chat_defaults_to_self_model(llm_client: LLMClient) -> None:
    """chat() uses self.model when no model override is given."""
    llm_client._client.chat.completions.create = AsyncMock(
        return_value=_make_response("ok")
    )
    await llm_client.chat([{"role": "user", "content": "test"}])
    call_kwargs = llm_client._client.chat.completions.create.call_args
    assert call_kwargs.kwargs["model"] == "test-model"


# ---------------------------------------------------------------------------
# chat_json() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_json_success(llm_client: LLMClient) -> None:
    """chat_json() returns a parsed dict on valid JSON response."""
    llm_client._client.chat.completions.create = AsyncMock(
        return_value=_make_response(json.dumps({"pillar": "content", "action": "caption"}))
    )
    result = await llm_client.chat_json([{"role": "user", "content": "test"}])
    assert result == {"pillar": "content", "action": "caption"}


@pytest.mark.asyncio
async def test_chat_json_retries_on_invalid_json(llm_client: LLMClient) -> None:
    """chat_json() retries on JSONDecodeError, then succeeds."""
    llm_client._client.chat.completions.create = AsyncMock(
        side_effect=[
            _make_response("not valid json {{{"),
            _make_response(json.dumps({"ok": True})),
        ]
    )

    with patch(
        "digital_mate.llm.client._jittered_backoff",
        side_effect=[1.0],
    ) as mock_backoff, patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await llm_client.chat_json([{"role": "user", "content": "test"}])

    assert result == {"ok": True}
    assert llm_client._client.chat.completions.create.call_count == 2
    mock_backoff.assert_called_once_with(1)
    mock_sleep.assert_called_once_with(1.0)


@pytest.mark.asyncio
async def test_chat_json_raises_on_non_dict_json(llm_client: LLMClient) -> None:
    """chat_json() raises LLMError when JSON is not a dict (e.g. array)."""
    llm_client._client.chat.completions.create = AsyncMock(
        return_value=_make_response(json.dumps([1, 2, 3]))
    )

    with pytest.raises(LLMError, match="non-object JSON"):
        await llm_client.chat_json([{"role": "user", "content": "test"}])


@pytest.mark.asyncio
async def test_chat_json_uses_router_model_by_default(llm_client: LLMClient) -> None:
    """chat_json() uses self.router_model when no model override is given."""
    llm_client._client.chat.completions.create = AsyncMock(
        return_value=_make_response(json.dumps({"result": "ok"}))
    )
    await llm_client.chat_json([{"role": "user", "content": "test"}])
    call_kwargs = llm_client._client.chat.completions.create.call_args
    assert call_kwargs.kwargs["model"] == "test-router-model"


@pytest.mark.asyncio
async def test_chat_json_raises_on_none_content(llm_client: LLMClient) -> None:
    """chat_json() raises LLMError when the response has None content."""
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=None))]
    llm_client._client.chat.completions.create = AsyncMock(return_value=resp)

    with pytest.raises(LLMError, match="empty JSON response"):
        await llm_client.chat_json([{"role": "user", "content": "test"}])


@pytest.mark.asyncio
async def test_chat_json_raises_on_timeout_after_retries(llm_client: LLMClient) -> None:
    """chat_json() raises LLMError after max retries on timeout."""
    llm_client._client.chat.completions.create = AsyncMock(
        side_effect=APITimeoutError(request=MagicMock())
    )

    with patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(LLMError, match="failed after 3 attempts"):
            await llm_client.chat_json([{"role": "user", "content": "test"}])


@pytest.mark.asyncio
async def test_chat_json_raises_on_api_error(llm_client: LLMClient) -> None:
    """chat_json() raises LLMError immediately on APIError."""
    mock_request = MagicMock()
    mock_request.url = "http://test"
    llm_client._client.chat.completions.create = AsyncMock(
        side_effect=APIError(
            message="bad request",
            request=mock_request,
            body=None,
        )
    )

    with pytest.raises(LLMError, match="AI service error"):
        await llm_client.chat_json([{"role": "user", "content": "test"}])

    assert llm_client._client.chat.completions.create.call_count == 1


# ---------------------------------------------------------------------------
# chat_stream() tests
# ---------------------------------------------------------------------------


def _make_stream_chunk(content: str | None) -> MagicMock:
    """Build a mock OpenAI streaming chunk with given delta content."""
    chunk = MagicMock()
    chunk.choices = [MagicMock(delta=MagicMock(content=content))]
    return chunk


class _MockAsyncStream:
    """Minimal async-iterable stand-in for the OpenAI stream object.

    chat_stream() iterates ``async for chunk in stream``; this yields the
    provided chunks then stops. Raising an exception in the constructor
    list lets us simulate timeout/connection errors on creation.
    """

    def __init__(self, chunks: list) -> None:
        self._chunks = chunks

    def __aiter__(self) -> _MockAsyncStream:
        return self

    async def __anext__(self) -> Any:
        if not self._chunks:
            raise StopAsyncIteration
        item = self._chunks.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.mark.asyncio
async def test_chat_stream_yields_chunks(llm_client: LLMClient) -> None:
    """chat_stream() yields text delta chunks in order."""
    stream_chunks = [
        _make_stream_chunk("Hello"),
        _make_stream_chunk(", "),
        _make_stream_chunk("world"),
        _make_stream_chunk("!"),
        _make_stream_chunk(None),  # final chunk with no content
    ]
    llm_client._client.chat.completions.create = AsyncMock(
        return_value=_MockAsyncStream(stream_chunks)
    )

    chunks = [c async for c in llm_client.chat_stream([{"role": "user", "content": "hi"}])]

    assert chunks == ["Hello", ", ", "world", "!"]
    # stream=True must be requested
    call_kwargs = llm_client._client.chat.completions.create.call_args
    assert call_kwargs.kwargs.get("stream") is True


@pytest.mark.asyncio
async def test_chat_stream_retries_on_timeout_then_success(llm_client: LLMClient) -> None:
    """chat_stream() retries on APITimeoutError and succeeds on a later attempt."""
    good_chunks = [_make_stream_chunk("recovered")]
    # First create() raises, second returns a working stream.
    llm_client._client.chat.completions.create = AsyncMock(
        side_effect=[
            APITimeoutError(request=MagicMock()),
            _MockAsyncStream(good_chunks),
        ]
    )

    with patch(
        "digital_mate.llm.client._jittered_backoff",
        side_effect=[1.0],
    ) as mock_backoff, patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        chunks = [c async for c in llm_client.chat_stream([{"role": "user", "content": "hi"}])]

    assert chunks == ["recovered"]
    assert llm_client._client.chat.completions.create.call_count == 2
    mock_backoff.assert_called_once_with(1)
    mock_sleep.assert_called_once_with(1.0)


@pytest.mark.asyncio
async def test_chat_stream_detects_stale_and_retries(llm_client: LLMClient) -> None:
    """chat_stream() kills a stale stream (no data within stale_timeout) and retries."""
    # Build a stream whose first real data arrives *after* the stale threshold.
    # We simulate staleness by having the stream yield nothing for long enough
    # that time.monotonic() advances past stale_timeout. To do this
    # deterministically we patch time.monotonic to jump forward.
    good_chunks = [_make_stream_chunk("fresh")]
    stale_stream = _MockAsyncStream([_make_stream_chunk(None), _make_stream_chunk("late")])
    good_stream = _MockAsyncStream(good_chunks)
    llm_client._client.chat.completions.create = AsyncMock(
        side_effect=[stale_stream, good_stream]
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
    assert llm_client._client.chat.completions.create.call_count == 2


@pytest.mark.asyncio
async def test_chat_stream_exhausts_retries(llm_client: LLMClient) -> None:
    """chat_stream() raises LLMError after all retry attempts are exhausted."""
    llm_client._client.chat.completions.create = AsyncMock(
        side_effect=APITimeoutError(request=MagicMock())
    )

    with patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(LLMError, match="failed after 3 attempts"):
            async for _ in llm_client.chat_stream([{"role": "user", "content": "hi"}]):
                pass

    assert llm_client._client.chat.completions.create.call_count == 3
