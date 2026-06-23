"""Tests for RoutingClassifier and updated Orchestrator routing logic.

Covers:
- LLM-based routing classification
- Fallback to keyword heuristic when LLM fails
- Orchestrator routing through classifier
- Keyword fallback preserved as backup
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from digital_mate.pillars.base import PillarResult
from digital_mate.agent.orchestrator import (
    Orchestrator,
    RoutingClassifier,
    ROUTE_CLASSIFIER_PROMPT,
    _is_complex_request,
)
from digital_mate.agent.workflow import WORKFLOWS


class TestRoutingClassifier:
    """Tests for the RoutingClassifier class."""

    @pytest.mark.asyncio
    async def test_classify_returns_workflow(self):
        """LLM returning 'workflow' strategy is passed through."""
        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(return_value={
            "strategy": "workflow",
            "workflow_name": "research_to_content",
            "reasoning": "user asked to research and create content",
        })
        classifier = RoutingClassifier(mock_llm)

        result = await classifier.classify(
            "Research trends then write a caption",
            pillar="research", action="trends", confidence=0.9,
        )

        assert result["strategy"] == "workflow"
        assert result["workflow_name"] == "research_to_content"
        mock_llm.chat_json.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_classify_returns_plan(self):
        """LLM returning 'plan' strategy is passed through."""
        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(return_value={
            "strategy": "plan",
            "workflow_name": None,
            "reasoning": "complex multi-step goal",
        })
        classifier = RoutingClassifier(mock_llm)

        result = await classifier.classify(
            "Help me launch a full marketing campaign for my new product",
            pillar="strategy", action="plan", confidence=0.6,
        )

        assert result["strategy"] == "plan"
        assert result["workflow_name"] is None

    @pytest.mark.asyncio
    async def test_classify_returns_single(self):
        """LLM returning 'single' strategy is passed through."""
        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(return_value={
            "strategy": "single",
            "workflow_name": None,
            "reasoning": "straightforward request",
        })
        classifier = RoutingClassifier(mock_llm)

        result = await classifier.classify(
            "Write me an Instagram caption about coffee",
            pillar="content", action="caption", confidence=0.9,
        )

        assert result["strategy"] == "single"

    @pytest.mark.asyncio
    async def test_classify_normalizes_invalid_strategy(self):
        """Invalid strategy values default to 'single'."""
        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(return_value={
            "strategy": "INVALID",
            "workflow_name": None,
            "reasoning": "bad value",
        })
        classifier = RoutingClassifier(mock_llm)

        result = await classifier.classify("test", "content", "caption", 0.8)
        assert result["strategy"] == "single"

    @pytest.mark.asyncio
    async def test_classify_rejects_unknown_workflow_name(self):
        """Unknown workflow names are normalized to None."""
        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(return_value={
            "strategy": "workflow",
            "workflow_name": "nonexistent_workflow",
            "reasoning": "bad name",
        })
        classifier = RoutingClassifier(mock_llm)

        result = await classifier.classify("test", "research", "trends", 0.8)
        assert result["strategy"] == "workflow"
        assert result["workflow_name"] is None

    @pytest.mark.asyncio
    async def test_classify_llm_error_returns_single(self):
        """LLM failure returns default single-response."""
        from digital_mate.llm.client import LLMError
        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(side_effect=LLMError("API down"))
        classifier = RoutingClassifier(mock_llm)

        result = await classifier.classify("test", "content", "caption", 0.8)
        assert result["strategy"] == "single"
        assert result["workflow_name"] is None
        assert "classifier_error" in result["reasoning"]

    @pytest.mark.asyncio
    async def test_classify_uses_router_model_and_low_tokens(self):
        """Classifier should use max_tokens=100 (cheap)."""
        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(return_value={
            "strategy": "single", "workflow_name": None, "reasoning": "ok",
        })
        classifier = RoutingClassifier(mock_llm)

        await classifier.classify("test", "content", "caption", 0.8)

        call_kwargs = mock_llm.chat_json.call_args
        assert call_kwargs.kwargs.get("max_tokens") == 100 or call_kwargs[1].get("max_tokens") == 100


class TestOrchestratorLLMRouting:
    """Test that Orchestrator uses RoutingClassifier as primary routing."""

    def setup_method(self):
        self.mock_research = AsyncMock()
        self.mock_research.handle_structured = AsyncMock(
            return_value=PillarResult(text="trend data", metadata={}, sources=[])
        )
        self.mock_content = AsyncMock()
        self.mock_content.handle_structured = AsyncMock(
            return_value=PillarResult(text="caption text")
        )
        self.pillars = {
            "research": self.mock_research,
            "content": self.mock_content,
        }

    @pytest.mark.asyncio
    async def test_llm_workflow_routing(self):
        """LLM classifier routing 'workflow' triggers the workflow engine."""
        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(return_value={
            "strategy": "workflow",
            "workflow_name": "research_to_content",
            "reasoning": "user asked for research-based content",
        })
        orch = Orchestrator(self.pillars, llm_client=mock_llm)

        text, was_handled = await orch.execute(
            user_message="Research trends then write a caption",
            pillar="research", action="trends", context=[],
        )

        assert was_handled is True
        assert "trend data" in text or "caption text" in text

    @pytest.mark.asyncio
    async def test_llm_single_routing_returns_empty(self):
        """LLM classifier routing 'single' returns (\"\", False)."""
        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(return_value={
            "strategy": "single",
            "workflow_name": None,
            "reasoning": "simple request",
        })
        orch = Orchestrator(self.pillars, llm_client=mock_llm)

        text, was_handled = await orch.execute(
            user_message="Write a caption for Instagram",
            pillar="content", action="caption", context=[],
        )

        assert was_handled is False
        assert text == ""

    @pytest.mark.asyncio
    async def test_llm_fails_falls_back_to_keyword_workflow(self):
        """When LLM classifier fails, keyword fallback still detects workflow."""
        from digital_mate.llm.client import LLMError
        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(side_effect=LLMError("down"))
        orch = Orchestrator(self.pillars, llm_client=mock_llm)

        # This message matches keyword "based on trends" → research_to_content
        text, was_handled = await orch.execute(
            user_message="Buatkan caption based on trends skincare",
            pillar="research", action="trends", context=[],
        )

        assert was_handled is True

    @pytest.mark.asyncio
    async def test_no_llm_client_uses_heuristic_fallback(self):
        """Without llm_client, Orchestrator uses keyword heuristic."""
        orch = Orchestrator(self.pillars, llm_client=None)

        text, was_handled = await orch.execute(
            user_message="Buatkan caption based on trends skincare",
            pillar="research", action="trends", context=[],
        )

        assert was_handled is True

    @pytest.mark.asyncio
    async def test_no_llm_client_simple_message_returns_empty(self):
        """Without llm_client, simple message returns (\"\", False)."""
        orch = Orchestrator(self.pillars, llm_client=None)

        text, was_handled = await orch.execute(
            user_message="Write a simple caption",
            pillar="content", action="caption", context=[],
        )

        assert was_handled is False

    @pytest.mark.asyncio
    async def test_llm_plan_routing_with_planner(self):
        """LLM classifier routing 'plan' triggers plan creation."""
        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(return_value={
            "strategy": "plan",
            "workflow_name": None,
            "reasoning": "complex marketing goal",
        })

        mock_planner = AsyncMock()
        mock_planner.create_plan = AsyncMock(return_value=[
            {"pillar": "research", "action": "trends", "description": "Research"},
        ])

        mock_plan_store = AsyncMock()
        mock_plan_store.get_active_plan = AsyncMock(return_value=None)
        mock_plan_store.create_plan = AsyncMock(return_value="plan-123")

        mock_executor = AsyncMock()
        mock_executor.execute = AsyncMock(return_value="Plan result here")

        orch = Orchestrator(
            self.pillars, planner=mock_planner,
            plan_store=mock_plan_store, llm_client=mock_llm,
        )
        orch._executor = mock_executor

        text, was_handled = await orch.execute(
            user_message="Launch a full marketing campaign",
            pillar="strategy", action="plan", context=[],
            chat_id=123,
        )

        assert was_handled is True


class TestOrchestratorBackwardCompatibility:
    """Ensure keyword-based routing still works as fallback."""

    def setup_method(self):
        self.mock_research = AsyncMock()
        self.mock_research.handle_structured = AsyncMock(
            return_value=PillarResult(text="trend data")
        )
        self.mock_content = AsyncMock()
        self.mock_content.handle_structured = AsyncMock(
            return_value=PillarResult(text="caption text")
        )
        self.pillars = {
            "research": self.mock_research,
            "content": self.mock_content,
        }

    @pytest.mark.asyncio
    async def test_keyword_fallback_detects_workflow(self):
        """Keyword-based fallback still works for workflow detection."""
        orch = Orchestrator(self.pillars, llm_client=None)

        # Explicit keyword trigger
        text, was_handled = await orch.execute(
            user_message="Buat caption based on trends skincare",
            pillar="research", action="trends", context=[],
        )
        assert was_handled is True

    @pytest.mark.asyncio
    async def test_keyword_heuristic_analytics_to_strategy(self):
        """Heuristic analytics→strategy workflow still works."""
        mock_analytics = AsyncMock()
        mock_analytics.handle_structured = AsyncMock(
            return_value=PillarResult(text="Report: CTR 2.5%")
        )
        mock_strategy = AsyncMock()
        mock_strategy.handle_structured = AsyncMock(
            return_value=PillarResult(text="Strategy: improve CTR")
        )
        orch = Orchestrator({"analytics": mock_analytics, "strategy": mock_strategy}, llm_client=None)

        text, was_workflow = await orch.execute(
            user_message="Analisis data campaign dan berikan rekomendasi strategi",
            pillar="analytics", action="improve", context=[],
        )
        assert was_workflow is True
