"""Base class for all marketing pillars.

Defines the common interface and shared functionality.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

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
        )

    async def _generate_response(
        self,
        user_message: str,
        context: list[dict[str, str]],
        brand_context: str = "",
        search_context: str = "",
    ) -> str:
        """Generate an LLM response for this pillar.

        Args:
            user_message: User's message.
            context: Conversation context.
            brand_context: Brand profile context.
            search_context: Search results context (Research pillar).

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
        )

        try:
            return await self.llm_client.chat(messages)
        except LLMError as exc:
            logger.error("LLM error in %s pillar: %s", self.PILLAR_NAME, exc)
            return f"⚠️ Sorry, I encountered an error generating a response. Please try again in a moment.\n\n(Error: {exc})"
