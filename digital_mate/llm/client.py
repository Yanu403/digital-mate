"""Async LLM client using OpenAI-compatible API.

Provides retry logic with jittered backoff, structured JSON responses,
and streaming support for real-time token delivery.

Retry strategy adopted from Hermes' jittered_backoff pattern:
decorrelated exponential backoff with random jitter to prevent
thundering-herd retry spikes when multiple users hit the same API
concurrently.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from typing import Any, AsyncIterator

from openai import AsyncOpenAI, APIError, APITimeoutError, APIConnectionError

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Raised when LLM request fails after all retries."""
    pass


def _jittered_backoff(
    attempt: int,
    *,
    base_delay: float = 2.0,
    max_delay: float = 30.0,
    jitter_ratio: float = 0.5,
) -> float:
    """Compute a jittered exponential backoff delay.

    Mirrors Hermes' retry_utils.jittered_backoff — decorrelated
    delays prevent thundering-herd retry spikes.

    Args:
        attempt: 1-based retry attempt number.
        base_delay: Base delay in seconds for attempt 1.
        max_delay: Maximum delay cap in seconds.
        jitter_ratio: Fraction of delay used as random jitter range.

    Returns:
        Delay in seconds: min(base * 2^(attempt-1), max_delay) + jitter.
    """
    exponent = max(0, attempt - 1)
    if exponent >= 63 or base_delay <= 0:
        delay = max_delay
    else:
        delay = min(base_delay * (2 ** exponent), max_delay)
    jitter = random.uniform(0, jitter_ratio * delay)
    return delay + jitter


