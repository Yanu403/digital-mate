"""Async LLM client using OpenAI-compatible API.

Provides retry logic with exponential backoff and structured JSON responses.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from openai import AsyncOpenAI, APIError, APITimeoutError, APIConnectionError

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Raised when LLM request fails after all retries."""

    pass


class LLMClient:
    """Async wrapper around OpenAI-compatible chat completions API.

    Supports standard chat and JSON-mode responses with automatic retry.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        router_model: str | None = None,
        max_retries: int = 3,
        timeout: float = 60.0,
    ) -> None:
        """Initialize the LLM client.

        Args:
            base_url: API base URL.
            api_key: API key for authentication.
            model: Default model to use for chat completions.
            router_model: Model to use for routing (defaults to model).
            max_retries: Maximum number of retry attempts.
            timeout: Request timeout in seconds.
        """
        self._client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
        )
        self.model = model
        self.router_model = router_model or model
        self.max_retries = max_retries

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
        model = model or self.model
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                response = await self._client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                content = response.choices[0].message.content
                if content is None:
                    raise LLMError("LLM returned empty response.")
                logger.debug("LLM response (%d tokens): %.100s...", len(content), content)
                return content.strip()

            except (APITimeoutError, APIConnectionError) as exc:
                last_error = exc
                wait = 2**attempt  # 1s, 2s, 4s
                logger.warning("LLM request failed (attempt %d/%d): %s — retrying in %ds", attempt + 1, self.max_retries, exc, wait)
                await asyncio.sleep(wait)

            except APIError as exc:
                last_error = exc
                logger.error("LLM API error: %s", exc)
                raise LLMError(f"AI service error: {exc.message}") from exc

            except Exception as exc:
                last_error = exc
                logger.error("Unexpected LLM error: %s", exc)
                raise LLMError("An unexpected error occurred while contacting the AI service.") from exc

        raise LLMError(f"LLM request failed after {self.max_retries} attempts: {last_error}")

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Send a chat request expecting a JSON response.

        Uses response_format={"type": "json_object"} for structured output.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            temperature: Sampling temperature (low for JSON).
            model: Override model (defaults to self.router_model).

        Returns:
            Parsed JSON dict from the response.

        Raises:
            LLMError: If the request fails or response is not valid JSON.
        """
        model = model or self.router_model
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                response = await self._client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    response_format={"type": "json_object"},
                )
                content = response.choices[0].message.content
                if content is None:
                    raise LLMError("LLM returned empty JSON response.")
                parsed = json.loads(content)
                if not isinstance(parsed, dict):
                    raise LLMError("LLM returned non-object JSON response.")
                logger.debug("LLM JSON response: %.200s", content)
                return parsed

            except json.JSONDecodeError as exc:
                last_error = exc
                logger.warning("LLM returned invalid JSON (attempt %d/%d): %s", attempt + 1, self.max_retries, exc)
                await asyncio.sleep(2**attempt)

            except (APITimeoutError, APIConnectionError) as exc:
                last_error = exc
                wait = 2**attempt
                logger.warning("LLM JSON request failed (attempt %d/%d): %s — retrying in %ds", attempt + 1, self.max_retries, exc, wait)
                await asyncio.sleep(wait)

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
