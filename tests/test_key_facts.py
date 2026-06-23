"""Tests for digital_mate.memory.key_facts module.

Covers KeyFactManager CRUD operations, get_facts_context formatting,
extract_facts_from_conversation with mocked LLM, and integration with
the bot (key facts passed to pillars).
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock

from digital_mate.memory.database import init_memory_db, AsyncConnection
from digital_mate.memory.key_facts import KeyFact, KeyFactManager
from digital_mate.memory.session import SessionManager
from digital_mate.memory.brand_profile import BrandProfileManager
from digital_mate.llm.client import LLMError


@pytest_asyncio.fixture
async def key_fact_db() -> AsyncConnection:
    """Create an in-memory SQLite database for key fact tests."""
    conn = await init_memory_db()
    yield conn
    await conn.close()


# ===========================================================================
# KeyFactManager — CRUD operations
# ===========================================================================

class TestKeyFactManagerCRUD:
    """Test KeyFactManager add, get, deactivate operations."""

    @pytest.mark.asyncio
    async def test_add_fact_inserts_and_returns_true(self, key_fact_db) -> None:
        """add_fact() inserts a new row and returns True."""
        mgr = KeyFactManager(key_fact_db)
        result = await mgr.add_fact(123, "User focuses on Instagram Reels")
        assert result is True

    @pytest.mark.asyncio
    async def test_add_fact_duplicate_returns_false(self, key_fact_db) -> None:
        """add_fact() with duplicate fact_text doesn't insert (returns False)."""
        mgr = KeyFactManager(key_fact_db)
        await mgr.add_fact(123, "User focuses on Instagram Reels")
        result = await mgr.add_fact(123, "User focuses on Instagram Reels")
        assert result is False

    @pytest.mark.asyncio
    async def test_add_fact_same_text_different_chat(self, key_fact_db) -> None:
        """Same fact text for different chat_ids should both succeed."""
        mgr = KeyFactManager(key_fact_db)
        r1 = await mgr.add_fact(100, "Budget is small")
        r2 = await mgr.add_fact(200, "Budget is small")
        assert r1 is True
        assert r2 is True

    @pytest.mark.asyncio
    async def test_add_fact_with_category(self, key_fact_db) -> None:
        """add_fact() stores the category correctly."""
        mgr = KeyFactManager(key_fact_db)
        await mgr.add_fact(123, "User sells coffee", category="products")

        facts = await mgr.get_facts(123)
        assert len(facts) == 1
        assert facts[0].fact_category == "products"

    @pytest.mark.asyncio
    async def test_get_facts_returns_active_only(self, key_fact_db) -> None:
        """get_facts() with active_only=True returns only active facts."""
        mgr = KeyFactManager(key_fact_db)
        await mgr.add_fact(123, "Fact 1")
        await mgr.add_fact(123, "Fact 2")
        await mgr.add_fact(123, "Fact 3")

        facts = await mgr.get_facts(123, active_only=True)
        assert len(facts) == 3
        for f in facts:
            assert f.is_active is True

    @pytest.mark.asyncio
    async def test_get_facts_all_includes_inactive(self, key_fact_db) -> None:
        """get_facts() with active_only=False returns all facts."""
        mgr = KeyFactManager(key_fact_db)
        await mgr.add_fact(123, "Fact 1")
        await mgr.add_fact(123, "Fact 2")

        # Deactivate one
        facts = await mgr.get_facts(123, active_only=False)
        await mgr.deactivate_fact(facts[0].id)

        all_facts = await mgr.get_facts(123, active_only=False)
        active_facts = await mgr.get_facts(123, active_only=True)

        assert len(all_facts) == 2
        assert len(active_facts) == 1

    @pytest.mark.asyncio
    async def test_get_facts_separate_chats(self, key_fact_db) -> None:
        """get_facts() returns facts only for the specified chat_id."""
        mgr = KeyFactManager(key_fact_db)
        await mgr.add_fact(100, "Fact for chat 100")
        await mgr.add_fact(200, "Fact for chat 200")

        facts_100 = await mgr.get_facts(100)
        facts_200 = await mgr.get_facts(200)

        assert len(facts_100) == 1
        assert facts_100[0].fact_text == "Fact for chat 100"
        assert len(facts_200) == 1
        assert facts_200[0].fact_text == "Fact for chat 200"

    @pytest.mark.asyncio
    async def test_get_facts_empty(self, key_fact_db) -> None:
        """get_facts() returns empty list for chat with no facts."""
        mgr = KeyFactManager(key_fact_db)
        facts = await mgr.get_facts(99999)
        assert facts == []

    @pytest.mark.asyncio
    async def test_deactivate_fact_sets_inactive(self, key_fact_db) -> None:
        """deactivate_fact() sets is_active=0 and returns True."""
        mgr = KeyFactManager(key_fact_db)
        await mgr.add_fact(123, "Fact to deactivate")
        facts = await mgr.get_facts(123)
        fact_id = facts[0].id

        result = await mgr.deactivate_fact(fact_id)
        assert result is True

        # Verify it's inactive
        active_facts = await mgr.get_facts(123, active_only=True)
        assert len(active_facts) == 0
        all_facts = await mgr.get_facts(123, active_only=False)
        assert len(all_facts) == 1
        assert all_facts[0].is_active is False

    @pytest.mark.asyncio
    async def test_deactivate_nonexistent_returns_false(self, key_fact_db) -> None:
        """deactivate_fact() on non-existent id returns False."""
        mgr = KeyFactManager(key_fact_db)
        result = await mgr.deactivate_fact(99999)
        assert result is False

    @pytest.mark.asyncio
    async def test_deactivate_already_inactive_returns_false(self, key_fact_db) -> None:
        """deactivate_fact() on already-inactive fact returns False."""
        mgr = KeyFactManager(key_fact_db)
        await mgr.add_fact(123, "Fact")
        facts = await mgr.get_facts(123)
        fact_id = facts[0].id

        # First deactivation succeeds
        r1 = await mgr.deactivate_fact(fact_id)
        assert r1 is True
        # Second deactivation fails (already inactive)
        r2 = await mgr.deactivate_fact(fact_id)
        assert r2 is False

    @pytest.mark.asyncio
    async def test_key_fact_dataclass_defaults(self) -> None:
        """KeyFact dataclass has correct default values."""
        fact = KeyFact(id=1, chat_id=100, fact_text="Test fact")
        assert fact.fact_category == "general"
        assert fact.is_active is True


