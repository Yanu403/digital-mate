"""Tests for the LLM-powered critic module.

Covers rubric lookup, evaluation flow, JSON parsing, and fallback
behavior on LLM errors.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from digital_mate.agent.critic import Critic, RUBRICS, CRITIC_SYSTEM_PROMPT


class TestRubrics:
    """Verify rubric definitions exist for each pillar."""

    def test_content_rubric_exists(self) -> None:
        assert "content" in RUBRICS
        rubric = RUBRICS["content"]
        assert "hook_strength" in rubric["criteria"]
        assert "cta_clarity" in rubric["criteria"]
        assert rubric["threshold"] == 7

    def test_strategy_rubric_exists(self) -> None:
        assert "strategy" in RUBRICS
        rubric = RUBRICS["strategy"]
        assert "completeness" in rubric["criteria"]
        assert rubric["threshold"] == 7

    def test_research_rubric_exists(self) -> None:
        assert "research" in RUBRICS
        rubric = RUBRICS["research"]
        assert "source_quality" in rubric["criteria"]
        assert rubric["threshold"] == 6

    def test_analytics_rubric_exists(self) -> None:
        assert "analytics" in RUBRICS
        rubric = RUBRICS["analytics"]
        assert "accuracy" in rubric["criteria"]
        assert rubric["threshold"] == 6

    def test_all_rubrics_have_required_keys(self) -> None:
        for name, rubric in RUBRICS.items():
            assert "criteria" in rubric, f"{name} missing 'criteria'"
            assert "threshold" in rubric, f"{name} missing 'threshold'"
            assert "description" in rubric, f"{name} missing 'description'"
            assert isinstance(rubric["criteria"], list)
            assert len(rubric["criteria"]) >= 3


class TestCriticEvaluate:
    """Test the Critic.evaluate() method."""

    @pytest.fixture
    def mock_llm(self) -> MagicMock:
        client = MagicMock()
        client.chat_json = AsyncMock(return_value={
            "scores": {"hook_strength": 8, "cta_clarity": 7},
            "overall": 7.5,
            "pass": True,
            "suggestions": "",
        })
        return client

    async def test_evaluate_content_pillar(self, mock_llm: MagicMock) -> None:
        critic = Critic(mock_llm)
        result = await critic.evaluate(
            pillar="content",
            user_message="Write a caption for skincare launch",
            output="New skincare is here! #skincare",
        )
        assert result["pass"] is True
        assert result["overall"] == 7.5
        assert "scores" in result
        mock_llm.chat_json.assert_called_once()

    async def test_evaluate_strategy_pillar(self, mock_llm: MagicMock) -> None:
        critic = Critic(mock_llm)
        result = await critic.evaluate(
            pillar="strategy",
            user_message="Create a marketing plan",
            output="Here is your plan...",
        )
        assert result["pass"] is True

    async def test_evaluate_unknown_pillar_auto_passes(self, mock_llm: MagicMock) -> None:
        critic = Critic(mock_llm)
        result = await critic.evaluate(
            pillar="general",
            user_message="Hello",
            output="Hi there!",
        )
        assert result["pass"] is True
        assert result["overall"] == 10.0
        mock_llm.chat_json.assert_not_called()

    async def test_evaluate_includes_brand_context(self, mock_llm: MagicMock) -> None:
        critic = Critic(mock_llm)
        await critic.evaluate(
            pillar="content",
            user_message="Write a caption",
            output="Caption text",
            brand_context="Brand: TestCo, Industry: Tech",
        )
        call_args = mock_llm.chat_json.call_args
        messages = call_args[0][0]
        user_msg = messages[1]["content"]
        assert "Brand: TestCo" in user_msg

    async def test_evaluate_llm_error_returns_passing_default(self) -> None:
        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(side_effect=Exception("LLM down"))
        critic = Critic(mock_llm)
        result = await critic.evaluate(
            pillar="content",
            user_message="Write a caption",
            output="Caption",
        )
        # Should return a passing default so we don't block delivery
        assert result["pass"] is True
        assert result["overall"] == 7.0

    async def test_evaluate_normalizes_non_bool_pass(self) -> None:
        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(return_value={
            "scores": {},
            "overall": 5.0,
            "pass": "yes",  # non-bool
            "suggestions": "",
        })
        critic = Critic(mock_llm)
        result = await critic.evaluate(
            pillar="content",
            user_message="Write a caption",
            output="Caption",
        )
        assert result["pass"] is False  # normalized to bool

    async def test_evaluate_normalizes_non_dict_scores(self) -> None:
        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(return_value={
            "scores": "invalid",  # non-dict
            "overall": 7.0,
            "pass": True,
            "suggestions": "",
        })
        critic = Critic(mock_llm)
        result = await critic.evaluate(
            pillar="content",
            user_message="Write a caption",
            output="Caption",
        )
        assert result["scores"] == {}
