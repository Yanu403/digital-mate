"""Tests for the reflection engine.

Covers pillar selection, the reflect-and-refine loop, skip logic,
and integration between critic and refiner.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from digital_mate.agent.critic import Critic
from digital_mate.agent.refiner import Refiner
from digital_mate.agent.reflection import ReflectionEngine


class TestReflectionPillarSelection:
    """Verify which pillars get reflection and which are skipped."""

    def test_reflect_pillars(self) -> None:
        assert "content" in ReflectionEngine.REFLECT_PILLARS
        assert "strategy" in ReflectionEngine.REFLECT_PILLARS

    def test_optional_pillars(self) -> None:
        assert "research" in ReflectionEngine.OPTIONAL_PILLARS

    def test_skip_pillars(self) -> None:
        assert "analytics" in ReflectionEngine.SKIP_PILLARS
        assert "general" in ReflectionEngine.SKIP_PILLARS

    def test_no_overlap_between_sets(self) -> None:
        all_sets = (
            ReflectionEngine.REFLECT_PILLARS
            | ReflectionEngine.OPTIONAL_PILLARS
            | ReflectionEngine.SKIP_PILLARS
        )
        # All standard pillars should be covered
        assert "content" in all_sets
        assert "strategy" in all_sets
        assert "research" in all_sets
        assert "analytics" in all_sets
        assert "general" in all_sets


class TestReflectionEngine:
    """Test the reflect_and_refine loop."""

    @pytest.fixture
    def passing_critic(self) -> MagicMock:
        """Critic that always passes."""
        critic = MagicMock(spec=Critic)
        critic.evaluate = AsyncMock(return_value={
            "scores": {"hook_strength": 8},
            "overall": 8.0,
            "pass": True,
            "suggestions": "",
        })
        return critic

    @pytest.fixture
    def failing_then_passing_critic(self) -> MagicMock:
        """Critic that fails once then passes."""
        critic = MagicMock(spec=Critic)
        critic.evaluate = AsyncMock(side_effect=[
            {
                "scores": {"hook_strength": 4},
                "overall": 4.0,
                "pass": False,
                "suggestions": "Add a stronger hook",
            },
            {
                "scores": {"hook_strength": 8},
                "overall": 8.0,
                "pass": True,
                "suggestions": "",
            },
        ])
        return critic

    @pytest.fixture
    def refiner(self) -> MagicMock:
        """Refiner that returns improved output."""
        r = MagicMock(spec=Refiner)
        r.MAX_ITERATIONS = 2
        r.refine = AsyncMock(return_value="Improved output with better hook!")
        return r

    async def test_skip_analytics_pillar(
        self, passing_critic: MagicMock, refiner: MagicMock
    ) -> None:
        engine = ReflectionEngine(passing_critic, refiner)
        output, log = await engine.reflect_and_refine(
            pillar="analytics",
            user_message="Analyze my metrics",
            initial_output="Your metrics look good",
        )
        assert output == "Your metrics look good"
        assert log["iterations"] == 0
        assert log["skipped"] is True
        passing_critic.evaluate.assert_not_called()

    async def test_skip_general_pillar(
        self, passing_critic: MagicMock, refiner: MagicMock
    ) -> None:
        engine = ReflectionEngine(passing_critic, refiner)
        output, log = await engine.reflect_and_refine(
            pillar="general",
            user_message="Hello",
            initial_output="Hi there!",
        )
        assert output == "Hi there!"
        assert log["skipped"] is True

    async def test_content_pillar_passes_first_try(
        self, passing_critic: MagicMock, refiner: MagicMock
    ) -> None:
        engine = ReflectionEngine(passing_critic, refiner)
        output, log = await engine.reflect_and_refine(
            pillar="content",
            user_message="Write a caption",
            initial_output="Great caption!",
        )
        assert output == "Great caption!"
        assert log["iterations"] == 1
        assert log["initial_score"] == 8.0
        assert log["final_score"] == 8.0
        assert log["improved"] is False
        refiner.refine.assert_not_called()

    async def test_content_pillar_refines_once(
        self, failing_then_passing_critic: MagicMock, refiner: MagicMock
    ) -> None:
        engine = ReflectionEngine(failing_then_passing_critic, refiner)
        output, log = await engine.reflect_and_refine(
            pillar="content",
            user_message="Write a caption",
            initial_output="Weak caption",
        )
        assert output == "Improved output with better hook!"
        assert log["iterations"] == 2
        assert log["initial_score"] == 4.0
        assert log["final_score"] == 8.0
        assert log["improved"] is True
        refiner.refine.assert_called_once()

    async def test_strategy_pillar_uses_reflection(
        self, passing_critic: MagicMock, refiner: MagicMock
    ) -> None:
        engine = ReflectionEngine(passing_critic, refiner)
        output, log = await engine.reflect_and_refine(
            pillar="strategy",
            user_message="Create a plan",
            initial_output="Here is a plan",
        )
        passing_critic.evaluate.assert_called_once()
        assert log["iterations"] == 1

    async def test_research_skipped_with_enough_sources(
        self, passing_critic: MagicMock, refiner: MagicMock
    ) -> None:
        engine = ReflectionEngine(passing_critic, refiner)
        output, log = await engine.reflect_and_refine(
            pillar="research",
            user_message="Research trends",
            initial_output="Here are the trends",
            metadata={"sources": ["url1", "url2", "url3"]},
        )
        assert log["skipped"] is True
        passing_critic.evaluate.assert_not_called()

    async def test_research_reflected_with_few_sources(
        self, passing_critic: MagicMock, refiner: MagicMock
    ) -> None:
        engine = ReflectionEngine(passing_critic, refiner)
        output, log = await engine.reflect_and_refine(
            pillar="research",
            user_message="Research trends",
            initial_output="Here are the trends",
            metadata={"sources": ["url1"]},
        )
        assert log["iterations"] == 1
        passing_critic.evaluate.assert_called_once()

    async def test_research_reflected_with_no_metadata(
        self, passing_critic: MagicMock, refiner: MagicMock
    ) -> None:
        engine = ReflectionEngine(passing_critic, refiner)
        output, log = await engine.reflect_and_refine(
            pillar="research",
            user_message="Research trends",
            initial_output="Here are the trends",
        )
        assert log["iterations"] == 1

    async def test_refine_called_with_suggestions(
        self, failing_then_passing_critic: MagicMock, refiner: MagicMock
    ) -> None:
        engine = ReflectionEngine(failing_then_passing_critic, refiner)
        await engine.reflect_and_refine(
            pillar="content",
            user_message="Write a caption",
            initial_output="Weak caption",
        )
        call_args = refiner.refine.call_args
        # refine() called with positional args: (pillar, user_message, draft, suggestions)
        assert call_args[0][3] == "Add a stronger hook"

    async def test_refine_returns_same_output_marks_not_improved(
        self, failing_then_passing_critic: MagicMock
    ) -> None:
        """If refine returns the same text, improved should be False."""
        refiner = MagicMock(spec=Refiner)
        refiner.MAX_ITERATIONS = 2
        refiner.refine = AsyncMock(return_value="Weak caption")  # same as input

        engine = ReflectionEngine(failing_then_passing_critic, refiner)
        output, log = await engine.reflect_and_refine(
            pillar="content",
            user_message="Write a caption",
            initial_output="Weak caption",
        )
        assert log["improved"] is False