# ===========================================================================
# KeyFactManager — get_facts_context
# ===========================================================================

class TestKeyFactContext:
    """Test get_facts_context formatting for prompt injection."""

    @pytest.mark.asyncio
    async def test_get_facts_context_with_facts(self, key_fact_db) -> None:
        """get_facts_context() returns formatted string with facts."""
        mgr = KeyFactManager(key_fact_db)
        await mgr.add_fact(123, "User focuses on Instagram Reels")
        await mgr.add_fact(123, "Budget is small")

        ctx = await mgr.get_facts_context(123)
        assert ctx != ""
        assert "## Key Facts About This User" in ctx
        assert "- User focuses on Instagram Reels" in ctx
        assert "- Budget is small" in ctx

    @pytest.mark.asyncio
    async def test_get_facts_context_no_facts(self, key_fact_db) -> None:
        """get_facts_context() returns empty string when no facts exist."""
        mgr = KeyFactManager(key_fact_db)
        ctx = await mgr.get_facts_context(99999)
        assert ctx == ""

    @pytest.mark.asyncio
    async def test_get_facts_context_excludes_inactive(self, key_fact_db) -> None:
        """get_facts_context() only includes active facts."""
        mgr = KeyFactManager(key_fact_db)
        await mgr.add_fact(123, "Active fact")
        await mgr.add_fact(123, "Inactive fact")
        facts = await mgr.get_facts(123)
        await mgr.deactivate_fact(facts[1].id)

        ctx = await mgr.get_facts_context(123)
        assert "Active fact" in ctx
        assert "Inactive fact" not in ctx


