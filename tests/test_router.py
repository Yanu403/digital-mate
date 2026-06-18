"""Tests for digital_mate.router module."""

import pytest
from digital_mate.router import IntentRouter, RouterResult, VALID_PILLARS, VALID_ACTIONS


class TestRouterResult:
    """Test RouterResult dataclass."""

    def test_create_result(self) -> None:
        """Test creating a RouterResult."""
        result = RouterResult(pillar="content", action="caption", confidence=0.9, language_detected="en")
        assert result.pillar == "content"
        assert result.action == "caption"
        assert result.confidence == 0.9
        assert result.language_detected == "en"

    def test_is_general(self) -> None:
        """Test is_general property."""
        general = RouterResult(pillar="general", action="chitchat")
        content = RouterResult(pillar="content", action="caption")
        assert general.is_general is True
        assert content.is_general is False

    def test_default_values(self) -> None:
        """Test default confidence and language."""
        result = RouterResult(pillar="strategy", action="plan")
        assert result.confidence == 0.8
        assert result.language_detected == "en"


class TestIntentRouter:
    """Test IntentRouter classification."""

    @pytest.mark.asyncio
    async def test_classify_success(self, mock_llm_client) -> None:
        """Test successful intent classification."""
        mock_llm_client.chat_json.return_value = {
            "pillar": "content",
            "action": "caption",
            "confidence": 0.95,
            "language_detected": "en",
        }
        router = IntentRouter(mock_llm_client)
        result = await router.classify("Write me an Instagram caption")

        assert result.pillar == "content"
        assert result.action == "caption"
        assert result.confidence == 0.95

    @pytest.mark.asyncio
    async def test_classify_invalid_pillar_fallback(self, mock_llm_client) -> None:
        """Test fallback when LLM returns invalid pillar."""
        mock_llm_client.chat_json.return_value = {
            "pillar": "invalid_pillar",
            "action": "caption",
            "confidence": 0.8,
            "language_detected": "en",
        }
        router = IntentRouter(mock_llm_client)
        result = await router.classify("test message")

        assert result.pillar == "general"
        assert result.action == "other"

    @pytest.mark.asyncio
    async def test_classify_invalid_action_fallback(self, mock_llm_client) -> None:
        """Test fallback when LLM returns invalid action for pillar."""
        mock_llm_client.chat_json.return_value = {
            "pillar": "content",
            "action": "nonexistent_action",
            "confidence": 0.8,
            "language_detected": "en",
        }
        router = IntentRouter(mock_llm_client)
        result = await router.classify("test message")

        assert result.pillar == "content"
        assert result.action == "other"

    @pytest.mark.asyncio
    async def test_classify_llm_error_keyword_fallback(self, mock_llm_client) -> None:
        """Test keyword fallback when LLM raises error."""
        from digital_mate.llm.client import LLMError
        mock_llm_client.chat_json.side_effect = LLMError("API error")

        router = IntentRouter(mock_llm_client)

        # Test content keyword
        result = await router.classify("Write me a caption with hashtags")
        assert result.pillar == "content"

        # Test strategy keyword
        result = await router.classify("Create a marketing plan for my business")
        assert result.pillar == "strategy"

        # Test greeting
        result = await router.classify("Hello there!")
        assert result.pillar == "general"
        assert result.action == "chitchat"

    @pytest.mark.asyncio
    async def test_classify_with_context(self, mock_llm_client) -> None:
        """Test classification with conversation context."""
        mock_llm_client.chat_json.return_value = {
            "pillar": "research",
            "action": "trends",
            "confidence": 0.85,
            "language_detected": "en",
        }
        router = IntentRouter(mock_llm_client)
        context = [
            {"role": "user", "content": "Tell me about social media"},
            {"role": "assistant", "content": "Social media is..."},
        ]
        result = await router.classify("What are the latest trends?", context)
        assert result.pillar == "research"
        assert result.action == "trends"

    @pytest.mark.asyncio
    async def test_keyword_fallback_greetings(self, mock_llm_client) -> None:
        """Test keyword fallback for various greetings."""
        from digital_mate.llm.client import LLMError
        mock_llm_client.chat_json.side_effect = LLMError("error")

        router = IntentRouter(mock_llm_client)

        for greeting in ["hi", "hello", "hey", "thanks", "halo", "terima kasih"]:
            result = await router.classify(greeting)
            assert result.pillar == "general"
            assert result.action == "chitchat"

    @pytest.mark.asyncio
    async def test_keyword_fallback_help(self, mock_llm_client) -> None:
        """Test keyword fallback for help requests."""
        from digital_mate.llm.client import LLMError
        mock_llm_client.chat_json.side_effect = LLMError("error")

        router = IntentRouter(mock_llm_client)
        result = await router.classify("What can you do?")
        assert result.pillar == "general"
        assert result.action == "help"

    def test_valid_pillars_and_actions(self) -> None:
        """Test that all pillars have defined actions."""
        for pillar in VALID_PILLARS:
            assert pillar in VALID_ACTIONS
            assert len(VALID_ACTIONS[pillar]) > 0
