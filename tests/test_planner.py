"""Tests for Planner — LLM-powered goal decomposition."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from digital_mate.llm.client import LLMClient, LLMError
from digital_mate.agent.planner import Planner, PLANNER_SYSTEM_PROMPT


@pytest.fixture
def mock_llm() -> MagicMock:
    """Create a mock LLMClient."""
    client = MagicMock(spec=LLMClient)
    client.chat_json = AsyncMock()
    return client


class TestCreatePlan:
    """Tests for Planner.create_plan."""

    @pytest.mark.asyncio
    async def test_create_plan_valid_json(self, mock_llm: MagicMock):
        mock_llm.chat_json = AsyncMock(return_value=[
            {"pillar": "research", "action": "trends", "description": "Research trends", "input_from": "user_request"},
            {"pillar": "content", "action": "caption", "description": "Write captions", "input_from": "step_1"},
        ])
        planner = Planner(mock_llm)
        steps = await planner.create_plan("Launch a skincare campaign on Instagram")
        assert len(steps) == 2
        assert steps[0]["pillar"] == "research"
        assert steps[0]["action"] == "trends"
        assert steps[1]["pillar"] == "content"
        assert steps[1]["input_from"] == "step_1"

    @pytest.mark.asyncio
    async def test_create_plan_invalid_pillar_retries(self, mock_llm: MagicMock):
        """Invalid pillar should cause validation failure and retry."""
        # First call: invalid pillar "social"
        # Second call: valid steps
        mock_llm.chat_json = AsyncMock(side_effect=[
            [{"pillar": "social", "action": "post", "description": "Post on social", "input_from": "user_request"}],
            [{"pillar": "research", "action": "trends", "description": "Research trends", "input_from": "user_request"}],
        ])
        planner = Planner(mock_llm)
        steps = await planner.create_plan("Test goal")
        assert len(steps) == 1
        assert steps[0]["pillar"] == "research"
        assert mock_llm.chat_json.call_count == 2

    @pytest.mark.asyncio
    async def test_create_plan_empty_on_failure(self, mock_llm: MagicMock):
        """Both attempts fail → returns empty list."""
        mock_llm.chat_json = AsyncMock(side_effect=LLMError("API down"))
        planner = Planner(mock_llm)
        steps = await planner.create_plan("Test goal")
        assert steps == []
        assert mock_llm.chat_json.call_count == 2

    @pytest.mark.asyncio
    async def test_create_plan_includes_brand_context(self, mock_llm: MagicMock):
        mock_llm.chat_json = AsyncMock(return_value=[
            {"pillar": "research", "action": "trends", "description": "Research trends", "input_from": "user_request"},
        ])
        planner = Planner(mock_llm)
        await planner.create_plan("Test goal", brand_context="Brand: CoffeeCo")
        call_args = mock_llm.chat_json.call_args
        messages = call_args[0][0]
        user_msg = messages[1]["content"]
        assert "Brand: CoffeeCo" in user_msg

    @pytest.mark.asyncio
    async def test_create_plan_includes_key_facts(self, mock_llm: MagicMock):
        mock_llm.chat_json = AsyncMock(return_value=[
            {"pillar": "research", "action": "trends", "description": "Research trends", "input_from": "user_request"},
        ])
        planner = Planner(mock_llm)
        await planner.create_plan("Test goal", key_facts="User prefers organic products")
        call_args = mock_llm.chat_json.call_args
        messages = call_args[0][0]
        user_msg = messages[1]["content"]
        assert "User prefers organic products" in user_msg

    @pytest.mark.asyncio
    async def test_create_plan_uses_system_prompt(self, mock_llm: MagicMock):
        mock_llm.chat_json = AsyncMock(return_value=[
            {"pillar": "research", "action": "trends", "description": "Research", "input_from": "user_request"},
        ])
        planner = Planner(mock_llm)
        await planner.create_plan("Test")
        call_args = mock_llm.chat_json.call_args
        messages = call_args[0][0]
        assert messages[0]["role"] == "system"
        assert "marketing plan decomposer" in messages[0]["content"].lower()

    @pytest.mark.asyncio
    async def test_create_plan_wraps_dict_response(self, mock_llm: MagicMock):
        """If LLM wraps the array in an object, parse it."""
        mock_llm.chat_json = AsyncMock(return_value={
            "steps": [
                {"pillar": "research", "action": "trends", "description": "Research", "input_from": "user_request"},
                {"pillar": "content", "action": "caption", "description": "Write", "input_from": "step_1"},
            ]
        })
        planner = Planner(mock_llm)
        steps = await planner.create_plan("Test")
        assert len(steps) == 2

    @pytest.mark.asyncio
    async def test_create_plan_validates_actions(self, mock_llm: MagicMock):
        """Invalid action for a valid pillar should fail validation."""
        mock_llm.chat_json = AsyncMock(return_value=[
            {"pillar": "research", "action": "invalid_action", "description": "Bad action", "input_from": "user_request"},
        ])
        planner = Planner(mock_llm)
        steps = await planner.create_plan("Test")
        # Should retry and fail both times (same response)
        assert steps == []


class TestParseSteps:
    """Tests for Planner._parse_steps validation."""

    def setup_method(self):
        self.planner = Planner(MagicMock(spec=LLMClient))

    def test_valid_steps(self):
        data = [
            {"pillar": "research", "action": "trends", "description": "Research", "input_from": "user_request"},
            {"pillar": "strategy", "action": "plan", "description": "Plan", "input_from": "step_1"},
        ]
        steps = self.planner._parse_steps(data)
        assert len(steps) == 2

    def test_invalid_pillar_returns_empty(self):
        data = [{"pillar": "invalid", "action": "trends", "description": "Bad", "input_from": "user_request"}]
        steps = self.planner._parse_steps(data)
        assert steps == []

    def test_general_pillar_returns_empty(self):
        data = [{"pillar": "general", "action": "chitchat", "description": "Chat", "input_from": "user_request"}]
        steps = self.planner._parse_steps(data)
        assert steps == []

    def test_invalid_action_returns_empty(self):
        data = [{"pillar": "research", "action": "nonexistent", "description": "Bad", "input_from": "user_request"}]
        steps = self.planner._parse_steps(data)
        assert steps == []

    def test_non_list_returns_empty(self):
        steps = self.planner._parse_steps("not a list")
        assert steps == []

    def test_future_step_reference_corrected(self):
        """Referencing a future step should be corrected to user_request."""
        data = [
            {"pillar": "research", "action": "trends", "description": "Research", "input_from": "step_2"},
            {"pillar": "content", "action": "caption", "description": "Write", "input_from": "step_1"},
        ]
        steps = self.planner._parse_steps(data)
        # step_2 referenced from step 1 (i=0) → invalid, corrected to user_request
        assert steps[0]["input_from"] == "user_request"
        # step_1 referenced from step 2 (i=1) → valid
        assert steps[1]["input_from"] == "step_1"

    def test_missing_description_gets_default(self):
        data = [{"pillar": "research", "action": "trends", "description": "", "input_from": "user_request"}]
        steps = self.planner._parse_steps(data)
        assert len(steps) == 1
        assert "research.trends" in steps[0]["description"]

    def test_missing_input_from_defaults(self):
        data = [{"pillar": "research", "action": "trends", "description": "Research"}]
        steps = self.planner._parse_steps(data)
        assert steps[0]["input_from"] == "user_request"
