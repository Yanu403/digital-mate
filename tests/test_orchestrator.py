"""Tests for the Orchestrator."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from digital_mate.pillars.base import PillarResult
from digital_mate.agent.orchestrator import Orchestrator
from digital_mate.agent.workflow import WORKFLOWS


class TestOrchestrator:
    """Tests for Orchestrator.execute."""

    def setup_method(self):
        self.mock_research = AsyncMock()
        self.mock_research.handle_structured = AsyncMock(
            return_value=PillarResult(
                text="trend: AI marketing",
                metadata={"search_query": "AI marketing trends"},
                sources=["http://ai.com"],
            )
        )

        self.mock_content = AsyncMock()
        self.mock_content.handle_structured = AsyncMock(
            return_value=PillarResult(text="✨ AI-powered caption!")
        )

        self.mock_strategy = AsyncMock()
        self.mock_strategy.handle = AsyncMock(return_value="Strategy plan here")

        self.pillars = {
            "research": self.mock_research,
            "content": self.mock_content,
            "strategy": self.mock_strategy,
        }
        self.orchestrator = Orchestrator(self.pillars)

    @pytest.mark.asyncio
    async def test_routes_to_workflow_when_detected(self):
        """Message with workflow trigger should execute the workflow."""
        text, was_workflow = await self.orchestrator.execute(
            user_message="Buatkan caption based on trends skincare",
            pillar="research",
            action="trends",
            context=[],
        )
        assert was_workflow is True
        assert "trend: AI marketing" in text
        assert "AI-powered caption" in text

    @pytest.mark.asyncio
    async def test_falls_through_for_simple_message(self):
        """Simple message without workflow trigger should return (empty, False)."""
        text, was_workflow = await self.orchestrator.execute(
            user_message="Buatkan caption IG tentang skincare",
            pillar="content",
            action="caption",
            context=[],
        )
        assert was_workflow is False
        assert text == ""

    @pytest.mark.asyncio
    async def test_falls_through_for_general(self):
        text, was_workflow = await self.orchestrator.execute(
            user_message="Halo, apa kabar?",
            pillar="general",
            action="chitchat",
            context=[],
        )
        assert was_workflow is False

    @pytest.mark.asyncio
    async def test_progress_callback_called(self):
        progress_calls = []

        async def on_progress(msg: str):
            progress_calls.append(msg)

        await self.orchestrator.execute(
            user_message="Buat caption based on trends skincare",
            pillar="research",
            action="trends",
            context=[],
            on_progress=on_progress,
        )
        assert len(progress_calls) >= 1

    @pytest.mark.asyncio
    async def test_workflow_step_failures_returned_in_text(self):
        """If workflow steps fail, errors appear in text but was_workflow is still True."""
        self.mock_research.handle_structured = AsyncMock(side_effect=RuntimeError("API down"))
        self.mock_content.handle_structured = AsyncMock(side_effect=RuntimeError("Also down"))

        text, was_workflow = await self.orchestrator.execute(
            user_message="Buat caption based on trends skincare",
            pillar="research",
            action="trends",
            context=[],
        )
        # Workflow was detected and attempted — errors captured in text
        assert was_workflow is True
        assert "error" in text.lower() or "Error" in text

    @pytest.mark.asyncio
    async def test_passes_brand_profile_and_key_facts(self):
        mock_profile = MagicMock()
        await self.orchestrator.execute(
            user_message="Buat caption based on trends",
            pillar="research",
            action="trends",
            context=[],
            brand_profile=mock_profile,
            key_facts="user likes organic products",
        )
        call_kwargs = self.mock_research.handle_structured.call_args
        assert call_kwargs.kwargs.get("brand_profile") is mock_profile or call_kwargs[1].get("brand_profile") is mock_profile

    @pytest.mark.asyncio
    async def test_heuristic_analytics_to_strategy(self):
        """Analytics report + strategy hint → analytics_to_strategy workflow."""
        mock_analytics = AsyncMock()
        mock_analytics.handle_structured = AsyncMock(
            return_value=PillarResult(text="Report: CTR 2.5%")
        )
        mock_strategy = AsyncMock()
        mock_strategy.handle_structured = AsyncMock(
            return_value=PillarResult(text="Strategy: improve CTR")
        )
        orch = Orchestrator({
            "analytics": mock_analytics,
            "strategy": mock_strategy,
        })

        text, was_workflow = await orch.execute(
            user_message="Analisis data campaign dan berikan rekomendasi strategi",
            pillar="analytics",
            action="improve",
            context=[],
        )
        assert was_workflow is True
        assert "CTR 2.5%" in text
        assert "improve CTR" in text
