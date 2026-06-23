"""Tests for the feedback button system (👍/👎/🔄).

Covers:
* ``ResponseStore`` — store, get, update_feedback, update_response, stats.
* ``feedback_keyboard`` — InlineKeyboardMarkup construction & callback data.
* ``DigitalMateBot`` — feedback keyboard attached only to pillar responses,
  NOT to general chitchat/help/brand; feedback callback handler flows for
  👍, 👎, and 🔄 regenerate.
* Backward-compatibility: ``response_store=None`` keeps existing behaviour.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from digital_mate.bot import DigitalMateBot
from digital_mate.memory.database import init_memory_db
from digital_mate.memory.response_store import ResponseStore, ResponseRecord
from digital_mate.memory.session import SessionManager
from digital_mate.memory.brand_profile import BrandProfileManager
from digital_mate.router import IntentRouter, RouterResult
from digital_mate.utils.keyboards import feedback_keyboard


# ---------------------------------------------------------------------------
# Helpers (mirror the style used in tests/test_bot.py)
# ---------------------------------------------------------------------------

def _make_update(chat_id: int = 123456789, text: str = "test message") -> AsyncMock:
    """Create a mock Telegram Update object for a text message.

    ``reply_text`` returns a mock Message that also has ``edit_text``
    so streaming code can progressively edit the placeholder.
    The list ``update._sent_messages`` tracks all messages created.
    Mirrors the helper used in tests/test_bot.py.
    """
    update = AsyncMock()
    update.effective_chat.id = chat_id
    update.message.text = text

    sent_messages: list[AsyncMock] = []
    update._sent_messages = sent_messages

    def _make_msg() -> AsyncMock:
        msg = AsyncMock()
        msg.edit_text = AsyncMock()
        msg.reply_text = AsyncMock()
        sent_messages.append(msg)
        return msg

    update.message.reply_text = AsyncMock(side_effect=lambda *a, **kw: _make_msg())
    update.message.chat.send_action = AsyncMock()
    return update


def _make_callback_update(callback_data: str, chat_id: int = 123456789) -> AsyncMock:
    """Create a mock Telegram Update object for a callback query press."""
    update = AsyncMock()
    update.effective_chat.id = chat_id
    update.callback_query = AsyncMock()
    update.callback_query.data = callback_data
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_reply_markup = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    update.callback_query.message = AsyncMock()
    update.callback_query.message.chat = AsyncMock()
    update.callback_query.message.chat.send_action = AsyncMock()
    update.callback_query.message.reply_text = AsyncMock()
    return update


def _make_context(**chat_data_fields) -> AsyncMock:
    """Create a mock Telegram context with optional chat_data."""
    ctx = AsyncMock()
    ctx.chat_data = dict(chat_data_fields)
    ctx.args = []
    return ctx


def _make_bot(
    sample_settings,
    mock_llm_client,
    response_store: ResponseStore | None = None,
) -> DigitalMateBot:
    """Build a DigitalMateBot with mocked dependencies and optional store."""
    router = IntentRouter(mock_llm_client)

    session_mgr = AsyncMock(spec=SessionManager)
    session_mgr.get_context = AsyncMock(return_value=[])
    session_mgr.add_message = AsyncMock()

    brand_mgr = AsyncMock(spec=BrandProfileManager)
    brand_mgr.get = AsyncMock(return_value=None)
    brand_mgr.create_or_update = AsyncMock()

    return DigitalMateBot(
        settings=sample_settings,
        llm_client=mock_llm_client,
        router=router,
        session_manager=session_mgr,
        brand_manager=brand_mgr,
        notion_service=None,
        search_service=None,
        response_store=response_store,
    )


# ===========================================================================
# 1. ResponseStore
# ===========================================================================

class TestResponseStore:
    """Test the ResponseStore persistence layer."""

    @pytest.mark.asyncio
    async def test_store_returns_log_id(self, temp_db) -> None:
        """store() should return an integer log_id for the new row."""
        store = ResponseStore(temp_db)
        log_id = await store.store(
            chat_id=1001,
            pillar="content",
            action="caption",
            user_request="Write a caption",
            response_text="Here is a caption!",
        )
        assert isinstance(log_id, int)
        assert log_id > 0

    @pytest.mark.asyncio
    async def test_store_and_get_roundtrip(self, temp_db) -> None:
        """get() should retrieve the record stored by store()."""
        store = ResponseStore(temp_db)
        log_id = await store.store(
            chat_id=1002,
            pillar="strategy",
            action="plan",
            user_request="Make a plan",
            response_text="Here is the plan.",
        )
        record = await store.get(log_id)
        assert record is not None
        assert record.log_id == log_id
        assert record.chat_id == 1002
        assert record.pillar == "strategy"
        assert record.action == "plan"
        assert record.user_request == "Make a plan"
        assert record.response_text == "Here is the plan."
        assert record.feedback is None
        assert record.regen_count == 0

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, temp_db) -> None:
        """get() on a missing log_id returns None."""
        store = ResponseStore(temp_db)
        record = await store.get(999999)
        assert record is None

    @pytest.mark.asyncio
    async def test_store_with_regen_count(self, temp_db) -> None:
        """store(regen_count=...) should persist the counter."""
        store = ResponseStore(temp_db)
        log_id = await store.store(
            chat_id=1003,
            pillar="research",
            action="trends",
            user_request="What are the trends?",
            response_text="Trendy stuff.",
            regen_count=2,
        )
        record = await store.get(log_id)
        assert record is not None
        assert record.regen_count == 2

    @pytest.mark.asyncio
    async def test_update_feedback_up(self, temp_db) -> None:
        """update_feedback('up') sets feedback='up'."""
        store = ResponseStore(temp_db)
        log_id = await store.store(
            chat_id=1004, pillar="content", action="caption",
            user_request="req", response_text="resp",
        )
        await store.update_feedback(log_id, "up")
        record = await store.get(log_id)
        assert record is not None
        assert record.feedback == "up"

    @pytest.mark.asyncio
    async def test_update_feedback_down(self, temp_db) -> None:
        """update_feedback('down') sets feedback='down'."""
        store = ResponseStore(temp_db)
        log_id = await store.store(
            chat_id=1005, pillar="content", action="caption",
            user_request="req", response_text="resp",
        )
        await store.update_feedback(log_id, "down")
        record = await store.get(log_id)
        assert record is not None
        assert record.feedback == "down"

    @pytest.mark.asyncio
    async def test_update_feedback_overwrites(self, temp_db) -> None:
        """A second update_feedback call should overwrite the previous value."""
        store = ResponseStore(temp_db)
        log_id = await store.store(
            chat_id=1006, pillar="content", action="caption",
            user_request="req", response_text="resp",
        )
        await store.update_feedback(log_id, "up")
        await store.update_feedback(log_id, "down")
        record = await store.get(log_id)
        assert record is not None
        assert record.feedback == "down"

    @pytest.mark.asyncio
    async def test_update_feedback_nonexistent_no_raise(self, temp_db) -> None:
        """update_feedback on a missing log_id should not raise."""
        store = ResponseStore(temp_db)
        # Should not raise even though the log_id doesn't exist
        await store.update_feedback(999999, "up")

    @pytest.mark.asyncio
    async def test_update_response(self, temp_db) -> None:
        """update_response replaces the response_text and bumps regen_count."""
        store = ResponseStore(temp_db)
        log_id = await store.store(
            chat_id=1007, pillar="content", action="caption",
            user_request="original request", response_text="original response",
        )
        await store.update_response(log_id, "new regenerated response", increment_regen=True)
        record = await store.get(log_id)
        assert record is not None
        assert record.response_text == "new regenerated response"
        assert record.regen_count == 1
        # The original request must be preserved
        assert record.user_request == "original request"

    @pytest.mark.asyncio
    async def test_get_last(self, temp_db) -> None:
        """get_last() returns the most recently stored record for a chat."""
        store = ResponseStore(temp_db)
        await store.store(
            chat_id=1008, pillar="content", action="caption",
            user_request="first", response_text="first resp",
        )
        second_id = await store.store(
            chat_id=1008, pillar="content", action="caption",
            user_request="second", response_text="second resp",
        )
        last = await store.get_last_for_chat(1008)
        assert last is not None
        assert last.log_id == second_id
        assert last.user_request == "second"

    @pytest.mark.asyncio
    async def test_get_last_nonexistent(self, temp_db) -> None:
        """get_last() for a chat with no records returns None."""
        store = ResponseStore(temp_db)
        last = await store.get_last_for_chat(9999)
        assert last is None

    @pytest.mark.asyncio
    async def test_stats_empty(self, temp_db) -> None:
        """stats() with no records returns all-zero counts."""
        store = ResponseStore(temp_db)
        stats = await store.count_feedback()
        assert stats == {"up": 0, "down": 0, "none": 0}

    @pytest.mark.asyncio
    async def test_stats_with_feedback(self, temp_db) -> None:
        """stats() aggregates up/down/none counts correctly."""
        store = ResponseStore(temp_db)
        # 2 up, 1 down, 1 none
        up1 = await store.store(1, "content", "caption", "r", "resp")
        up2 = await store.store(2, "content", "caption", "r", "resp")
        down1 = await store.store(3, "content", "caption", "r", "resp")
        none1 = await store.store(4, "content", "caption", "r", "resp")
        await store.update_feedback(up1, "up")
        await store.update_feedback(up2, "up")
        await store.update_feedback(down1, "down")
        # none1 left without feedback

        stats = await store.count_feedback()
        assert stats["up"] == 2
        assert stats["down"] == 1
        assert stats["none"] == 1

    @pytest.mark.asyncio
    async def test_stats_for_specific_chat(self, temp_db) -> None:
        """stats(chat_id=...) scopes counts to that chat."""
        store = ResponseStore(temp_db)
        a1 = await store.store(100, "content", "caption", "r", "resp")
        a2 = await store.store(100, "content", "caption", "r", "resp")
        b1 = await store.store(200, "content", "caption", "r", "resp")
        await store.update_feedback(a1, "up")
        await store.update_feedback(a2, "down")
        await store.update_feedback(b1, "up")

        stats_chat100 = await store.count_feedback(chat_id=100)
        assert stats_chat100 == {"up": 1, "down": 1, "none": 0}

        stats_chat200 = await store.count_feedback(chat_id=200)
        assert stats_chat200 == {"up": 1, "down": 0, "none": 0}


# ===========================================================================
# 2. feedback_keyboard
# ===========================================================================

class TestFeedbackKeyboard:
    """Test the feedback_keyboard builder."""

    def test_returns_inline_keyboard(self) -> None:
        """feedback_keyboard returns an InlineKeyboardMarkup."""
        kb = feedback_keyboard(42)
        # Import lazily so the test doesn't hard-fail if telegram isn't installed
        from telegram import InlineKeyboardMarkup
        assert isinstance(kb, InlineKeyboardMarkup)

    def test_has_three_buttons(self) -> None:
        """The keyboard has exactly 3 buttons (👍/👎/🔄)."""
        kb = feedback_keyboard(42)
        buttons = kb.inline_keyboard[0]
        assert len(buttons) == 3

    def test_button_callback_data_format(self) -> None:
        """Each button has the correct fb:<action>:<id> callback data."""
        kb = feedback_keyboard(7)
        buttons = kb.inline_keyboard[0]
        callback_datas = [b.callback_data for b in buttons]
        assert "fb:up:7" in callback_datas
        assert "fb:down:7" in callback_datas
        assert "fb:regen:7" in callback_datas

    def test_button_emojis_present(self) -> None:
        """The buttons display the 👍, 👎, 🔄 emojis."""
        kb = feedback_keyboard(1)
        buttons = kb.inline_keyboard[0]
        texts = [b.text for b in buttons]
        assert any("👍" in t for t in texts)
        assert any("👎" in t for t in texts)
        assert any("🔄" in t for t in texts)


# ===========================================================================
# 3. Bot: feedback keyboard attachment behaviour
# ===========================================================================

class TestFeedbackAttachment:
    """Test that feedback buttons are attached only to pillar responses."""

    @pytest.mark.asyncio
    async def test_pillar_response_gets_keyboard(
        self, sample_settings, mock_llm_client, temp_db
    ) -> None:
        """A pillar response should be sent with reply_markup on the last chunk."""
        store = ResponseStore(temp_db)
        mock_llm_client.chat_json.return_value = {
            "pillar": "content", "action": "caption",
            "confidence": 0.9, "language_detected": "en",
        }
        bot = _make_bot(sample_settings, mock_llm_client, response_store=store)
        bot.content_pillar.handle = AsyncMock(return_value="Here's your caption!")

        async def _stream(*a, **kw):
            yield "Here's your caption!"
        bot.content_pillar.handle_stream = _stream

        update = _make_update(text="Write me a caption")
        ctx = _make_context()

        await bot._handle_message(update, ctx)

        # The feedback keyboard is attached via edit_text on the last sent
        # message (the streaming placeholder), not via reply_text kwargs.
        assert update._sent_messages, "expected at least one sent message"
        last_msg = update._sent_messages[-1]
        assert last_msg.edit_text.called, "expected edit_text to be called on last message"
        last_edit_kwargs = last_msg.edit_text.call_args_list[-1].kwargs
        assert "reply_markup" in last_edit_kwargs
        assert last_edit_kwargs["reply_markup"] is not None

    @pytest.mark.asyncio
    async def test_general_chitchat_no_keyboard(
        self, sample_settings, mock_llm_client, temp_db
    ) -> None:
        """General chitchat responses should NOT get a feedback keyboard."""
        store = ResponseStore(temp_db)
        mock_llm_client.chat_json.return_value = {
            "pillar": "general", "action": "chitchat",
            "confidence": 0.9, "language_detected": "en",
        }
        mock_llm_client.chat.return_value = "Hey there! How can I help?"
        bot = _make_bot(sample_settings, mock_llm_client, response_store=store)
        update = _make_update(text="hi there")
        ctx = _make_context()

        await bot._handle_message(update, ctx)

        calls = update.message.reply_text.call_args_list
        for call in calls:
            # No reply_markup should be set on any chunk
            assert call.kwargs.get("reply_markup") is None

    @pytest.mark.asyncio
    async def test_general_help_no_keyboard(
        self, sample_settings, mock_llm_client, temp_db
    ) -> None:
        """General/help responses should NOT get a feedback keyboard."""
        store = ResponseStore(temp_db)
        mock_llm_client.chat_json.return_value = {
            "pillar": "general", "action": "help",
            "confidence": 0.9, "language_detected": "en",
        }
        bot = _make_bot(sample_settings, mock_llm_client, response_store=store)
        update = _make_update(text="help")
        ctx = _make_context()

        await bot._handle_message(update, ctx)

        calls = update.message.reply_text.call_args_list
        for call in calls:
            assert call.kwargs.get("reply_markup") is None

    @pytest.mark.asyncio
    async def test_general_brand_no_keyboard(
        self, sample_settings, mock_llm_client, temp_db
    ) -> None:
        """General/brand responses should NOT get a feedback keyboard."""
        store = ResponseStore(temp_db)
        mock_llm_client.chat_json.return_value = {
            "pillar": "general", "action": "brand",
            "confidence": 0.9, "language_detected": "en",
        }
        bot = _make_bot(sample_settings, mock_llm_client, response_store=store)
        update = _make_update(text="set up my brand")
        ctx = _make_context()

        await bot._handle_message(update, ctx)

        calls = update.message.reply_text.call_args_list
        for call in calls:
            assert call.kwargs.get("reply_markup") is None

    @pytest.mark.asyncio
    async def test_no_store_means_no_keyboard(
        self, sample_settings, mock_llm_client
    ) -> None:
        """When response_store is None, pillar responses get no keyboard."""
        mock_llm_client.chat_json.return_value = {
            "pillar": "content", "action": "caption",
            "confidence": 0.9, "language_detected": "en",
        }
        bot = _make_bot(sample_settings, mock_llm_client, response_store=None)
        bot.content_pillar.handle = AsyncMock(return_value="caption here")
        update = _make_update(text="Write me a caption")
        ctx = _make_context()

        await bot._handle_message(update, ctx)

        calls = update.message.reply_text.call_args_list
        for call in calls:
            assert call.kwargs.get("reply_markup") is None

    @pytest.mark.asyncio
    async def test_keyboard_only_on_last_chunk(
        self, sample_settings, mock_llm_client, temp_db
    ) -> None:
        """Multi-chunk responses should only attach keyboard to the last chunk."""
        store = ResponseStore(temp_db)
        mock_llm_client.chat_json.return_value = {
            "pillar": "content", "action": "caption",
            "confidence": 0.9, "language_detected": "en",
        }
        # Build a very long response that will be split into multiple chunks
        long_response = "A" * 5000
        bot = _make_bot(sample_settings, mock_llm_client, response_store=store)
        bot.content_pillar.handle = AsyncMock(return_value=long_response)

        async def _stream(*a, **kw):
            yield long_response
        bot.content_pillar.handle_stream = _stream

        update = _make_update(text="Write a long caption")
        ctx = _make_context()

        await bot._handle_message(update, ctx)

        # Streaming splits long responses across multiple sent messages.
        # The feedback keyboard is attached via edit_text on the LAST sent
        # message only.
        assert len(update._sent_messages) >= 2  # at least 2 chunks
        # All messages except the last should have NO reply_markup on edit_text
        for msg in update._sent_messages[:-1]:
            for call in msg.edit_text.call_args_list:
                assert call.kwargs.get("reply_markup") is None
        # The last message should have a reply_markup on its final edit_text
        last_msg = update._sent_messages[-1]
        assert last_msg.edit_text.call_args_list[-1].kwargs.get("reply_markup") is not None

    @pytest.mark.asyncio
    async def test_store_records_response(
        self, sample_settings, mock_llm_client, temp_db
    ) -> None:
        """The response_store should record the pillar response when attached."""
        store = ResponseStore(temp_db)
        mock_llm_client.chat_json.return_value = {
            "pillar": "content", "action": "caption",
            "confidence": 0.9, "language_detected": "en",
        }
        bot = _make_bot(sample_settings, mock_llm_client, response_store=store)
        bot.content_pillar.handle = AsyncMock(return_value="caption text")

        async def _stream(*a, **kw):
            yield "caption text"
        bot.content_pillar.handle_stream = _stream

        update = _make_update(chat_id=555555, text="Write me a caption")
        ctx = _make_context()

        await bot._handle_message(update, ctx)

        last = await store.get_last_for_chat(555555)
        assert last is not None
        assert last.pillar == "content"
        assert last.action == "caption"
        assert last.user_request == "Write me a caption"
        assert last.response_text == "caption text"


# ===========================================================================
# 4. Bot: feedback callback handler
# ===========================================================================

class TestFeedbackCallbackHandler:
    """Test the _handle_feedback_callback method for 👍/👎/🔄."""

    @pytest.mark.asyncio
    async def test_upvote_updates_db_and_removes_keyboard(
        self, sample_settings, mock_llm_client, temp_db
    ) -> None:
        """👍 should update feedback to 'up', remove keyboard, and thank."""
        store = ResponseStore(temp_db)
        log_id = await store.store(
            chat_id=123, pillar="content", action="caption",
            user_request="req", response_text="resp",
        )
        bot = _make_bot(sample_settings, mock_llm_client, response_store=store)
        update = _make_callback_update(f"fb:up:{log_id}")

        await bot._handle_feedback_callback(update, MagicMock())

        update.callback_query.answer.assert_awaited_once()
        update.callback_query.edit_message_reply_markup.assert_awaited_once()
        # The thanks message should be sent
        update.callback_query.message.reply_text.assert_awaited()
        thanks_text = update.callback_query.message.reply_text.call_args[0][0]
        assert "Thanks" in thanks_text or "👍" in thanks_text
        # DB should now show 'up'
        record = await store.get(log_id)
        assert record is not None
        assert record.feedback == "up"

    @pytest.mark.asyncio
    async def test_downvote_updates_db_and_removes_keyboard(
        self, sample_settings, mock_llm_client, temp_db
    ) -> None:
        """👎 should update feedback to 'down', remove keyboard, and thank."""
        store = ResponseStore(temp_db)
        log_id = await store.store(
            chat_id=124, pillar="content", action="caption",
            user_request="req", response_text="resp",
        )
        bot = _make_bot(sample_settings, mock_llm_client, response_store=store)
        update = _make_callback_update(f"fb:down:{log_id}")

        await bot._handle_feedback_callback(update, MagicMock())

        update.callback_query.answer.assert_awaited_once()
        update.callback_query.edit_message_reply_markup.assert_awaited_once()
        update.callback_query.message.reply_text.assert_awaited()
        record = await store.get(log_id)
        assert record is not None
        assert record.feedback == "down"

    @pytest.mark.asyncio
    async def test_regen_calls_pillar_and_edits_message(
        self, sample_settings, mock_llm_client, temp_db
    ) -> None:
        """🔄 should re-invoke the pillar and edit the message with a new response."""
        store = ResponseStore(temp_db)
        log_id = await store.store(
            chat_id=125, pillar="content", action="caption",
            user_request="Write me a caption", response_text="old caption",
        )
        mock_llm_client.chat_json.return_value = {
            "pillar": "content", "action": "caption",
            "confidence": 0.9, "language_detected": "en",
        }
        bot = _make_bot(sample_settings, mock_llm_client, response_store=store)
        bot.content_pillar.handle = AsyncMock(return_value="brand new caption!")
        update = _make_callback_update(f"fb:regen:{log_id}")

        await bot._handle_feedback_callback(update, MagicMock())

        # The pillar should have been called with the original request
        bot.content_pillar.handle.assert_awaited_once()
        call_kwargs = bot.content_pillar.handle.call_args.kwargs
        assert call_kwargs["user_message"] == "Write me a caption"
        # The message should be edited
        update.callback_query.edit_message_text.assert_awaited_once()
        edited_text = update.callback_query.edit_message_text.call_args[0][0]
        assert "brand new caption!" in edited_text
        # A new keyboard should be attached
        edited_kwargs = update.callback_query.edit_message_text.call_args.kwargs
        assert edited_kwargs.get("reply_markup") is not None

    @pytest.mark.asyncio
    async def test_regen_creates_new_log_entry(
        self, sample_settings, mock_llm_client, temp_db
    ) -> None:
        """🔄 should store the regenerated response as a new feedback_log row."""
        store = ResponseStore(temp_db)
        log_id = await store.store(
            chat_id=126, pillar="content", action="caption",
            user_request="Write a caption", response_text="old",
        )
        bot = _make_bot(sample_settings, mock_llm_client, response_store=store)
        bot.content_pillar.handle = AsyncMock(return_value="new caption")
        update = _make_callback_update(f"fb:regen:{log_id}")

        await bot._handle_feedback_callback(update, MagicMock())

        # A new record should exist (the regenerated one)
        last = await store.get_last_for_chat(126)
        assert last is not None
        assert last.response_text == "new caption"
        assert last.regen_count >= 1

    @pytest.mark.asyncio
    async def test_regen_missing_record_shows_error(
        self, sample_settings, mock_llm_client, temp_db
    ) -> None:
        """🔄 on a non-existent log_id should show an error message."""
        store = ResponseStore(temp_db)
        bot = _make_bot(sample_settings, mock_llm_client, response_store=store)
        update = _make_callback_update("fb:regen:999999")

        await bot._handle_feedback_callback(update, MagicMock())

        update.callback_query.edit_message_text.assert_awaited_once()
        edited_text = update.callback_query.edit_message_text.call_args[0][0]
        assert "couldn't find" in edited_text.lower() or "⚠️" in edited_text

    @pytest.mark.asyncio
    async def test_regen_unknown_pillar_shows_error(
        self, sample_settings, mock_llm_client, temp_db
    ) -> None:
        """🔄 for a record with an unknown pillar should show an error."""
        store = ResponseStore(temp_db)
        log_id = await store.store(
            chat_id=127, pillar="nonexistent_pillar", action="other",
            user_request="req", response_text="resp",
        )
        bot = _make_bot(sample_settings, mock_llm_client, response_store=store)
        update = _make_callback_update(f"fb:regen:{log_id}")

        await bot._handle_feedback_callback(update, MagicMock())

        update.callback_query.edit_message_text.assert_awaited_once()
        edited_text = update.callback_query.edit_message_text.call_args[0][0]
        assert "pillar" in edited_text.lower() or "⚠️" in edited_text

    @pytest.mark.asyncio
    async def test_malformed_callback_data_ignored(
        self, sample_settings, mock_llm_client, temp_db
    ) -> None:
        """Malformed callback data should be ignored without raising."""
        store = ResponseStore(temp_db)
        bot = _make_bot(sample_settings, mock_llm_client, response_store=store)
        update = _make_callback_update("fb:garbage")

        # Should not raise
        await bot._handle_feedback_callback(update, MagicMock())

        # answer() is still called, but no edit should happen
        update.callback_query.answer.assert_awaited_once()
        update.callback_query.edit_message_text.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_callback_when_store_none_shows_unavailable(
        self, sample_settings, mock_llm_client
    ) -> None:
        """When response_store is None, callback should show unavailable message."""
        bot = _make_bot(sample_settings, mock_llm_client, response_store=None)
        update = _make_callback_update("fb:up:1")

        await bot._handle_feedback_callback(update, MagicMock())

        update.callback_query.answer.assert_awaited_once()
        update.callback_query.edit_message_text.assert_awaited_once()
        edited_text = update.callback_query.edit_message_text.call_args[0][0]
        assert "not available" in edited_text.lower() or "⚠️" in edited_text


# ===========================================================================
# 5. Bot: backward compatibility (response_store defaults to None)
# ===========================================================================

class TestBackwardCompatibility:
    """Ensure the feedback system is fully optional and doesn't break the bot."""

    def test_response_store_defaults_none(self, sample_settings, mock_llm_client) -> None:
        """DigitalMateBot should default response_store to None."""
        bot = _make_bot(sample_settings, mock_llm_client, response_store=None)
        assert bot.response_store is None

    @pytest.mark.asyncio
    async def test_pillar_works_without_store(
        self, sample_settings, mock_llm_client
    ) -> None:
        """Pillar routing still works without a response_store."""
        mock_llm_client.chat_json.return_value = {
            "pillar": "content", "action": "caption",
            "confidence": 0.9, "language_detected": "en",
        }
        bot = _make_bot(sample_settings, mock_llm_client, response_store=None)
        bot.content_pillar.handle = AsyncMock(return_value="caption!")

        async def _stream(*a, **kw):
            yield "caption!"
        bot.content_pillar.handle_stream = _stream

        update = _make_update(text="Write me a caption")
        ctx = _make_context()

        await bot._handle_message(update, ctx)

        # With streaming, handle_stream is used (not handle). The response
        # is delivered via edit_text on the placeholder message.
        update.message.reply_text.assert_called()
        assert update._sent_messages, "expected at least one sent message"
        assert update._sent_messages[0].edit_text.called

    @pytest.mark.asyncio
    async def test_general_works_without_store(
        self, sample_settings, mock_llm_client
    ) -> None:
        """General routing still works without a response_store."""
        mock_llm_client.chat_json.return_value = {
            "pillar": "general", "action": "chitchat",
            "confidence": 0.9, "language_detected": "en",
        }
        mock_llm_client.chat.return_value = "Hello!"
        bot = _make_bot(sample_settings, mock_llm_client, response_store=None)
        update = _make_update(text="hello")
        ctx = _make_context()

        await bot._handle_message(update, ctx)

        update.message.reply_text.assert_called()