# ===========================================================================
# KeyFactManager — extract_facts_from_conversation
# ===========================================================================

class TestExtractFacts:
    """Test extract_facts_from_conversation with mocked LLM."""

    @pytest.mark.asyncio
    async def test_extract_facts_with_mocked_llm(self, key_fact_db) -> None:
        """extract_facts_from_conversation() returns newly added facts."""
        mgr = KeyFactManager(key_fact_db)

        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(return_value={
            "facts": ["User runs a coffee shop", "Budget is micro"]
        })

        messages = [
            {"role": "user", "content": "I run a coffee shop in Jakarta"},
            {"role": "assistant", "content": "Great! How can I help?"},
        ]

        added = await mgr.extract_facts_from_conversation(123, mock_llm, messages)
        assert len(added) == 2
        assert "User runs a coffee shop" in added
        assert "Budget is micro" in added

        # Verify facts persisted
        facts = await mgr.get_facts(123)
        assert len(facts) == 2

    @pytest.mark.asyncio
    async def test_extract_facts_dedup(self, key_fact_db) -> None:
        """extract_facts_from_conversation() deduplicates existing facts."""
        mgr = KeyFactManager(key_fact_db)
        await mgr.add_fact(123, "User runs a coffee shop")

        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(return_value={
            "facts": ["User runs a coffee shop", "User targets Gen Z"]
        })

        added = await mgr.extract_facts_from_conversation(123, mock_llm, [])
        assert len(added) == 1
        assert "User targets Gen Z" in added
        # The duplicate should not be re-added
        assert "User runs a coffee shop" not in added

    @pytest.mark.asyncio
    async def test_extract_facts_llm_error_returns_empty(self, key_fact_db) -> None:
        """extract_facts_from_conversation() returns [] on LLMError."""
        mgr = KeyFactManager(key_fact_db)

        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(side_effect=LLMError("API error"))

        added = await mgr.extract_facts_from_conversation(123, mock_llm, [])
        assert added == []

    @pytest.mark.asyncio
    async def test_extract_facts_empty_response(self, key_fact_db) -> None:
        """extract_facts_from_conversation() handles empty facts list."""
        mgr = KeyFactManager(key_fact_db)

        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(return_value={"facts": []})

        added = await mgr.extract_facts_from_conversation(123, mock_llm, [])
        assert added == []

    @pytest.mark.asyncio
    async def test_extract_facts_non_list_facts(self, key_fact_db) -> None:
        """extract_facts_from_conversation() handles non-list facts field."""
        mgr = KeyFactManager(key_fact_db)

        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(return_value={"facts": "not a list"})

        added = await mgr.extract_facts_from_conversation(123, mock_llm, [])
        assert added == []

    @pytest.mark.asyncio
    async def test_extract_facts_non_string_items(self, key_fact_db) -> None:
        """extract_facts_from_conversation() skips non-string items."""
        mgr = KeyFactManager(key_fact_db)

        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(return_value={
            "facts": ["Valid fact", 123, "", "   ", "Another valid fact"]
        })

        added = await mgr.extract_facts_from_conversation(123, mock_llm, [])
        assert len(added) == 2
        assert "Valid fact" in added
        assert "Another valid fact" in added

    @pytest.mark.asyncio
    async def test_extract_facts_unexpected_error(self, key_fact_db) -> None:
        """extract_facts_from_conversation() handles unexpected errors."""
        mgr = KeyFactManager(key_fact_db)

        mock_llm = MagicMock()
        mock_llm.chat_json = AsyncMock(side_effect=RuntimeError("unexpected"))

        added = await mgr.extract_facts_from_conversation(123, mock_llm, [])
        assert added == []


# ===========================================================================
# SessionManager — get_message_count
# ===========================================================================

