"""Strategy & Planning pillar.

Handles marketing plans, funnels, budget allocation, campaign timelines,
product launches, and marketing audits.
"""

from __future__ import annotations

import logging
from typing import Any

from digital_mate.pillars.base import BasePillar
from digital_mate.memory.brand_profile import BrandProfile

logger = logging.getLogger(__name__)


class StrategyPillar(BasePillar):
    """Strategy & Planning pillar implementation.

    Creates comprehensive marketing strategies, plans, funnels,
    and campaign timelines tailored to the user's business.
    """

    PILLAR_NAME = "strategy"
    MAX_RESPONSE_TOKENS = 4096

    async def handle(
        self,
        user_message: str,
        action: str,
        context: list[dict[str, str]],
        brand_profile: BrandProfile | None = None,
        **kwargs: Any,
    ) -> str:
        """Handle a strategy-related user message.

        Args:
            user_message: The user's message text.
            action: Classified action (plan, funnel, budget, etc.).
            context: Recent conversation context.
            brand_profile: Optional brand profile for personalization.
            **kwargs: Additional arguments.

        Returns:
            Generated strategy response.
        """
        brand_context = self._build_brand_context(brand_profile)
        key_facts = kwargs.get("key_facts", "")
        enhanced_message = self._enhance_message(user_message, action)

        response = await self._generate_response(
            user_message=enhanced_message,
            context=context,
            brand_context=brand_context,
            key_facts=key_facts,
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
            "plan": "Create a detailed marketing plan with SMART goals, specific tactics, timeline, and success metrics.",
            "funnel": "Design a marketing funnel with stages: Awareness, Interest, Desire, Action. Include specific tactics for each stage.",
            "budget": "Provide budget allocation recommendations with percentage splits and expected ROI for each channel.",
            "timeline": "Create a campaign timeline with specific milestones, deadlines, and deliverables.",
            "launch": "Develop a product launch strategy covering pre-launch, launch day, and post-launch phases.",
            "audit": "Perform a marketing audit covering channels, content, engagement, and conversion metrics.",
        }
        hint = hints.get(action, "")
        if hint:
            return f"{hint}\n\nUser request: {user_message}"
        return user_message
