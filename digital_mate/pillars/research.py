"""Research & Insight pillar.

Handles market trends, competitor analysis, audience research,
keyword research, and industry benchmarks. Integrates with
web search for real-time data.
"""

from __future__ import annotations

import logging
from typing import Any

from digital_mate.pillars.base import BasePillar
from digital_mate.memory.brand_profile import BrandProfile
from digital_mate.integrations.search import SearchService, format_search_context

logger = logging.getLogger(__name__)


class ResearchPillar(BasePillar):
    """Research & Insight pillar implementation.

    Provides market research, trend analysis, and competitor insights
    using web search when available for real-time data.
    """

    PILLAR_NAME = "research"
    MAX_RESPONSE_TOKENS = 3072

    def __init__(
        self,
        llm_client: Any,
        search_service: SearchService | None = None,
        language: str = "bilingual",
        bot_name: str = "Digital Mate",
    ) -> None:
        """Initialize the Research pillar.

        Args:
            llm_client: LLM client for generating responses.
            search_service: Optional web search service.
            language: Language setting.
            bot_name: Bot display name.
        """
        super().__init__(llm_client, language, bot_name)
        self.search_service = search_service

    async def handle(
        self,
        user_message: str,
        action: str,
        context: list[dict[str, str]],
        brand_profile: BrandProfile | None = None,
        **kwargs: Any,
    ) -> str:
        """Handle a research-related user message.

        Performs web search if the action requires real-time data,
        then generates an informed response.

        Args:
            user_message: The user's message text.
            action: Classified action (trends, competitors, etc.).
            context: Recent conversation context.
            brand_profile: Optional brand profile for personalization.
            **kwargs: Additional arguments.

        Returns:
            Generated research response.
        """
        brand_context = self._build_brand_context(brand_profile)
        search_context = ""

        # Perform web search for research actions that benefit from real-time data
        if self.search_service and action in ("trends", "competitors", "audience", "keywords", "benchmarks"):
            try:
                search_query = self._build_search_query(user_message, action, brand_profile)
                search_results = await self.search_service.search(search_query, max_results=5)
                search_context = format_search_context(search_results)
                logger.debug("Search results for research: %d results", len(search_results))
            except Exception as exc:
                logger.warning("Search failed for research pillar: %s", exc)

        enhanced_message = self._enhance_message(user_message, action)

        response = await self._generate_response(
            user_message=enhanced_message,
            context=context,
            brand_context=brand_context,
            search_context=search_context,
        )

        return response

    def _build_search_query(
        self,
        user_message: str,
        action: str,
        brand_profile: BrandProfile | None,
    ) -> str:
        """Build an optimized search query from the user message.

        Args:
            user_message: User's original message.
            action: Classified action.
            brand_profile: Optional brand profile for context.

        Returns:
            Optimized search query string.
        """
        industry = ""
        if brand_profile:
            industry = brand_profile.industry

        prefixes = {
            "trends": f"latest {industry} marketing trends" if industry else "latest digital marketing trends",
            "competitors": f"{industry} competitor analysis" if industry else "digital marketing competitor analysis",
            "audience": f"{industry} target audience research" if industry else "target audience research",
            "keywords": f"{industry} SEO keywords" if industry else "SEO keyword research",
            "benchmarks": f"{industry} marketing benchmarks" if industry else "digital marketing benchmarks 2024",
        }

        prefix = prefixes.get(action, "digital marketing research")
        # Combine with user message for specificity
        return f"{prefix} {user_message}".strip()[:200]

    def _enhance_message(self, user_message: str, action: str) -> str:
        """Add action-specific context to the user message.

        Args:
            user_message: Original user message.
            action: Classified action.

        Returns:
            Enhanced message with action hints.
        """
        hints = {
            "trends": "Analyze current market trends with specific data points and actionable insights. Cite sources.",
            "competitors": "Provide a competitor analysis framework with specific areas to examine and benchmarking suggestions.",
            "audience": "Help define target audience segments with demographics, psychographics, and behavior patterns.",
            "keywords": "Suggest relevant keywords with estimated search volume and competition level where possible.",
            "benchmarks": "Provide industry benchmark data with specific metrics and comparison ranges.",
        }
        hint = hints.get(action, "")
        if hint:
            return f"{hint}\n\nUser request: {user_message}"
        return user_message