class TestSessionMessageCount:
    """Test SessionManager.get_message_count."""

    @pytest.mark.asyncio
    async def test_get_message_count_empty(self, key_fact_db) -> None:
        """get_message_count() returns 0 for chat with no messages."""
        sm = SessionManager(key_fact_db, max_turns=10)
        count = await sm.get_message_count(99999)
        assert count == 0

    @pytest.mark.asyncio
    async def test_get_message_count_with_messages(self, key_fact_db) -> None:
        """get_message_count() returns correct count."""
        sm = SessionManager(key_fact_db, max_turns=10)
        await sm.add_message(100, "user", "Hello")
        await sm.add_message(100, "assistant", "Hi there")
        await sm.add_message(100, "user", "How are you?")

        count = await sm.get_message_count(100)
        assert count == 3

    @pytest.mark.asyncio
    async def test_get_message_count_separate_chats(self, key_fact_db) -> None:
        """get_message_count() returns count only for specified chat."""
        sm = SessionManager(key_fact_db, max_turns=10)
        await sm.add_message(100, "user", "msg1")
        await sm.add_message(200, "user", "msg2")

        assert await sm.get_message_count(100) == 1
        assert await sm.get_message_count(200) == 1


# ===========================================================================
# Prompts — key facts integration
# ===========================================================================

class TestPromptsKeyFacts:
    """Test prompt builders with key facts integration."""

    def test_build_key_facts_context_empty(self) -> None:
        """build_key_facts_context() returns '' for empty input."""
        from digital_mate.llm.prompts import build_key_facts_context
        assert build_key_facts_context("") == ""
        assert build_key_facts_context("   ") == ""

    def test_build_key_facts_context_non_empty(self) -> None:
        """build_key_facts_context() returns the input for non-empty."""
        from digital_mate.llm.prompts import build_key_facts_context
        facts = "## Key Facts About This User\n- Fact 1\n- Fact 2"
        result = build_key_facts_context(facts)
        assert result == facts

    def test_build_brand_context_with_key_facts(self) -> None:
        """build_brand_context() appends key facts when provided."""
        from digital_mate.llm.prompts import build_brand_context
        ctx = build_brand_context(
            name="TestBrand", industry="Tech", audience="Devs",
            tone="Casual", products="Software", hashtags="#dev",
            key_facts="## Key Facts About This User\n- User likes Python",
        )
        assert "## 🏢 Brand Context" in ctx
        assert "## Key Facts About This User" in ctx
        assert "- User likes Python" in ctx

    def test_build_brand_context_without_key_facts(self) -> None:
        """build_brand_context() works without key_facts (backward compat)."""
        from digital_mate.llm.prompts import build_brand_context
        ctx = build_brand_context(
            name="TestBrand", industry="Tech", audience="Devs",
            tone="Casual", products="Software", hashtags="#dev",
        )
        assert "## 🏢 Brand Context" in ctx
        assert "Key Facts" not in ctx

    def test_build_pillar_messages_with_key_facts(self) -> None:
        """build_pillar_messages() includes key facts in system prompt."""
        from digital_mate.llm.prompts import build_pillar_messages
        messages = build_pillar_messages(
            user_message="Write a caption",
            pillar="content",
            context=[],
            brand_context="## Brand Context\nName: TestBrand",
            key_facts="## Key Facts About This User\n- User likes Python",
        )
        system_content = messages[0]["content"]
        assert "## Brand Context" in system_content
        assert "## Key Facts About This User" in system_content
        assert "- User likes Python" in system_content

    def test_build_pillar_messages_without_key_facts(self) -> None:
        """build_pillar_messages() works without key_facts (backward compat)."""
        from digital_mate.llm.prompts import build_pillar_messages
        messages = build_pillar_messages(
            user_message="Write a caption",
            pillar="content",
            context=[],
        )
        system_content = messages[0]["content"]
        # Should still have a system message
        assert len(messages) >= 2

    def test_build_general_messages_with_key_facts(self) -> None:
        """build_general_messages() includes key facts in system prompt."""
        from digital_mate.llm.prompts import build_general_messages
        messages = build_general_messages(
            user_message="Hello",
            context=[],
            key_facts="## Key Facts About This User\n- User likes Python",
        )
        system_content = messages[0]["content"]
        assert "## Key Facts About This User" in system_content
        assert "- User likes Python" in system_content

    def test_build_general_messages_without_key_facts(self) -> None:
        """build_general_messages() works without key_facts (backward compat)."""
        from digital_mate.llm.prompts import build_general_messages
        messages = build_general_messages(
            user_message="Hello",
            context=[],
        )
        assert len(messages) >= 2

    def test_build_router_messages_unchanged(self) -> None:
        """build_router_messages() should NOT accept key_facts."""
        from digital_mate.llm.prompts import build_router_messages
        import inspect
        sig = inspect.signature(build_router_messages)
        assert "key_facts" not in sig.parameters


