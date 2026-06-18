"""Content & Copywriting pillar.

Handles social media captions, hooks, hashtags, CTAs, content ideas,
rewriting, and content calendar discussions.
"""

from __future__ import annotations

import logging
from typing import Any

from digital_mate.pillars.base import BasePillar
from digital_mate.memory.brand_profile import BrandProfile

logger = logging.getLogger(__name__)


class ContentPillar(BasePillar):
    """Content & Copywriting pillar implementation.

    Generates engaging social media content including captions, hooks,
    hashtags, CTAs, and content ideas tailored to the user's brand.
    """

    PILLAR_NAME = "content"

    async def handle(
        self,
        user_message: str,
        action: str,
        context: list[dict[str, str]],
        brand_profile: BrandProfile | None = None,
        **kwargs: Any,
    ) -> str:
        """Handle a content-related user message.

        Args:
            user_message: The user's message text.
            action: Classified action (caption, hooks, hashtags, etc.).
            context: Recent conversation context.
            brand_profile: Optional brand profile for personalization.
            **kwargs: Additional arguments.

        Returns:
            Generated content response.
        """
        brand_context = self._build_brand_context(brand_profile)

        # Add action-specific instructions to the user message
        enhanced_message = self._enhance_message(user_message, action)

        response = await self._generate_response(
            user_message=enhanced_message,
            context=context,
            brand_context=brand_context,
        )

        return response

    def _enhance_message(self, user_message: str, action: str) -> str:
        """Add action-specific context to the user message.

        Args:
            user_message: Original user message.
            action: Classified action.

        Returns:
            Enhanced message with action hints.
        """
        hints = {
            "caption": "Please write a social media caption with relevant hashtags (3-7 hashtags).",
            "hooks": "Please generate 5 numbered hook ideas that grab attention in the first 3 seconds.",
            "hashtags": "Please suggest 10-15 relevant hashtags, mixing popular and niche tags.",
            "cta": "Please write 3 different call-to-action options with explanations.",
            "rewrite": "Please rewrite and improve the text, explaining what you changed and why.",
            "ideas": "Please brainstorm 5-7 content ideas with brief descriptions.",
            "calendar": "Please help plan a content calendar with specific post ideas for each day.",
        }
        hint = hints.get(action, "")
        if hint:
            return f"{hint}\n\nUser request: {user_message}"
        return user_message
