"""Tests for the workflow scheduler.

Covers weekly digest generation, campaign report generation,
error handling, and search integration.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from digital_mate.agent.scheduler import WorkflowScheduler, DIGEST_SYSTEM_PROMPT
from digital_mate.memory.brand_profile import BrandProfile


@pytest.fixture
def mock_llm() -> MagicMock:
    client = MagicMock()
    client.chat = AsyncMock(return_value=(
        "1. Instagram Reel — Behind the scenes of coffee roasting\n"
        "2. TikTok — Quick coffee brewing tips\n"
        "3. LinkedIn — Sustainability in F&B\n"
        "4. Instagram Story — Customer testimonial series\n"
        "5. Twitter Thread — Coffee industry trends 2024\n"
    ))
    return client


@pytest.fixture
def mock_search() -> MagicMock:
    service = MagicMock()
    service.search = AsyncMock(return_value=[
        {"title": "Coffee Trends 2024", "snippet": "Specialty coffee is growing"},
        {"title": "F&B Marketing", "snippet": "Social media is key"},
    ])
    return service


@pytest.fixture
def brand_profile() -> BrandProfile:
    return BrandProfile(
        chat_id=123,
        name="Test Coffee",
        industry="Food & Beverage",
        audience="Young professionals",
        tone="Warm and friendly",
        products="Specialty coffee beans",
        hashtags="#CoffeeLovers",
        competitors="Blue Bottle",
        platform_preference="instagram,tiktok",
        budget_range="medium",
        business_stage="growth",
    )


class TestWeeklyDigest:
    """Test the run_weekly_digest workflow."""

    async def test_digest_returns_formatted_text(
        self, mock_llm: MagicMock, brand_profile: BrandProfile
    ) -> None:
        scheduler = WorkflowScheduler(mock_llm)
        result = await scheduler.run_weekly_digest(brand_profile)
        assert "Weekly Content Digest" in result
        assert "Food & Beverage" in result
        mock_llm.chat.assert_called_once()

    async def test_digest_includes_brand_context(
        self, mock_llm: MagicMock, brand_profile: BrandProfile
    ) -> None:
        scheduler = WorkflowScheduler(mock_llm)
        await scheduler.run_weekly_digest(brand_profile)
        call_args = mock_llm.chat.call_args
        messages = call_args[0][0]
        user_msg = messages[1]["content"]
        assert "Food & Beverage" in user_msg
        assert "Specialty coffee beans" in user_msg

    async def test_digest_with_search_results(
        self, mock_llm: MagicMock, mock_search: MagicMock, brand_profile: BrandProfile
    ) -> None:
        scheduler = WorkflowScheduler(mock_llm, mock_search)
        result = await scheduler.run_weekly_digest(brand_profile)
        assert "Weekly Content Digest" in result
        mock_search.search.assert_called_once()
        # Verify trends are included in the LLM prompt
        call_args = mock_llm.chat.call_args
        messages = call_args[0][0]
        user_msg = messages[1]["content"]
        assert "Coffee Trends 2024" in user_msg

    async def test_digest_search_failure_graceful(
        self, mock_llm: MagicMock, brand_profile: BrandProfile
    ) -> None:
        mock_search = MagicMock()
        mock_search.search = AsyncMock(side_effect=Exception("Search down"))
        scheduler = WorkflowScheduler(mock_llm, mock_search)
        result = await scheduler.run_weekly_digest(brand_profile)
        # Should still work without search results
        assert "Weekly Content Digest" in result

    async def test_digest_llm_error(
        self, brand_profile: BrandProfile
    ) -> None:
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(side_effect=Exception("LLM error"))
        scheduler = WorkflowScheduler(mock_llm)
        result = await scheduler.run_weekly_digest(brand_profile)
        assert "Could not generate" in result

    async def test_digest_without_search_service(
        self, mock_llm: MagicMock, brand_profile: BrandProfile
    ) -> None:
        scheduler = WorkflowScheduler(mock_llm, search_service=None)
        result = await scheduler.run_weekly_digest(brand_profile)
        assert "Weekly Content Digest" in result
        mock_llm.chat.assert_called_once()


class TestCampaignReport:
    """Test the run_campaign_report workflow."""

    async def test_report_returns_formatted_text(
        self, mock_llm: MagicMock, brand_profile: BrandProfile
    ) -> None:
        scheduler = WorkflowScheduler(mock_llm)
        result = await scheduler.run_campaign_report(brand_profile)
        assert "Campaign Report" in result
        assert "Test Coffee" in result

    async def test_report_with_campaign_data(
        self, mock_llm: MagicMock, brand_profile: BrandProfile
    ) -> None:
        scheduler = WorkflowScheduler(mock_llm)
        result = await scheduler.run_campaign_report(
            brand_profile,
            campaign_data="Reach: 50k, Engagement: 3.5k, Conversions: 250",
        )
        call_args = mock_llm.chat.call_args
        messages = call_args[0][0]
        user_msg = messages[1]["content"]
        assert "50k" in user_msg

    async def test_report_without_campaign_data(
        self, mock_llm: MagicMock, brand_profile: BrandProfile
    ) -> None:
        scheduler = WorkflowScheduler(mock_llm)
        result = await scheduler.run_campaign_report(brand_profile)
        call_args = mock_llm.chat.call_args
        messages = call_args[0][0]
        user_msg = messages[1]["content"]
        assert "No specific campaign data" in user_msg

    async def test_report_llm_error(
        self, brand_profile: BrandProfile
    ) -> None:
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(side_effect=Exception("LLM error"))
        scheduler = WorkflowScheduler(mock_llm)
        result = await scheduler.run_campaign_report(brand_profile)
        assert "Could not generate" in result
