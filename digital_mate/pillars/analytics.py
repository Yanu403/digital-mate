"""Analytics & Reporting pillar.

Handles performance reports, KPI definition, metric interpretation,
ROI calculations, and data-driven improvement suggestions.
"""

from __future__ import annotations

import logging
from typing import Any

from digital_mate.pillars.base import BasePillar
from digital_mate.memory.brand_profile import BrandProfile
from digital_mate.integrations.notion_client import NotionService

logger = logging.getLogger(__name__)


class AnalyticsPillar(BasePillar):
    """Analytics & Reporting pillar implementation.

    Generates performance reports, defines KPIs, interprets metrics,
    calculates ROI, and suggests data-driven improvements.
    """

    PILLAR_NAME = "analytics"
    MAX_RESPONSE_TOKENS = 3072

    def __init__(
        self,
        llm_client: Any,
        notion_service: NotionService | None = None,
        language: str = "bilingual",
        bot_name: str = "Digital Mate",
    ) -> None:
        """Initialize the Analytics pillar.

        Args:
            llm_client: LLM client for generating responses.
            notion_service: Optional Notion service for campaign data.
            language: Language setting.
            bot_name: Bot display name.
        """
        super().__init__(llm_client, language, bot_name)
        self.notion_service = notion_service

    async def handle(
        self,
        user_message: str,
        action: str,
        context: list[dict[str, str]],
        brand_profile: BrandProfile | None = None,
        **kwargs: Any,
    ) -> str:
        """Handle an analytics-related user message.

        May fetch campaign data from Notion if available for
        report generation and metric interpretation.

        Args:
            user_message: The user's message text.
            action: Classified action (report, kpis, interpret, etc.).
            context: Recent conversation context.
            brand_profile: Optional brand profile for personalization.
            **kwargs: Additional arguments.

        Returns:
            Generated analytics response.
        """
        brand_context = self._build_brand_context(brand_profile)
        campaign_context = ""

        # Fetch campaign data from Notion if available
        if self.notion_service and self.notion_service.is_configured and action in ("report", "interpret", "improve"):
            try:
                campaigns = await self.notion_service.get_campaigns()
                if campaigns:
                    from digital_mate.utils.formatting import format_campaign_table
                    campaign_context = format_campaign_table(campaigns)
            except Exception as exc:
                logger.warning("Failed to fetch campaign data: %s", exc)

        enhanced_message = self._enhance_message(user_message, action)
        if campaign_context:
            enhanced_message = f"{campaign_context}\n\n{enhanced_message}"

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
            "report": "Generate a performance report with key metrics, comparisons to benchmarks, and actionable recommendations.",
            "kpis": "Define relevant KPIs with clear descriptions, measurement methods, target ranges, and why each matters.",
            "interpret": "Interpret the given metrics/data, explain what they mean, compare to benchmarks, and suggest actions.",
            "roi": "Calculate ROI step by step, showing the formula, inputs, calculation, and interpretation of results.",
            "improve": "Analyze the data and provide specific, prioritized improvement recommendations with expected impact.",
        }
        hint = hints.get(action, "")
        if hint:
            return f"{hint}\n\nUser request: {user_message}"
        return user_message