class LLMClient:
    """Async wrapper around OpenAI-compatible chat completions API.

    Supports standard chat, streaming chat, and JSON-mode responses
    with automatic retry using jittered backoff.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        router_model: str | None = None,
        max_retries: int = 3,
        timeout: float = 120.0,
        stale_timeout: float = 30.0,
    ) -> None:
        """Initialize the LLM client.

        Args:
            base_url: API base URL.
            api_key: API key for authentication.
            model: Default model to use for chat completions.
            router_model: Model to use for routing (defaults to model).
            max_retries: Maximum number of retry attempts.
            timeout: Request timeout in seconds (read timeout for streaming).
            stale_timeout: Seconds without any data before killing a stream.
        """
        self._client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
        )
        self.model = model
        self.router_model = router_model or model
        self.max_retries = max_retries
        self.timeout = timeout
        self.stale_timeout = stale_timeout

    # ------------------------------------------------------------------
    # Non-streaming chat
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        model: str | None = None,
    ) -> str:
        """Send a chat completion request and return the response text.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens in the response.
            model: Override model (defaults to self.model).

        Returns:
            The assistant's response text.

        Raises:
            LLMError: If the request fails after all retries.
        """
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                response = await self._client.chat.completions.create(
                    model=model or self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                content = response.choices[0].message.content
                if not content or not content.strip():
                    raise LLMError("LLM returned empty response.")
                return content.strip()

            except (APITimeoutError, APIConnectionError) as exc:
                last_error = exc
                if attempt < self.max_retries - 1:
                    wait = _jittered_backoff(attempt + 1)
                    logger.warning(
                        "LLM request failed (attempt %d/%d): %s — retrying in %.1fs",
                        attempt + 1, self.max_retries, exc, wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error("LLM request timed out after %d attempts: %s", self.max_retries, exc)

            except APIError as exc:
                last_error = exc
                logger.error("LLM API error: %s", exc)
                raise LLMError(f"AI service error: {exc.message}") from exc

            except Exception as exc:
                last_error = exc
                logger.error("Unexpected LLM error: %s", exc)
                raise LLMError("An unexpected error occurred while contacting the AI service.") from exc

        raise LLMError(f"LLM request failed after {self.max_retries} attempts: {last_error}")

    # ------------------------------------------------------------------
    # Streaming chat
    # ------------------------------------------------------------------

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        model: str | None = None,
    ) -> AsyncIterator[str]:
        """Stream a chat completion, yielding text chunks as they arrive.

        Uses stream=True so the first token arrives as soon as the
        model starts generating, rather than waiting for the full
        response.  Includes a stale-call detector: if no chunk arrives
        within ``stale_timeout`` seconds, the connection is killed and
        retried.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens in the response.
            model: Override model (defaults to self.model).

        Yields:
            Text chunks (delta content) as they arrive from the API.

        Raises:
            LLMError: If the request fails after all retries.
        """
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                stream = await self._client.chat.completions.create(
                    model=model or self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=True,
                    stream_options={"include_usage": True},
                )

                last_chunk_time = time.monotonic()
                got_any_chunk = False

                async for chunk in stream:
                    now = time.monotonic()
                    # Stale detection: no data for stale_timeout seconds
                    if now - last_chunk_time > self.stale_timeout:
                        logger.warning(
                            "Stream stale for %.0fs (threshold %.0fs) — killing and retrying (attempt %d/%d)",
                            now - last_chunk_time, self.stale_timeout,
                            attempt + 1, self.max_retries,
                        )
                        raise _StaleStreamError()

                    last_chunk_time = now

                    if chunk.choices and chunk.choices[0].delta.content:
                        got_any_chunk = True
                        yield chunk.choices[0].delta.content

                # Stream completed successfully
                if not got_any_chunk:
                    logger.warning("Stream completed but produced no content (attempt %d/%d)", attempt + 1, self.max_retries)
                    # Don't raise — might be an empty-but-valid response
                return

            except _StaleStreamError:
                # Retry with backoff
                last_error = Exception("Stream stale — no data received within timeout")
                if attempt < self.max_retries - 1:
                    wait = _jittered_backoff(attempt + 1)
                    logger.warning("Retrying stale stream in %.1fs (attempt %d/%d)", wait, attempt + 1, self.max_retries)
                    await asyncio.sleep(wait)
                continue

            except (APITimeoutError, APIConnectionError) as exc:
                last_error = exc
                if attempt < self.max_retries - 1:
                    wait = _jittered_backoff(attempt + 1)
                    logger.warning(
                        "LLM stream failed (attempt %d/%d): %s — retrying in %.1fs",
                        attempt + 1, self.max_retries, exc, wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error("LLM stream timed out after %d attempts: %s", self.max_retries, exc)

            except APIError as exc:
                last_error = exc
                logger.error("LLM API error (stream): %s", exc)
                raise LLMError(f"AI service error: {exc.message}") from exc

            except Exception as exc:
                last_error = exc
                logger.error("Unexpected LLM stream error: %s", exc)
                raise LLMError("An unexpected error occurred while contacting the AI service.") from exc

        raise LLMError(f"LLM stream failed after {self.max_retries} attempts: {last_error}")

    # ------------------------------------------------------------------
    # Vision chat (image + text)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_vision_messages(
        messages: list[dict[str, str]],
        image_base64: str,
        image_mime_type: str = "image/jpeg",
    ) -> list[dict[str, Any]]:
        """Inject an image into the last user message of a chat message list.

        Converts the last user message's ``content`` from a plain string into
        the OpenAI vision content-array format::

            [{"type": "text", "text": "..."},
             {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}]

        All preceding messages (system, assistant, earlier user turns) are
        passed through unchanged so conversation context is preserved.

        Args:
            messages: Original message list (role/content string dicts).
            image_base64: Base64-encoded image data (without the data: prefix).
            image_mime_type: MIME type of the image (default image/jpeg).

        Returns:
            New message list with the last user message converted to vision
            content-array format.

        Raises:
            ValueError: If no user message is found in *messages*.
        """
        if not messages:
            raise ValueError("messages must contain at least one user message for vision.")

        data_url = f"data:{image_mime_type};base64,{image_base64}"
        vision_messages: list[dict[str, Any]] = []

        # Find the index of the last user message
        last_user_idx = -1
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "user":
                last_user_idx = i
                break

        if last_user_idx == -1:
            raise ValueError("No user message found in messages for vision attachment.")

        for i, msg in enumerate(messages):
            if i == last_user_idx:
                original_text = msg.get("content", "")
                vision_messages.append({
                    "role": "user",
                    "content": [
                        {"type": "text", "text": original_text},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                })
            else:
                vision_messages.append(dict(msg))

        return vision_messages

    async def chat_with_image(
        self,
        messages: list[dict[str, str]],
        image_base64: str,
        image_mime_type: str = "image/jpeg",
        temperature: float = 0.7,
        max_tokens: int = 2048,
        model: str | None = None,
    ) -> str:
        """Send a chat completion with an image attached (vision).

        Constructs a message with a content array containing text and
        ``image_url``, then calls the chat completions API. The last user
        message in *messages* receives the image; all other messages pass
        through unchanged so conversation context is preserved.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            image_base64: Base64-encoded image data (without data: prefix).
            image_mime_type: MIME type of the image (default image/jpeg).
            temperature: Sampling temperature.
            max_tokens: Maximum tokens in the response.
            model: Override model (defaults to self.model).

        Returns:
            The assistant's response text.

        Raises:
            LLMError: If the request fails after all retries.
            ValueError: If no user message is found in *messages*.
        """
        vision_messages = self._build_vision_messages(
            messages, image_base64, image_mime_type
        )
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                response = await self._client.chat.completions.create(
                    model=model or self.model,
                    messages=vision_messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                content = response.choices[0].message.content
                if not content or not content.strip():
                    raise LLMError("LLM returned empty response.")
                return content.strip()

            except (APITimeoutError, APIConnectionError) as exc:
                last_error = exc
                if attempt < self.max_retries - 1:
                    wait = _jittered_backoff(attempt + 1)
                    logger.warning(
                        "LLM vision request failed (attempt %d/%d): %s — retrying in %.1fs",
                        attempt + 1, self.max_retries, exc, wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error("LLM vision request timed out after %d attempts: %s", self.max_retries, exc)

            except APIError as exc:
                last_error = exc
                logger.error("LLM API error (vision): %s", exc)
                raise LLMError(f"AI service error: {exc.message}") from exc

            except LLMError:
                raise

            except Exception as exc:
                last_error = exc
                logger.error("Unexpected LLM vision error: %s", exc)
                raise LLMError("An unexpected error occurred while contacting the AI service.") from exc

        raise LLMError(f"LLM vision request failed after {self.max_retries} attempts: {last_error}")

    async def chat_with_image_stream(
        self,
        messages: list[dict[str, str]],
        image_base64: str,
        image_mime_type: str = "image/jpeg",
        temperature: float = 0.7,
        max_tokens: int = 2048,
        model: str | None = None,
    ) -> AsyncIterator[str]:
        """Stream a chat completion with an image attached (vision).

        Same pattern as :meth:`chat_stream` but injects an image into the
        last user message using the vision content-array format.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            image_base64: Base64-encoded image data (without data: prefix).
            image_mime_type: MIME type of the image (default image/jpeg).
            temperature: Sampling temperature.
            max_tokens: Maximum tokens in the response.
            model: Override model (defaults to self.model).

        Yields:
            Text chunks (delta content) as they arrive from the API.

        Raises:
            LLMError: If the request fails after all retries.
            ValueError: If no user message is found in *messages*.
        """
        vision_messages = self._build_vision_messages(
            messages, image_base64, image_mime_type
        )
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                stream = await self._client.chat.completions.create(
                    model=model or self.model,
                    messages=vision_messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=True,
                    stream_options={"include_usage": True},
                )

                last_chunk_time = time.monotonic()
                got_any_chunk = False

                async for chunk in stream:
                    now = time.monotonic()
                    if now - last_chunk_time > self.stale_timeout:
                        logger.warning(
                            "Vision stream stale for %.0fs (threshold %.0fs) — killing and retrying (attempt %d/%d)",
                            now - last_chunk_time, self.stale_timeout,
                            attempt + 1, self.max_retries,
                        )
                        raise _StaleStreamError()

                    last_chunk_time = now

                    if chunk.choices and chunk.choices[0].delta.content:
                        got_any_chunk = True
                        yield chunk.choices[0].delta.content

                if not got_any_chunk:
                    logger.warning("Vision stream completed but produced no content (attempt %d/%d)", attempt + 1, self.max_retries)
                return

            except _StaleStreamError:
                last_error = Exception("Vision stream stale — no data received within timeout")
                if attempt < self.max_retries - 1:
                    wait = _jittered_backoff(attempt + 1)
                    logger.warning("Retrying stale vision stream in %.1fs (attempt %d/%d)", wait, attempt + 1, self.max_retries)
                    await asyncio.sleep(wait)
                continue

            except (APITimeoutError, APIConnectionError) as exc:
                last_error = exc
                if attempt < self.max_retries - 1:
                    wait = _jittered_backoff(attempt + 1)
                    logger.warning(
                        "LLM vision stream failed (attempt %d/%d): %s — retrying in %.1fs",
                        attempt + 1, self.max_retries, exc, wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error("LLM vision stream timed out after %d attempts: %s", self.max_retries, exc)

            except APIError as exc:
                last_error = exc
                logger.error("LLM API error (vision stream): %s", exc)
                raise LLMError(f"AI service error: {exc.message}") from exc

            except Exception as exc:
                last_error = exc
                logger.error("Unexpected LLM vision stream error: %s", exc)
                raise LLMError("An unexpected error occurred while contacting the AI service.") from exc

        raise LLMError(f"LLM vision stream failed after {self.max_retries} attempts: {last_error}")

    # ------------------------------------------------------------------
    # JSON-mode chat (for router classification)
    # ------------------------------------------------------------------

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 512,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Send a chat completion request expecting a JSON response.

        Uses response_format={"type": "json_object"} to enforce JSON output.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            temperature: Sampling temperature (low for classification).
            max_tokens: Maximum tokens in the response.
            model: Override model (defaults to router_model for JSON calls).

        Returns:
            Parsed JSON dict.

        Raises:
            LLMError: If the request fails or response is not valid JSON.
        """
        last_error: Exception | None = None
        use_model = model or self.router_model

        for attempt in range(self.max_retries):
            try:
                response = await self._client.chat.completions.create(
                    model=use_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"},
                )
                content = response.choices[0].message.content
                if not content or not content.strip():
                    raise LLMError("LLM returned empty JSON response.")

                try:
                    parsed = json.loads(content)
                except json.JSONDecodeError as exc:
                    last_error = exc
                    logger.warning("JSON decode failed (attempt %d/%d): %s", attempt + 1, self.max_retries, exc)
                    if attempt < self.max_retries - 1:
                        wait = _jittered_backoff(attempt + 1)
                        await asyncio.sleep(wait)
                    continue

                if not isinstance(parsed, dict):
                    raise LLMError("LLM returned non-object JSON response.")
                logger.debug("LLM JSON response: %.200s", content)
                return parsed

            except (APITimeoutError, APIConnectionError) as exc:
                last_error = exc
                if attempt < self.max_retries - 1:
                    wait = _jittered_backoff(attempt + 1)
                    logger.warning(
                        "LLM JSON request failed (attempt %d/%d): %s — retrying in %.1fs",
                        attempt + 1, self.max_retries, exc, wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error("LLM JSON request timed out after %d attempts: %s", self.max_retries, exc)

            except APIError as exc:
                last_error = exc
                logger.error("LLM API error (JSON): %s", exc)
                raise LLMError(f"AI service error: {exc.message}") from exc

            except LLMError:
                raise

            except Exception as exc:
                last_error = exc
                logger.error("Unexpected LLM JSON error: %s", exc)
                raise LLMError("An unexpected error occurred while contacting the AI service.") from exc

        raise LLMError(f"LLM JSON request failed after {self.max_retries} attempts: {last_error}")


class _StaleStreamError(Exception):
    """Internal sentinel raised when a stream goes stale (no data for N seconds)."""
    pass
