"""Tests for workflow definitions and WorkflowEngine."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from digital_mate.pillars.base import PillarResult
from digital_mate.agent.workflow import (
    WorkflowStep,
    Workflow,
    WORKFLOWS,
    WorkflowEngine,
)


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


class TestPillarResult:
    """Tests for PillarResult dataclass."""

    def test_creation(self):
        r = PillarResult(text="hello", metadata={"k": "v"}, sources=["http://x.com"])
        assert r.text == "hello"
        assert r.metadata == {"k": "v"}
        assert r.sources == ["http://x.com"]

    def test_defaults(self):
        r = PillarResult(text="hi")
        assert r.metadata == {}
        assert r.sources == []

    def test_empty_text(self):
        r = PillarResult(text="")
        assert r.text == ""


class TestWorkflowStep:
    """Tests for WorkflowStep dataclass."""

    def test_defaults(self):
        step = WorkflowStep(pillar="research", action="trends")
        assert step.input_transform == "user_message"
        assert step.input_key == ""
        assert step.description == ""

    def test_custom_values(self):
        step = WorkflowStep(
            pillar="content",
            action="caption",
            input_transform="previous_text",
            description="✍️ Writing...",
        )
        assert step.pillar == "content"
        assert step.input_transform == "previous_text"
        assert step.description == "✍️ Writing..."


class TestWorkflow:
    """Tests for Workflow dataclass."""

    def test_creation(self):
        w = Workflow(
            name="test",
            trigger_keywords=["kw1"],
            steps=[WorkflowStep(pillar="research", action="trends")],
            description="Test workflow",
        )
        assert w.name == "test"
        assert len(w.steps) == 1


# ---------------------------------------------------------------------------
# Built-in workflows tests
# ---------------------------------------------------------------------------


class TestWorkflows:
    """Tests for the WORKFLOWS registry."""

    def test_all_4_workflows_exist(self):
        expected = {"research_to_content", "research_to_strategy", "analytics_to_strategy", "strategy_to_content"}
        assert set(WORKFLOWS.keys()) == expected

    def test_each_workflow_has_steps(self):
        for name, wf in WORKFLOWS.items():
            assert len(wf.steps) >= 2, f"Workflow '{name}' should have at least 2 steps"

    def test_each_workflow_has_keywords(self):
        for name, wf in WORKFLOWS.items():
            assert len(wf.trigger_keywords) > 0, f"Workflow '{name}' should have trigger keywords"

    def test_research_to_content_steps(self):
        wf = WORKFLOWS["research_to_content"]
        assert wf.steps[0].pillar == "research"
        assert wf.steps[0].action == "trends"
        assert wf.steps[1].pillar == "content"
        assert wf.steps[1].action == "caption"

    def test_research_to_strategy_steps(self):
        wf = WORKFLOWS["research_to_strategy"]
        assert wf.steps[0].pillar == "research"
        assert wf.steps[0].action == "competitors"
        assert wf.steps[1].pillar == "strategy"
        assert wf.steps[1].action == "plan"

    def test_analytics_to_strategy_steps(self):
        wf = WORKFLOWS["analytics_to_strategy"]
        assert wf.steps[0].pillar == "analytics"
        assert wf.steps[1].pillar == "strategy"

    def test_strategy_to_content_steps(self):
        wf = WORKFLOWS["strategy_to_content"]
        assert wf.steps[0].pillar == "strategy"
        assert wf.steps[0].action == "plan"
        assert wf.steps[1].pillar == "content"
        assert wf.steps[1].action == "calendar"


# ---------------------------------------------------------------------------
# WorkflowEngine.detect_workflow tests
# ---------------------------------------------------------------------------


class TestDetectWorkflow:
    """Tests for WorkflowEngine.detect_workflow."""

    def setup_method(self):
        self.engine = WorkflowEngine(pillars={})

    def test_detect_by_keyword_research_content(self):
        wf = self.engine.detect_workflow(
            "Buat caption based on trends skincare terbaru",
            pillar="research",
            action="trends",
        )
        assert wf is not None
        assert wf.name == "research_to_content"

    def test_detect_by_keyword_research_strategy(self):
        wf = self.engine.detect_workflow(
            "Lakukan competitor analysis untuk brand skincare",
            pillar="research",
            action="competitors",
        )
        assert wf is not None
        assert wf.name == "research_to_strategy"

    def test_detect_by_keyword_analytics_strategy(self):
        wf = self.engine.detect_workflow(
            "Help me improve performance of my campaign",
            pillar="analytics",
            action="report",
        )
        assert wf is not None
        assert wf.name == "analytics_to_strategy"

    def test_detect_by_keyword_strategy_content(self):
        wf = self.engine.detect_workflow(
            "Buatkan content dari strategy plan yang sudah ada",
            pillar="strategy",
            action="plan",
        )
        assert wf is not None
        assert wf.name == "strategy_to_content"

    def test_detect_heuristic_research_trends_with_content_hint(self):
        """Research+trends + content hint → research_to_content."""
        wf = self.engine.detect_workflow(
            "Tolong riset tren skincare lalu buatkan caption IG",
            pillar="research",
            action="trends",
        )
        assert wf is not None
        assert wf.name == "research_to_content"

    def test_detect_heuristic_research_competitors_with_strategy_hint(self):
        """Research+competitors + strategy hint → research_to_strategy."""
        wf = self.engine.detect_workflow(
            "Analisis kompetitor dan buatkan strategi",
            pillar="research",
            action="competitors",
        )
        assert wf is not None
        assert wf.name == "research_to_strategy"

    def test_detect_heuristic_analytics_with_strategy_hint(self):
        """Analytics + strategy hint → analytics_to_strategy."""
        wf = self.engine.detect_workflow(
            "Lihat data campaign ini dan berikan rekomendasi strategi",
            pillar="analytics",
            action="improve",
        )
        assert wf is not None
        assert wf.name == "analytics_to_strategy"

    def test_detect_heuristic_strategy_with_content_hint(self):
        """Strategy + content hint → strategy_to_content."""
        wf = self.engine.detect_workflow(
            "Buat marketing plan dan kalender konten",
            pillar="strategy",
            action="plan",
        )
        assert wf is not None
        assert wf.name == "strategy_to_content"

    def test_detect_returns_none_for_simple_content(self):
        """Simple content request should NOT trigger workflow."""
        wf = self.engine.detect_workflow(
            "Buatkan caption IG untuk skincare",
            pillar="content",
            action="caption",
        )
        assert wf is None

    def test_detect_returns_none_for_general(self):
        wf = self.engine.detect_workflow(
            "Halo, apa kabar?",
            pillar="general",
            action="chitchat",
        )
        assert wf is None

    def test_detect_returns_none_for_research_without_content_hint(self):
        """Research+trends without content hints should NOT trigger workflow."""
        wf = self.engine.detect_workflow(
            "Apa tren marketing terbaru?",
            pillar="research",
            action="trends",
        )
        assert wf is None

    def test_detect_returns_none_for_analytics_without_strategy_hint(self):
        """Analytics without strategy hints should NOT trigger workflow."""
        wf = self.engine.detect_workflow(
            "Buatkan laporan performa campaign",
            pillar="analytics",
            action="report",
        )
        assert wf is None


# ---------------------------------------------------------------------------
# WorkflowEngine._build_step_input tests
# ---------------------------------------------------------------------------


class TestBuildStepInput:
    """Tests for WorkflowEngine._build_step_input."""

    def setup_method(self):
        self.engine = WorkflowEngine(pillars={})

    def test_user_message_transform(self):
        step = WorkflowStep(pillar="content", action="caption", input_transform="user_message")
        result = self.engine._build_step_input(step, "buat caption", [])
        assert result == "buat caption"

    def test_previous_text_transform(self):
        step = WorkflowStep(pillar="content", action="caption", input_transform="previous_text")
        prev = [PillarResult(text="trend: skincare glowing", metadata={}, sources=[])]
        result = self.engine._build_step_input(step, "buat caption", prev)
        assert "skincare glowing" in result
        assert "Based on the following" in result

    def test_previous_metadata_transform(self):
        step = WorkflowStep(
            pillar="strategy", action="plan",
            input_transform="previous_metadata", input_key="search_query",
        )
        prev = [PillarResult(text="analysis text", metadata={"search_query": "skincare trends 2026"}, sources=[])]
        result = self.engine._build_step_input(step, "original msg", prev)
        assert result == "skincare trends 2026"

    def test_previous_metadata_fallback_to_text(self):
        """If key not found in metadata, falls back to previous text."""
        step = WorkflowStep(
            pillar="strategy", action="plan",
            input_transform="previous_metadata", input_key="nonexistent",
        )
        prev = [PillarResult(text="fallback text", metadata={}, sources=[])]
        result = self.engine._build_step_input(step, "original msg", prev)
        assert result == "fallback text"

    def test_previous_text_no_results_fallback(self):
        step = WorkflowStep(pillar="content", action="caption", input_transform="previous_text")
        result = self.engine._build_step_input(step, "original msg", [])
        assert result == "original msg"


# ---------------------------------------------------------------------------
# WorkflowEngine._combine_results tests
# ---------------------------------------------------------------------------


class TestCombineResults:
    """Tests for WorkflowEngine._combine_results."""

    def test_single_result(self):
        wf = Workflow(name="test", trigger_keywords=[], steps=[WorkflowStep(pillar="r", action="a")])
        r = PillarResult(text="hello")
        combined = WorkflowEngine._combine_results(wf, [r])
        assert combined.text == "hello"

    def test_multiple_results_with_headers(self):
        wf = Workflow(
            name="test", trigger_keywords=[], steps=[
                WorkflowStep(pillar="r", action="a", description="🔍 Searching..."),
                WorkflowStep(pillar="c", action="b", description="✍️ Writing..."),
            ]
        )
        r1 = PillarResult(text="research data")
        r2 = PillarResult(text="caption text")
        combined = WorkflowEngine._combine_results(wf, [r1, r2])
        assert "🔍 Searching..." in combined.text
        assert "research data" in combined.text
        assert "✍️ Writing..." in combined.text
        assert "caption text" in combined.text
        assert "---" in combined.text

    def test_empty_results(self):
        wf = Workflow(name="test", trigger_keywords=[], steps=[])
        combined = WorkflowEngine._combine_results(wf, [])
        assert "no results" in combined.text

    def test_metadata_merged(self):
        wf = Workflow(
            name="test", trigger_keywords=[], steps=[
                WorkflowStep(pillar="r", action="a"),
                WorkflowStep(pillar="c", action="b"),
            ]
        )
        r1 = PillarResult(text="a", metadata={"k1": "v1"})
        r2 = PillarResult(text="b", metadata={"k2": "v2"})
        combined = WorkflowEngine._combine_results(wf, [r1, r2])
        assert combined.metadata["k1"] == "v1"
        assert combined.metadata["k2"] == "v2"
        assert combined.metadata["workflow"] == "test"
        assert combined.metadata["step_count"] == 2

    def test_sources_merged(self):
        wf = Workflow(
            name="test", trigger_keywords=[], steps=[
                WorkflowStep(pillar="r", action="a"),
                WorkflowStep(pillar="c", action="b"),
            ]
        )
        r1 = PillarResult(text="a", sources=["http://a.com"])
        r2 = PillarResult(text="b", sources=["http://b.com"])
        combined = WorkflowEngine._combine_results(wf, [r1, r2])
        assert combined.sources == ["http://a.com", "http://b.com"]


# ---------------------------------------------------------------------------
# WorkflowEngine.execute tests
# ---------------------------------------------------------------------------


class TestEngineExecute:
    """Tests for WorkflowEngine.execute with mocked pillars."""

    def setup_method(self):
        self.mock_pillar_research = AsyncMock()
        self.mock_pillar_research.handle_structured = AsyncMock(
            return_value=PillarResult(
                text="trend: skincare glowing",
                metadata={"search_query": "skincare trends"},
                sources=["http://trend.com"],
            )
        )

        self.mock_pillar_content = AsyncMock()
        self.mock_pillar_content.handle_structured = AsyncMock(
            return_value=PillarResult(text="✨ Glowing skin caption!")
        )

        self.pillars = {
            "research": self.mock_pillar_research,
            "content": self.mock_pillar_content,
        }
        self.engine = WorkflowEngine(self.pillars)

    @pytest.mark.asyncio
    async def test_execute_chains_steps(self):
        wf = WORKFLOWS["research_to_content"]
        result = await self.engine.execute(
            workflow=wf,
            user_message="Buat caption based on trends skincare",
            context=[],
        )
        assert "trend: skincare glowing" in result.text
        assert "Glowing skin caption" in result.text
        self.mock_pillar_research.handle_structured.assert_called_once()
        self.mock_pillar_content.handle_structured.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_with_progress_callback(self):
        progress_calls = []
        async def on_progress(msg: str):
            progress_calls.append(msg)

        wf = WORKFLOWS["research_to_content"]
        await self.engine.execute(
            workflow=wf,
            user_message="test",
            context=[],
            on_progress=on_progress,
        )
        assert len(progress_calls) == 2
        assert "🔍" in progress_calls[0]
        assert "✍️" in progress_calls[1]

    @pytest.mark.asyncio
    async def test_execute_handles_missing_pillar(self):
        """If a pillar is not in the dict, the step is skipped."""
        engine = WorkflowEngine({"research": self.mock_pillar_research})  # no content pillar
        wf = WORKFLOWS["research_to_content"]
        result = await engine.execute(workflow=wf, user_message="test", context=[])
        # Research ran, content was skipped
        self.mock_pillar_research.handle_structured.assert_called_once()
        assert "trend: skincare glowing" in result.text

    @pytest.mark.asyncio
    async def test_execute_handles_step_failure(self):
        """If a step raises, workflow continues with remaining steps."""
        self.mock_pillar_research.handle_structured = AsyncMock(side_effect=RuntimeError("API down"))
        wf = WORKFLOWS["research_to_content"]
        result = await self.engine.execute(
            workflow=wf, user_message="test", context=[],
        )
        # Error message in result, but content step still ran
        assert "error" in result.text.lower() or "Error" in result.text
        self.mock_pillar_content.handle_structured.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_passes_brand_profile(self):
        mock_profile = MagicMock()
        wf = WORKFLOWS["research_to_content"]
        await self.engine.execute(
            workflow=wf, user_message="test", context=[],
            brand_profile=mock_profile, key_facts="user likes skincare",
        )
        # Check brand_profile passed to research pillar
        call_kwargs = self.mock_pillar_research.handle_structured.call_args
        assert call_kwargs.kwargs.get("brand_profile") is mock_profile or call_kwargs[1].get("brand_profile") is mock_profile
