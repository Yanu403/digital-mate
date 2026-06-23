"""Scheduled autonomous workflows for proactive intelligence.

Generates weekly content digests and campaign performance reports
on behalf of users, combining search, LLM generation, and brand
profile context.
"""

from __future__ import annotations

import logging
from typing import Any

from digital_mate.llm.client import LLMClient, LLMError
from digital_mate.integrations.search import SearchService
from digital_mate.memory.brand_profile import BrandProfile

logger = logging.getLogger(__name__)

DIGEST_SYSTEM_PROMPT = """You are a digital marketing strategist creating a weekly content digest.
Given the user's brand profile and current industry trends, generate 5 actionable content ideas.

For each idea provide:
- Platform (Instagram/TikTok/LinkedIn/Twitter/etc.)
- Content type (Reel/Story/Post/Thread/etc.)
- Topic and angle
- Sample hook or headline
- Key hashtags

Format as a clean, numbered list. Be specific and actionable."""


class WorkflowScheduler:
    """Runs scheduled autonomous workflows for users.

    Generates proactive content like weekly digests and campaign
    reports that are sent to users via the bot.

    Args:
        llm_client: LLM client for content generation.
        search_service: Search service for trend research.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        search_service: SearchService | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.search_service = search_service

    async def run_weekly_digest(
        self,
        brand_profile: BrandProfile,
    ) -> str:
        """Generate weekly content digest for a user.

        Searches for trends in the user's industry, then generates
        5 content ideas based on those trends and the brand profile.

        Args:
            brand_profile: User's brand profile for personalization.

        Returns:
            Formatted weekly digest text.
        """
        # Search for industry trends
        trend_context = ""
        if self.search_service and brand_profile.industry:
            try:
                results = await self.search_service.search(
                    f"{brand_profile.industry} marketing trends this week"
                )
                if results:
                    trend_context = "## Current Industry Trends\n"
                    for r in results[:3]:
                        trend_context += f"- {r.get('title', '')}: {r.get('snippet', '')}\n"
            except Exception as exc:
                logger.warning("Trend search failed for digest: %s", exc)

        # Build brand context
        brand_ctx = (
            f"## Brand Profile\n"
            f"- Industry: {brand_profile.industry}\n"
            f"- Audience: {brand_profile.audience}\n"
            f"- Tone: {brand_profile.tone}\n"
            f"- Products: {brand_profile.products}\n"
            f"- Platforms: {brand_profile.platform_preference}\n"
        )

        user_content = f"{brand_ctx}\n\n{trend_context}" if trend_context else brand_ctx

        messages = [
            {"role": "system", "content": DIGEST_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        try:
            response = await self.llm_client.chat(messages, temperature=0.7, max_tokens=2048)
            return (
                f"🌅 *Weekly Content Digest*\n"
                f"Industry: {brand_profile.industry}\n\n"
                f"{response.strip()}"
            )
        except (LLMError, Exception) as exc:
            logger.error("Weekly digest generation failed: %s", exc)
            return "⚠️ Could not generate weekly digest. Please try again later."

    async def run_campaign_report(
        self,
        brand_profile: BrandProfile,
        campaign_data: str = "",
    ) -> str:
        """Generate campaign performance report.

        Analyzes campaign data and provides actionable recommendations.

        Args:
            brand_profile: User's brand profile.
            campaign_data: Optional campaign data (e.g. from Notion).

        Returns:
            Formatted campaign report text.
        """
        system_prompt = (
            "You are a marketing analytics expert. Generate a concise campaign "
            "performance report with key insights and actionable recommendations. "
            "Focus on metrics that matter: reach, engagement, conversions, and ROI."
        )

        brand_ctx = (
            f"Brand: {brand_profile.name}\n"
            f"Industry: {brand_profile.industry}\n"
            f"Products: {brand_profile.products}\n"
        )

        user_content = brand_ctx
        if campaign_data:
            user_content += f"\n\n## Campaign Data\n{campaign_data}"
        else:
            user_content += (
                "\n\nNo specific campaign data provided. "
                "Generate a general campaign health checklist and "
                "recommended KPIs to track."
            )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        try:
            response = await self.llm_client.chat(messages, temperature=0.7, max_tokens=2048)
            return (
                f"📊 *Campaign Report*\n"
                f"Brand: {brand_profile.name}\n\n"
                f"{response.strip()}"
            )
        except (LLMError, Exception) as exc:
            logger.error("Campaign report generation failed: %s", exc)
            return "⚠️ Could not generate campaign report. Please try again later."
