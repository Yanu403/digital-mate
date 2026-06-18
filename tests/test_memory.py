"""Tests for digital_mate.memory module (session, brand_profile, database)."""

import pytest
import pytest_asyncio
from digital_mate.memory.session import SessionManager
from digital_mate.memory.brand_profile import BrandProfile, BrandProfileManager
from digital_mate.memory.database import init_memory_db, AsyncConnection


class TestSessionManager:
    """Test session context management."""

    @pytest.mark.asyncio
    async def test_add_and_get_messages(self, temp_db) -> None:
        """Test adding messages and retrieving context."""
        sm = SessionManager(temp_db, max_turns=5)
        chat_id = 1001

        await sm.add_message(chat_id, "user", "Hello!")
        await sm.add_message(chat_id, "assistant", "Hi there!")

        context = await sm.get_context(chat_id)
        assert len(context) == 2
        assert context[0]["role"] == "user"
        assert context[0]["content"] == "Hello!"
        assert context[1]["role"] == "assistant"
        assert context[1]["content"] == "Hi there!"

    @pytest.mark.asyncio
    async def test_context_window_limit(self, temp_db) -> None:
        """Test that old messages are pruned when exceeding max_turns."""
        sm = SessionManager(temp_db, max_turns=2)
        chat_id = 1002

        # Add 3 turns (6 messages) — only 2 turns (4 messages) should remain
        for i in range(3):
            await sm.add_message(chat_id, "user", f"Question {i}")
            await sm.add_message(chat_id, "assistant", f"Answer {i}")

        context = await sm.get_context(chat_id)
        assert len(context) == 4  # 2 turns * 2 messages
        # Should be the most recent
        assert context[-1]["content"] == "Answer 2"
        assert context[0]["content"] == "Question 1"

    @pytest.mark.asyncio
    async def test_clear_session(self, temp_db) -> None:
        """Test clearing session context."""
        sm = SessionManager(temp_db, max_turns=10)
        chat_id = 1003

        await sm.add_message(chat_id, "user", "test")
        await sm.add_message(chat_id, "assistant", "response")

        count = await sm.clear(chat_id)
        assert count == 2

        context = await sm.get_context(chat_id)
        assert len(context) == 0

    @pytest.mark.asyncio
    async def test_separate_chats(self, temp_db) -> None:
        """Test that different chat_ids have separate contexts."""
        sm = SessionManager(temp_db, max_turns=10)

        await sm.add_message(2001, "user", "Chat 1 message")
        await sm.add_message(2002, "user", "Chat 2 message")

        ctx1 = await sm.get_context(2001)
        ctx2 = await sm.get_context(2002)

        assert len(ctx1) == 1
        assert ctx1[0]["content"] == "Chat 1 message"
        assert len(ctx2) == 1
        assert ctx2[0]["content"] == "Chat 2 message"

    @pytest.mark.asyncio
    async def test_empty_context(self, temp_db) -> None:
        """Test getting context for a chat with no messages."""
        sm = SessionManager(temp_db, max_turns=10)
        context = await sm.get_context(9999)
        assert context == []


