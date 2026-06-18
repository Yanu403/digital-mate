"""Tests for digital_mate.llm.client module.

Covers chat() and chat_json() success paths, retry logic with exponential
backoff on transient errors, error handling for non-retryable failures,
edge cases like None content and non-dict JSON, and model selection.
"""

from __future__ import annotations

import json
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

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await llm_client.chat([{"role": "user", "content": "test"}])

    assert result == "recovered"
    assert llm_client._client.chat.completions.create.call_count == 3
    # Exponential backoff: 2^0=1, 2^1=2
    mock_sleep.assert_any_call(1)
    mock_sleep.assert_any_call(2)


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

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await llm_client.chat([{"role": "user", "content": "test"}])

    assert result == "connected"
    assert llm_client._client.chat.completions.create.call_count == 2
    mock_sleep.assert_called_once_with(1)


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

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await llm_client.chat_json([{"role": "user", "content": "test"}])

    assert result == {"ok": True}
    assert llm_client._client.chat.completions.create.call_count == 2
    mock_sleep.assert_called_once_with(1)


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
