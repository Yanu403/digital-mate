"""Tests for digital_mate.pillars.research module."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from digital_mate.pillars.research import ResearchPillar
from digital_mate.integrations.search import SearchService


class TestResearchPillar:
    """Test Research & Insight pillar."""

    @pytest.mark.asyncio
    async def test_handle_trends_without_search(self, mock_llm_client) -> None:
        """Test trend research without search service."""
        mock_llm_client.chat = AsyncMock(return_value="Current trends: AI, short video, personalization")
        pillar = ResearchPillar(mock_llm_client, search_service=None)

        response = await pillar.handle(
            user_message="What are the latest marketing trends?",
            action="trends",
            context=[],
        )

        assert "trend" in response.lower()

    @pytest.mark.asyncio
    async def test_handle_with_search_service(self, mock_llm_client) -> None:
        """Test research with search service providing results."""
        mock_llm_client.chat = AsyncMock(return_value="Based on research: AI is trending...")

        search_service = MagicMock(spec=SearchService)
        search_service.search = AsyncMock(return_value=[
            {"title": "2024 Trends", "url": "https://trends.com", "snippet": "AI is the top trend"},
        ])

        pillar = ResearchPillar(mock_llm_client, search_service=search_service)

        response = await pillar.handle(
            user_message="What's trending in digital marketing?",
            action="trends",
            context=[],
        )

        # Search should have been called
        search_service.search.assert_called_once()
        assert response

    @pytest.mark.asyncio
    async def test_handle_competitors(self, mock_llm_client) -> None:
        """Test competitor analysis."""
        mock_llm_client.chat = AsyncMock(return_value="Competitor analysis framework...")
        pillar = ResearchPillar(mock_llm_client)

        response = await pillar.handle(
            user_message="Analyze my competitors",
            action="competitors",
            context=[],
        )

        call_args = mock_llm_client.chat.call_args
        messages = call_args[0][0]
        user_msg = [m for m in messages if m["role"] == "user"][-1]["content"]
        assert "competitor" in user_msg.lower()

    @pytest.mark.asyncio
    async def test_build_search_query_with_brand(self, mock_llm_client, sample_brand_profile) -> None:
        """Test search query building with brand context."""
        pillar = ResearchPillar(mock_llm_client)

        query = pillar._build_search_query("latest trends", "trends", sample_brand_profile)
        assert "Food & Beverage" in query or "food" in query.lower()

    @pytest.mark.asyncio
    async def test_build_search_query_without_brand(self, mock_llm_client) -> None:
        """Test search query building without brand context."""
        pillar = ResearchPillar(mock_llm_client)

        query = pillar._build_search_query("latest trends", "trends", None)
        assert "marketing" in query.lower() or "trend" in query.lower()

    @pytest.mark.asyncio
    async def test_search_failure_graceful(self, mock_llm_client) -> None:
        """Test graceful handling when search fails."""
        mock_llm_client.chat = AsyncMock(return_value="Based on my knowledge...")

        search_service = MagicMock(spec=SearchService)
        search_service.search = AsyncMock(side_effect=Exception("Search API down"))

        pillar = ResearchPillar(mock_llm_client, search_service=search_service)

        response = await pillar.handle(
            user_message="What are the trends?",
            action="trends",
            context=[],
        )

        # Should still get a response despite search failure
        assert response

    @pytest.mark.asyncio
    async def test_no_search_for_general_action(self, mock_llm_client) -> None:
        """Test that 'other' action doesn't trigger search."""
        mock_llm_client.chat = AsyncMock(return_value="General research answer")

        search_service = MagicMock(spec=SearchService)
        search_service.search = AsyncMock(return_value=[])

        pillar = ResearchPillar(mock_llm_client, search_service=search_service)

        response = await pillar.handle(
            user_message="General research question",
            action="other",
            context=[],
        )

        # Search should NOT be called for 'other' action
        search_service.search.assert_not_called()
