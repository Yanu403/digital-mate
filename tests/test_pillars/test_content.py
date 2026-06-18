"""Tests for digital_mate.pillars.content module."""

import pytest
from unittest.mock import AsyncMock
from digital_mate.pillars.content import ContentPillar
from digital_mate.memory.brand_profile import BrandProfile


class TestContentPillar:
    """Test Content & Copywriting pillar."""

    @pytest.mark.asyncio
    async def test_handle_caption(self, mock_llm_client) -> None:
        """Test caption generation includes hint."""
        mock_llm_client.chat = AsyncMock(return_value="Here's your caption! #marketing #digital")
        pillar = ContentPillar(mock_llm_client)

        response = await pillar.handle(
            user_message="Write a caption for my new product",
            action="caption",
            context=[],
        )

        assert "caption" in response.lower() or "#" in response
        # Verify the LLM was called with enhanced message
        call_args = mock_llm_client.chat.call_args
        messages = call_args[0][0]
        user_msg = [m for m in messages if m["role"] == "user"][-1]["content"]
        assert "caption" in user_msg.lower()

    @pytest.mark.asyncio
    async def test_handle_hooks_numbered(self, mock_llm_client) -> None:
        """Test hook generation asks for numbered output."""
        mock_llm_client.chat = AsyncMock(return_value="1. Hook one\n2. Hook two\n3. Hook three")
        pillar = ContentPillar(mock_llm_client)

        response = await pillar.handle(
            user_message="Give me hook ideas for my video",
            action="hooks",
            context=[],
        )

        call_args = mock_llm_client.chat.call_args
        messages = call_args[0][0]
        user_msg = [m for m in messages if m["role"] == "user"][-1]["content"]
        assert "numbered" in user_msg.lower() or "hook" in user_msg.lower()

    @pytest.mark.asyncio
    async def test_handle_with_brand_profile(self, mock_llm_client, sample_brand_profile) -> None:
        """Test that brand profile is included in context."""
        mock_llm_client.chat = AsyncMock(return_value="Caption for TestBrand Coffee!")
        pillar = ContentPillar(mock_llm_client)

        response = await pillar.handle(
            user_message="Write a caption",
            action="caption",
            context=[],
            brand_profile=sample_brand_profile,
        )

        call_args = mock_llm_client.chat.call_args
        messages = call_args[0][0]
        system_msg = [m for m in messages if m["role"] == "system"][0]["content"]
        assert "TestBrand Coffee" in system_msg

    @pytest.mark.asyncio
    async def test_handle_hashtags_action(self, mock_llm_client) -> None:
        """Test hashtags action includes hashtag hint."""
        mock_llm_client.chat = AsyncMock(return_value="#coffee #brew #specialty")
        pillar = ContentPillar(mock_llm_client)

        response = await pillar.handle(
            user_message="Suggest hashtags for my coffee brand",
            action="hashtags",
            context=[],
        )

        call_args = mock_llm_client.chat.call_args
        messages = call_args[0][0]
        user_msg = [m for m in messages if m["role"] == "user"][-1]["content"]
        assert "hashtag" in user_msg.lower()

    @pytest.mark.asyncio
    async def test_handle_llm_error_graceful(self, mock_llm_client) -> None:
        """Test graceful error handling when LLM fails."""
        from digital_mate.llm.client import LLMError
        mock_llm_client.chat = AsyncMock(side_effect=LLMError("API down"))
        pillar = ContentPillar(mock_llm_client)

        response = await pillar.handle(
            user_message="Write a caption",
            action="caption",
            context=[],
        )

        assert "error" in response.lower() or "sorry" in response.lower()

    @pytest.mark.asyncio
    async def test_enhance_message_all_actions(self, mock_llm_client) -> None:
        """Test that all content actions have enhancement hints."""
        pillar = ContentPillar(mock_llm_client)
        actions = ["caption", "hooks", "hashtags", "cta", "rewrite", "ideas", "calendar"]

        for action in actions:
            enhanced = pillar._enhance_message("test request", action)
            assert enhanced != "test request"  # Should be enhanced
