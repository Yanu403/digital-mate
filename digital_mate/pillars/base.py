"""Base class for all marketing pillars.

Defines the common interface and shared functionality.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

from digital_mate.llm.client import LLMClient, LLMError
from digital_mate.llm.prompts import build_pillar_messages, build_brand_context
from digital_mate.memory.brand_profile import BrandProfile

logger = logging.getLogger(__name__)


class BasePillar(ABC):
    """Abstract base class for marketing pillars.

    Each pillar handles a specific domain of digital marketing
    and generates responses using the LLM.
    """

    PILLAR_NAME: str = ""
    MAX_RESPONSE_TOKENS: int = 2048

    def __init__(
        self,
        llm_client: LLMClient,
        language: str = "bilingual",
        bot_name: str = "Digital Mate",
    ) -> None:
        """Initialize the pillar.

        Args:
            llm_client: LLM client for generating responses.
            language: Language setting (bilingual/en/id).
            bot_name: Bot display name.
        """
        self.llm_client = llm_client
        self.language = language
        self.bot_name = bot_name

    @abstractmethod
    async def handle(
        self,
        user_message: str,
        action: str,
        context: list[dict[str, str]],
        brand_profile: BrandProfile | None = None,
        **kwargs: Any,
    ) -> str:
        """Handle a user message for this pillar.

        Args:
            user_message: The user's message text.
            action: The classified action from the router.
            context: Recent conversation context.
            brand_profile: Optional brand profile for personalization.
            **kwargs: Additional pillar-specific arguments.

        Returns:
            Formatted response text.
        """
        ...

    async def handle_stream(
        self,
        user_message: str,
        action: str,
        context: list[dict[str, str]],
        brand_profile: BrandProfile | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream a response for this pillar, yielding text chunks as they arrive.

        Mirrors :meth:`handle` but uses :meth:`LLMClient.chat_stream` for
        real-time token delivery. Message building is identical to
        :meth:`_generate_response` (via :func:`build_pillar_messages`).
        On an :class:`LLMError` the error message is yielded as a single
        chunk (same text as :meth:`handle` would return) and the generator
        stops — callers receive the error inline rather than via an exception.

        Args:
            user_message: The user's message text.
            action: The classified action from the router.
            context: Recent conversation context.
            brand_profile: Optional brand profile for personalization.
            **kwargs: Additional pillar-specific arguments (e.g. search_context, key_facts).

        Yields:
            Text chunks (delta content) from the LLM stream.
        """
        brand_context = self._build_brand_context(brand_profile)
        search_context = kwargs.get("search_context", "")
        key_facts = kwargs.get("key_facts", "")
        messages = build_pillar_messages(
            user_message=user_message,
            pillar=self.PILLAR_NAME,
            context=context,
            language=self.language,
            bot_name=self.bot_name,
            brand_context=brand_context,
            search_context=search_context,
            key_facts=key_facts,
        )
        try:
            async for chunk in self.llm_client.chat_stream(
                messages, max_tokens=self.MAX_RESPONSE_TOKENS
            ):
                yield chunk
        except LLMError as exc:
            logger.error("LLM stream error in %s pillar: %s", self.PILLAR_NAME, exc)
            yield (
                "⚠️ Sorry, I encountered an error generating a response. "
                "Please try again in a moment.\n\n"
                f"(Error: {exc})"
            )

    def _build_brand_context(self, profile: BrandProfile | None) -> str:
        """Build the brand context string for LLM prompts.

        Args:
            profile: Optional brand profile.

        Returns:
            Formatted brand context string or empty string.
        """
        if profile is None:
            return ""
        return build_brand_context(
            name=profile.name,
            industry=profile.industry,
            audience=profile.audience,
            tone=profile.tone,
            products=profile.products,
            hashtags=profile.hashtags,
            competitors=profile.competitors,
            platform_preference=profile.platform_preference,
            budget_range=profile.budget_range,
            business_stage=profile.business_stage,
        )

    async def _generate_response(
        self,
        user_message: str,
        context: list[dict[str, str]],
        brand_context: str = "",
        search_context: str = "",
        key_facts: str = "",
    ) -> str:
        """Generate an LLM response for this pillar.

        Args:
            user_message: User's message.
            context: Conversation context.
            brand_context: Brand profile context.
            search_context: Search results context (Research pillar).
            key_facts: Key facts context for personalization.

        Returns:
            LLM-generated response text.
        """
        messages = build_pillar_messages(
            user_message=user_message,
            pillar=self.PILLAR_NAME,
            context=context,
            language=self.language,
            bot_name=self.bot_name,
            brand_context=brand_context,
            search_context=search_context,
            key_facts=key_facts,
        )

        try:
            return await self.llm_client.chat(messages, max_tokens=self.MAX_RESPONSE_TOKENS)
        except LLMError as exc:
            logger.error("LLM error in %s pillar: %s", self.PILLAR_NAME, exc)
            return f"⚠️ Sorry, I encountered an error generating a response. Please try again in a moment.\n\n(Error: {exc})"