# ===========================================================================
# Bot integration — key facts passed to pillars
# ===========================================================================

class TestBotKeyFactsIntegration:
    """Test that DigitalMateBot passes key_facts to pillars and general handler."""

    @pytest.mark.asyncio
    async def test_bot_accepts_key_fact_manager(
        self, sample_settings, mock_llm_client, key_fact_db
    ) -> None:
        """DigitalMateBot constructor accepts key_fact_manager."""
        from digital_mate.bot import DigitalMateBot
        from digital_mate.router import IntentRouter
        from digital_mate.memory.session import SessionManager
        from digital_mate.memory.brand_profile import BrandProfileManager

        router = IntentRouter(mock_llm_client)
        sm = SessionManager(key_fact_db)
        bm = BrandProfileManager(key_fact_db)
        kfm = KeyFactManager(key_fact_db)

        bot = DigitalMateBot(
            settings=sample_settings,
            llm_client=mock_llm_client,
            router=router,
            session_manager=sm,
            brand_manager=bm,
            key_fact_manager=kfm,
        )
        assert bot.key_fact_manager is kfm

    @pytest.mark.asyncio
    async def test_bot_without_key_fact_manager(
        self, sample_settings, mock_llm_client, key_fact_db
    ) -> None:
        """DigitalMateBot works without key_fact_manager (backward compat)."""
        from digital_mate.bot import DigitalMateBot
        from digital_mate.router import IntentRouter
        from digital_mate.memory.session import SessionManager
        from digital_mate.memory.brand_profile import BrandProfileManager

        router = IntentRouter(mock_llm_client)
        sm = SessionManager(key_fact_db)
        bm = BrandProfileManager(key_fact_db)

        bot = DigitalMateBot(
            settings=sample_settings,
            llm_client=mock_llm_client,
            router=router,
            session_manager=sm,
            brand_manager=bm,
        )
        assert bot.key_fact_manager is None

    @pytest.mark.asyncio
    async def test_bot_passes_key_facts_to_pillar(
        self, sample_settings, mock_llm_client, key_fact_db
    ) -> None:
        """Bot fetches key facts and passes them to pillar.handle_stream()."""
        from digital_mate.bot import DigitalMateBot
        from digital_mate.router import IntentRouter, RouterResult
        from digital_mate.memory.session import SessionManager
        from digital_mate.memory.brand_profile import BrandProfileManager

        # Add a fact so get_facts_context returns non-empty
        kfm = KeyFactManager(key_fact_db)
        await kfm.add_fact(123456789, "User focuses on Instagram")

        router = IntentRouter(mock_llm_client)
        sm = SessionManager(key_fact_db, max_turns=10)
        bm = BrandProfileManager(key_fact_db)

        bot = DigitalMateBot(
            settings=sample_settings,
            llm_client=mock_llm_client,
            router=router,
            session_manager=sm,
            brand_manager=bm,
            key_fact_manager=kfm,
        )

        # Mock the content pillar's handle_stream to capture key_facts
        captured_kwargs: dict = {}

        async def mock_handle_stream(**kwargs):
            captured_kwargs.update(kwargs)
            yield "Mock response"

        bot.content_pillar.handle_stream = mock_handle_stream

        # Mock router to classify as content
        router.classify = AsyncMock(return_value=RouterResult(
            pillar="content", action="caption", confidence=0.9,
            language_detected="en",
        ))

        # Build mock update
        from tests.test_bot import _make_update, _make_context
        update = _make_update(chat_id=123456789, text="Write a caption")
        ctx = _make_context()

        await bot._handle_message(update, ctx)

        # Verify key_facts was passed to handle_stream
        assert "key_facts" in captured_kwargs
        assert "User focuses on Instagram" in captured_kwargs["key_facts"]

    @pytest.mark.asyncio
    async def test_bot_passes_key_facts_to_general(
        self, sample_settings, mock_llm_client, key_fact_db
    ) -> None:
        """Bot fetches key facts and passes them to _handle_general()."""
        from digital_mate.bot import DigitalMateBot
        from digital_mate.router import IntentRouter, RouterResult
        from digital_mate.memory.session import SessionManager
        from digital_mate.memory.brand_profile import BrandProfileManager

        # Add a fact
        kfm = KeyFactManager(key_fact_db)
        await kfm.add_fact(123456789, "User prefers Indonesian")

        router = IntentRouter(mock_llm_client)
        sm = SessionManager(key_fact_db, max_turns=10)
        bm = BrandProfileManager(key_fact_db)

        bot = DigitalMateBot(
            settings=sample_settings,
            llm_client=mock_llm_client,
            router=router,
            session_manager=sm,
            brand_manager=bm,
            key_fact_manager=kfm,
        )

        # Mock router to classify as general/chitchat
        router.classify = AsyncMock(return_value=RouterResult(
            pillar="general", action="chitchat", confidence=0.9,
            language_detected="en",
        ))

        # Mock LLM chat to capture messages
        captured_messages: list = []

        async def mock_chat(messages, **kwargs):
            captured_messages.extend(messages)
            return "Mock general response"

        mock_llm_client.chat = mock_chat

        from tests.test_bot import _make_update, _make_context
        update = _make_update(chat_id=123456789, text="Halo!")
        ctx = _make_context()

        await bot._handle_message(update, ctx)

        # Verify the system message contains key facts
        system_content = captured_messages[0]["content"]
        assert "## Key Facts About This User" in system_content
        assert "User prefers Indonesian" in system_content

    @pytest.mark.asyncio
    async def test_bot_triggers_fact_extraction_every_10_messages(
        self, sample_settings, mock_llm_client, key_fact_db
    ) -> None:
        """Bot triggers background fact extraction when msg count hits 10."""
        from digital_mate.bot import DigitalMateBot
        from digital_mate.router import IntentRouter, RouterResult
        from digital_mate.memory.session import SessionManager
        from digital_mate.memory.brand_profile import BrandProfileManager
        import asyncio

        kfm = KeyFactManager(key_fact_db)
        router = IntentRouter(mock_llm_client)
        sm = SessionManager(key_fact_db, max_turns=20)
        bm = BrandProfileManager(key_fact_db)

        bot = DigitalMateBot(
            settings=sample_settings,
            llm_client=mock_llm_client,
            router=router,
            session_manager=sm,
            brand_manager=bm,
            key_fact_manager=kfm,
        )

        # Add 8 messages (so after adding user+assistant, we'll have 10)
        for i in range(4):
            await sm.add_message(123456789, "user", f"msg {i}")
            await sm.add_message(123456789, "assistant", f"resp {i}")

        # Mock extract_facts to track if it was called
        extract_called = False

        original_extract = kfm.extract_facts_from_conversation

        async def mock_extract(*args, **kwargs):
            nonlocal extract_called
            extract_called = True
            return []

        kfm.extract_facts_from_conversation = mock_extract

        # Mock router as general to keep it simple
        router.classify = AsyncMock(return_value=RouterResult(
            pillar="general", action="chitchat", confidence=0.9,
            language_detected="en",
        ))

        mock_llm_client.chat = AsyncMock(return_value="Mock response")

        from tests.test_bot import _make_update, _make_context
        update = _make_update(chat_id=123456789, text="test")
        ctx = _make_context()

        await bot._handle_message(update, ctx)

        # After this message, count should be 10 (8 + 2)
        # The background task should have been created
        # Give it a moment to run
        await asyncio.sleep(0.1)

        assert extract_called, "extract_facts_from_conversation should have been called"

        # Restore original
        kfm.extract_facts_from_conversation = original_extract