class TestBrandProfileManager:
    """Test brand profile CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_profile(self, temp_db, sample_brand_profile) -> None:
        """Test creating a new brand profile."""
        bm = BrandProfileManager(temp_db)
        profile = await bm.create(sample_brand_profile)

        assert profile.chat_id == sample_brand_profile.chat_id
        assert profile.name == "TestBrand Coffee"

    @pytest.mark.asyncio
    async def test_get_profile(self, temp_db, sample_brand_profile) -> None:
        """Test retrieving a brand profile."""
        bm = BrandProfileManager(temp_db)
        await bm.create(sample_brand_profile)

        retrieved = await bm.get(sample_brand_profile.chat_id)
        assert retrieved is not None
        assert retrieved.name == "TestBrand Coffee"
        assert retrieved.industry == "Food & Beverage"
        assert retrieved.audience == sample_brand_profile.audience

    @pytest.mark.asyncio
    async def test_get_nonexistent_profile(self, temp_db) -> None:
        """Test retrieving a profile that doesn't exist."""
        bm = BrandProfileManager(temp_db)
        result = await bm.get(99999)
        assert result is None

    @pytest.mark.asyncio
    async def test_update_profile(self, temp_db, sample_brand_profile) -> None:
        """Test updating a brand profile."""
        bm = BrandProfileManager(temp_db)
        await bm.create(sample_brand_profile)

        updated = BrandProfile(
            chat_id=sample_brand_profile.chat_id,
            name="Updated Brand",
            industry="Technology",
            audience="Developers",
            tone="Technical and precise",
            products="Software tools",
            hashtags="#DevTools",
            competitors="None",
        )
        result = await bm.update(updated)
        assert result.name == "Updated Brand"
        assert result.industry == "Technology"

        # Verify persistence
        retrieved = await bm.get(sample_brand_profile.chat_id)
        assert retrieved.name == "Updated Brand"

    @pytest.mark.asyncio
    async def test_delete_profile(self, temp_db, sample_brand_profile) -> None:
        """Test deleting a brand profile."""
        bm = BrandProfileManager(temp_db)
        await bm.create(sample_brand_profile)

        deleted = await bm.delete(sample_brand_profile.chat_id)
        assert deleted is True

        # Verify deletion
        result = await bm.get(sample_brand_profile.chat_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, temp_db) -> None:
        """Test deleting a profile that doesn't exist."""
        bm = BrandProfileManager(temp_db)
        deleted = await bm.delete(99999)
        assert deleted is False

    @pytest.mark.asyncio
    async def test_create_duplicate_raises(self, temp_db, sample_brand_profile) -> None:
        """Test that creating a duplicate profile raises ValueError."""
        bm = BrandProfileManager(temp_db)
        await bm.create(sample_brand_profile)

        with pytest.raises(ValueError, match="already exists"):
            await bm.create(sample_brand_profile)

    @pytest.mark.asyncio
    async def test_update_nonexistent_raises(self, temp_db) -> None:
        """Test that updating a nonexistent profile raises ValueError."""
        bm = BrandProfileManager(temp_db)
        profile = BrandProfile(chat_id=99999, name="Ghost")

        with pytest.raises(ValueError, match="No brand profile"):
            await bm.update(profile)

    @pytest.mark.asyncio
    async def test_create_or_update(self, temp_db, sample_brand_profile) -> None:
        """Test create_or_upsert behavior."""
        bm = BrandProfileManager(temp_db)

        # First call creates
        result = await bm.create_or_update(sample_brand_profile)
        assert result.name == "TestBrand Coffee"

        # Second call updates
        updated = BrandProfile(
            chat_id=sample_brand_profile.chat_id,
            name="Updated Brand",
            industry="Tech",
        )
        result = await bm.create_or_update(updated)
        assert result.name == "Updated Brand"

    @pytest.mark.asyncio
    async def test_brand_profile_to_dict(self, sample_brand_profile) -> None:
        """Test BrandProfile to_dict method."""
        d = sample_brand_profile.to_dict()
        assert isinstance(d, dict)
        assert d["name"] == "TestBrand Coffee"
        assert d["chat_id"] == 123456789


class TestSessionCleanup:
    """Test session expiry / cleanup_old_sessions."""

    @pytest.mark.asyncio
    async def test_cleanup_deletes_old_messages(self, temp_db) -> None:
        """Messages older than max_age_days should be deleted."""
        # Insert messages with an old created_at
        await temp_db.execute(
            "INSERT INTO sessions (chat_id, role, content, created_at) VALUES (?, ?, ?, datetime('now', '-10 days'))",
            (9001, "user", "old message 1"),
        )
        await temp_db.execute(
            "INSERT INTO sessions (chat_id, role, content, created_at) VALUES (?, ?, ?, datetime('now', '-8 days'))",
            (9001, "assistant", "old message 2"),
        )
        await temp_db.commit()

        count = await SessionManager.cleanup_old_sessions(temp_db, max_age_days=7)
        assert count == 2

        # Verify they're gone
        cursor = await temp_db.execute("SELECT COUNT(*) FROM sessions WHERE chat_id = 9001")
        row = await cursor.fetchone()
        assert row[0] == 0

    @pytest.mark.asyncio
    async def test_cleanup_preserves_recent_messages(self, temp_db) -> None:
        """Recent messages should NOT be deleted."""
        # Insert a recent message
        await temp_db.execute(
            "INSERT INTO sessions (chat_id, role, content) VALUES (?, ?, ?)",
            (9002, "user", "recent message"),
        )
        # Insert an old message
        await temp_db.execute(
            "INSERT INTO sessions (chat_id, role, content, created_at) VALUES (?, ?, ?, datetime('now', '-10 days'))",
            (9002, "user", "old message"),
        )
        await temp_db.commit()

        count = await SessionManager.cleanup_old_sessions(temp_db, max_age_days=7)
        assert count == 1

        # Recent message should still be there
        cursor = await temp_db.execute(
            "SELECT content FROM sessions WHERE chat_id = 9002"
        )
        rows = await cursor.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "recent message"

    @pytest.mark.asyncio
    async def test_cleanup_returns_zero_when_nothing_to_delete(self, temp_db) -> None:
        """Should return 0 when there are no old messages."""
        count = await SessionManager.cleanup_old_sessions(temp_db, max_age_days=7)
        assert count == 0
