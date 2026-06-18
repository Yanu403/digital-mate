"""Tests for digital_mate.pillars.analytics module."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from digital_mate.pillars.analytics import AnalyticsPillar
from digital_mate.integrations.notion_client import NotionService


class TestAnalyticsPillar:
    """Test Analytics & Reporting pillar."""

    @pytest.mark.asyncio
    async def test_handle_report(self, mock_llm_client) -> None:
        """Test report generation."""
        mock_llm_client.chat = AsyncMock(return_value="Performance Report: Engagement up 15%...")
        pillar = AnalyticsPillar(mock_llm_client)

        response = await pillar.handle(
            user_message="Generate a performance report",
            action="report",
            context=[],
        )

        assert "report" in response.lower() or "performance" in response.lower()

    @pytest.mark.asyncio
    async def test_handle_kpis(self, mock_llm_client) -> None:
        """Test KPI definition."""
        mock_llm_client.chat = AsyncMock(return_value="Key KPIs: CTR, CPC, ROAS, Conversion Rate")
        pillar = AnalyticsPillar(mock_llm_client)

        response = await pillar.handle(
            user_message="What KPIs should I track?",
            action="kpis",
            context=[],
        )

        call_args = mock_llm_client.chat.call_args
        messages = call_args[0][0]
        user_msg = [m for m in messages if m["role"] == "user"][-1]["content"]
        assert "KPI" in user_msg

    @pytest.mark.asyncio
    async def test_handle_roi(self, mock_llm_client) -> None:
        """Test ROI calculation."""
        mock_llm_client.chat = AsyncMock(return_value="ROI = (Revenue - Cost) / Cost * 100 = 150%")
        pillar = AnalyticsPillar(mock_llm_client)

        response = await pillar.handle(
            user_message="How do I calculate marketing ROI?",
            action="roi",
            context=[],
        )

        call_args = mock_llm_client.chat.call_args
        messages = call_args[0][0]
        user_msg = [m for m in messages if m["role"] == "user"][-1]["content"]
        assert "ROI" in user_msg

    @pytest.mark.asyncio
    async def test_handle_with_notion_campaigns(self, mock_llm_client, mock_notion_client) -> None:
        """Test report generation with Notion campaign data."""
        mock_llm_client.chat = AsyncMock(return_value="Based on your campaigns: Q1 Launch is performing well...")
        pillar = AnalyticsPillar(mock_llm_client, notion_service=mock_notion_client)

        response = await pillar.handle(
            user_message="How are my campaigns doing?",
            action="report",
            context=[],
        )

        # Notion should have been queried
        mock_notion_client.get_campaigns.assert_called_once()
        assert response

    @pytest.mark.asyncio
    async def test_handle_without_notion(self, mock_llm_client) -> None:
        """Test analytics without Notion configured."""
        mock_llm_client.chat = AsyncMock(return_value="General analytics advice...")
        pillar = AnalyticsPillar(mock_llm_client, notion_service=None)

        response = await pillar.handle(
            user_message="How's my performance?",
            action="report",
            context=[],
        )

        assert response

    @pytest.mark.asyncio
    async def test_enhance_all_actions(self, mock_llm_client) -> None:
        """Test all analytics actions have enhancements."""
        pillar = AnalyticsPillar(mock_llm_client)
        actions = ["report", "kpis", "interpret", "roi", "improve"]

        for action in actions:
            enhanced = pillar._enhance_message("test", action)
            assert enhanced != "test"

    @pytest.mark.asyncio
    async def test_notion_fetch_failure_graceful(self, mock_llm_client) -> None:
        """Test graceful handling when Notion fetch fails."""
        mock_llm_client.chat = AsyncMock(return_value="Analytics response without campaign data")

        notion = MagicMock(spec=NotionService)
        notion.is_configured = True
        notion.get_campaigns = AsyncMock(side_effect=Exception("Notion API error"))

        pillar = AnalyticsPillar(mock_llm_client, notion_service=notion)

        response = await pillar.handle(
            user_message="Generate report",
            action="report",
            context=[],
        )

        # Should still get a response
        assert response
