"""Tests for the refiner module.

Covers refinement flow, error handling, and the MAX_ITERATIONS config.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from digital_mate.agent.refiner import Refiner, REFINER_SYSTEM_PROMPT


class TestRefinerConfig:
    """Verify refiner configuration."""

    def test_max_iterations(self) -> None:
        assert Refiner.MAX_ITERATIONS == 2


class TestRefinerRefine:
    """Test the Refiner.refine() method."""

    @pytest.fixture
    def mock_llm(self) -> MagicMock:
        client = MagicMock()
        client.chat = AsyncMock(return_value="Improved caption with better hook and CTA!")
        return client

    async def test_refine_returns_improved_text(self, mock_llm: MagicMock) -> None:
        refiner = Refiner(mock_llm)
        result = await refiner.refine(
            pillar="content",
            user_message="Write a caption for skincare",
            draft="Basic skincare caption",
            suggestions="Add a stronger hook, include CTA",
        )
        assert result == "Improved caption with better hook and CTA!"
        mock_llm.chat.assert_called_once()

    async def test_refine_includes_all_inputs_in_prompt(self, mock_llm: MagicMock) -> None:
        refiner = Refiner(mock_llm)
        await refiner.refine(
            pillar="content",
            user_message="Write a caption",
            draft="Draft text",
            suggestions="Make it better",
        )
        call_args = mock_llm.chat.call_args
        messages = call_args[0][0]
        user_msg = messages[1]["content"]
        assert "Write a caption" in user_msg
        assert "Draft text" in user_msg
        assert "Make it better" in user_msg

    async def test_refine_uses_correct_system_prompt(self, mock_llm: MagicMock) -> None:
        refiner = Refiner(mock_llm)
        await refiner.refine(
            pillar="content",
            user_message="Write a caption",
            draft="Draft",
            suggestions="Improve",
        )
        call_args = mock_llm.chat.call_args
        messages = call_args[0][0]
        assert messages[0]["role"] == "system"
        assert "refiner" in messages[0]["content"].lower()

    async def test_refine_returns_draft_on_llm_error(self) -> None:
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(side_effect=Exception("LLM error"))
        refiner = Refiner(mock_llm)
        result = await refiner.refine(
            pillar="content",
            user_message="Write a caption",
            draft="Original draft",
            suggestions="Improve this",
        )
        assert result == "Original draft"

    async def test_refine_returns_draft_on_empty_response(self) -> None:
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value="   ")
        refiner = Refiner(mock_llm)
        result = await refiner.refine(
            pillar="content",
            user_message="Write a caption",
            draft="Original draft",
            suggestions="Improve this",
        )
        assert result == "Original draft"

    async def test_refine_strips_whitespace(self, mock_llm: MagicMock) -> None:
        mock_llm.chat = AsyncMock(return_value="  Refined text  ")
        refiner = Refiner(mock_llm)
        result = await refiner.refine(
            pillar="content",
            user_message="Write a caption",
            draft="Draft",
            suggestions="Improve",
        )
        assert result == "Refined text"
