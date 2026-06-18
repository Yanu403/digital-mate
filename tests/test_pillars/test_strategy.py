"""Tests for digital_mate.pillars.strategy module."""

import pytest
from unittest.mock import AsyncMock
from digital_mate.pillars.strategy import StrategyPillar
from digital_mate.memory.brand_profile import BrandProfile


class TestStrategyPillar:
    """Test Strategy & Planning pillar."""

    @pytest.mark.asyncio
    async def test_handle_plan(self, mock_llm_client) -> None:
        """Test marketing plan generation."""
        mock_llm_client.chat = AsyncMock(return_value="Here's your marketing plan:\n1. Phase 1...")
        pillar = StrategyPillar(mock_llm_client)

        response = await pillar.handle(
            user_message="Create a marketing plan for my startup",
            action="plan",
            context=[],
        )

        assert "plan" in response.lower()
        call_args = mock_llm_client.chat.call_args
        messages = call_args[0][0]
        user_msg = [m for m in messages if m["role"] == "user"][-1]["content"]
        assert "SMART" in user_msg or "plan" in user_msg.lower()

    @pytest.mark.asyncio
    async def test_handle_funnel(self, mock_llm_client) -> None:
        """Test funnel design request."""
        mock_llm_client.chat = AsyncMock(return_value="Funnel: Awareness → Interest → Desire → Action")
        pillar = StrategyPillar(mock_llm_client)

        response = await pillar.handle(
            user_message="Design a marketing funnel",
            action="funnel",
            context=[],
        )

        call_args = mock_llm_client.chat.call_args
        messages = call_args[0][0]
        user_msg = [m for m in messages if m["role"] == "user"][-1]["content"]
        assert "funnel" in user_msg.lower()

    @pytest.mark.asyncio
    async def test_handle_budget(self, mock_llm_client) -> None:
        """Test budget allocation advice."""
        mock_llm_client.chat = AsyncMock(return_value="Budget: 40% social, 30% search, 30% content")
        pillar = StrategyPillar(mock_llm_client)

        response = await pillar.handle(
            user_message="How should I allocate $10k budget?",
            action="budget",
            context=[],
        )

        call_args = mock_llm_client.chat.call_args
        messages = call_args[0][0]
        user_msg = [m for m in messages if m["role"] == "user"][-1]["content"]
        assert "budget" in user_msg.lower()

    @pytest.mark.asyncio
    async def test_handle_with_brand(self, mock_llm_client, sample_brand_profile) -> None:
        """Test strategy with brand context."""
        mock_llm_client.chat = AsyncMock(return_value="Strategy for TestBrand Coffee...")
        pillar = StrategyPillar(mock_llm_client)

        response = await pillar.handle(
            user_message="Create a launch strategy",
            action="launch",
            context=[],
            brand_profile=sample_brand_profile,
        )

        call_args = mock_llm_client.chat.call_args
        messages = call_args[0][0]
        system_msg = [m for m in messages if m["role"] == "system"][0]["content"]
        assert "TestBrand Coffee" in system_msg

    @pytest.mark.asyncio
    async def test_enhance_all_actions(self, mock_llm_client) -> None:
        """Test all strategy actions have enhancements."""
        pillar = StrategyPillar(mock_llm_client)
        actions = ["plan", "funnel", "budget", "timeline", "launch", "audit"]

        for action in actions:
            enhanced = pillar._enhance_message("test", action)
            assert enhanced != "test"
