"""Tests for digital_mate.memory.autocalendar module.

Covers AutoCalendarManager CRUD operations, subscription enabling/disabling,
entry logging, and edge cases.
"""

from __future__ import annotations

import pytest
from dataclasses import asdict

from digital_mate.memory.autocalendar import (
    AutoCalendarManager,
    AutoCalendarSubscription,
    AutoCalendarEntry,
)


class TestAutoCalendarSubscription:
    """Test the AutoCalendarSubscription dataclass."""

    def test_defaults(self) -> None:
        """Test default values."""
        sub = AutoCalendarSubscription(chat_id=456)
        assert sub.enabled is True
        assert sub.day_of_week == 0
        assert sub.hour == 9
        assert sub.last_run_at is None

    def test_custom_values(self) -> None:
        """Test custom values."""
        sub = AutoCalendarSubscription(
            chat_id=123, enabled=False, day_of_week=3, hour=14,
        )
        assert sub.chat_id == 123
        assert sub.enabled is False
        assert sub.day_of_week == 3
        assert sub.hour == 14


class TestAutoCalendarManagerUpsert:
    """Test create / upsert operations."""

    @pytest.mark.asyncio
    async def test_upsert_creates_subscription(self, temp_db) -> None:
        """Upsert for a new chat should create a subscription."""
        mgr = AutoCalendarManager(temp_db)
        sub = await mgr.upsert_subscription(chat_id=100, day_of_week=2, hour=14)
        assert sub.chat_id == 100
        assert sub.enabled is True
        assert sub.day_of_week == 2
        assert sub.hour == 14
        assert sub.last_run_at is None

    @pytest.mark.asyncio
    async def test_upsert_updates_existing(self, temp_db) -> None:
        """Upsert on existing subscription should update it."""
        mgr = AutoCalendarManager(temp_db)
        await mgr.upsert_subscription(chat_id=200, day_of_week=0, hour=9)
        sub = await mgr.upsert_subscription(chat_id=200, day_of_week=3, hour=10)
        assert sub.day_of_week == 3
        assert sub.hour == 10

    @pytest.mark.asyncio
    async def test_upsert_defaults(self, temp_db) -> None:
        """Upsert with defaults should use Monday 09:00."""
        mgr = AutoCalendarManager(temp_db)
        sub = await mgr.upsert_subscription(chat_id=300)
        assert sub.day_of_week == 0
        assert sub.hour == 9

    @pytest.mark.asyncio
    async def test_upsert_invalid_day(self, temp_db) -> None:
        """Invalid day_of_week should raise ValueError."""
        mgr = AutoCalendarManager(temp_db)
        with pytest.raises(ValueError):
            await mgr.upsert_subscription(chat_id=301, day_of_week=7)

    @pytest.mark.asyncio
    async def test_upsert_invalid_hour(self, temp_db) -> None:
        """Invalid hour should raise ValueError."""
        mgr = AutoCalendarManager(temp_db)
        with pytest.raises(ValueError):
            await mgr.upsert_subscription(chat_id=302, hour=24)


class TestAutoCalendarManagerSetEnabled:
    """Test set_enabled operations."""

    @pytest.mark.asyncio
    async def test_enable_creates_subscription(self, temp_db) -> None:
        """set_enabled(True) for new chat should create subscription."""
        mgr = AutoCalendarManager(temp_db)
        sub = await mgr.set_enabled(chat_id=400, enabled=True)
        assert sub is not None
        assert sub.enabled is True

    @pytest.mark.asyncio
    async def test_disable_existing(self, temp_db) -> None:
        """set_enabled(False) on existing subscription should disable it."""
        mgr = AutoCalendarManager(temp_db)
        await mgr.upsert_subscription(chat_id=500)
        sub = await mgr.set_enabled(chat_id=500, enabled=False)
        assert sub is not None
        assert sub.enabled is False

    @pytest.mark.asyncio
    async def test_disable_nonexistent(self, temp_db) -> None:
        """set_enabled(False) on non-existent subscription should return None."""
        mgr = AutoCalendarManager(temp_db)
        result = await mgr.set_enabled(chat_id=999, enabled=False)
        assert result is None


class TestAutoCalendarManagerGet:
    """Test get_subscription operations."""

    @pytest.mark.asyncio
    async def test_get_existing(self, temp_db) -> None:
        """Get should return the subscription."""
        mgr = AutoCalendarManager(temp_db)
        await mgr.upsert_subscription(chat_id=600, day_of_week=5, hour=15)
        sub = await mgr.get_subscription(chat_id=600)
        assert sub is not None
        assert sub.chat_id == 600
        assert sub.day_of_week == 5
        assert sub.hour == 15

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, temp_db) -> None:
        """Get for non-existent chat should return None."""
        mgr = AutoCalendarManager(temp_db)
        sub = await mgr.get_subscription(chat_id=777)
        assert sub is None

    @pytest.mark.asyncio
    async def test_get_disabled(self, temp_db) -> None:
        """Get should still return disabled subscriptions."""
        mgr = AutoCalendarManager(temp_db)
        await mgr.upsert_subscription(chat_id=800)
        await mgr.set_enabled(chat_id=800, enabled=False)
        sub = await mgr.get_subscription(chat_id=800)
        assert sub is not None
        assert sub.enabled is False


class TestAutoCalendarManagerDelete:
    """Test delete_subscription."""

    @pytest.mark.asyncio
    async def test_delete_existing(self, temp_db) -> None:
        """Delete should remove the subscription."""
        mgr = AutoCalendarManager(temp_db)
        await mgr.upsert_subscription(chat_id=900)
        result = await mgr.delete_subscription(chat_id=900)
        assert result is True
        sub = await mgr.get_subscription(chat_id=900)
        assert sub is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, temp_db) -> None:
        """Delete on non-existent should return False."""
        mgr = AutoCalendarManager(temp_db)
        result = await mgr.delete_subscription(chat_id=999)
        assert result is False


class TestAutoCalendarManagerGetEnabled:
    """Test get_enabled_subscriptions."""

    @pytest.mark.asyncio
    async def test_get_enabled_returns_only_enabled(self, temp_db) -> None:
        """Should return only enabled subscriptions."""
        mgr = AutoCalendarManager(temp_db)
        await mgr.upsert_subscription(chat_id=101)
        await mgr.upsert_subscription(chat_id=102)
        await mgr.upsert_subscription(chat_id=103)
        await mgr.set_enabled(chat_id=102, enabled=False)

        enabled = await mgr.get_enabled_subscriptions()
        assert len(enabled) == 2
        chat_ids = {s.chat_id for s in enabled}
        assert chat_ids == {101, 103}

    @pytest.mark.asyncio
    async def test_get_enabled_empty(self, temp_db) -> None:
        """Should return empty list when no subscriptions exist."""
        mgr = AutoCalendarManager(temp_db)
        enabled = await mgr.get_enabled_subscriptions()
        assert enabled == []


class TestAutoCalendarManagerUpdateLastRun:
    """Test update_last_run."""

    @pytest.mark.asyncio
    async def test_update_last_run(self, temp_db) -> None:
        """update_last_run should set last_run_at."""
        mgr = AutoCalendarManager(temp_db)
        await mgr.upsert_subscription(chat_id=700)
        await mgr.update_last_run(chat_id=700)
        sub = await mgr.get_subscription(chat_id=700)
        assert sub is not None
        assert sub.last_run_at is not None


class TestAutoCalendarManagerEntries:
    """Test add_entry and get_entries_for_week."""

    @pytest.mark.asyncio
    async def test_add_and_get_entries(self, temp_db) -> None:
        """Added entries should be retrievable."""
        mgr = AutoCalendarManager(temp_db)
        week = "2024-01-15"

        entry = AutoCalendarEntry(
            chat_id=900,
            week_start=week,
            platform="Instagram",
            content_type="Reel",
            topic="Morning routine",
            caption="Start your day right!",
            hashtags="#morning #routine",
            notion_page_id="page-123",
        )
        await mgr.add_entry(entry)

        entries = await mgr.get_entries_for_week(chat_id=900, week_start=week)
        assert len(entries) == 1
        e = entries[0]
        assert e.platform == "Instagram"
        assert e.content_type == "Reel"
        assert e.topic == "Morning routine"
        assert e.caption == "Start your day right!"
        assert e.hashtags == "#morning #routine"
        assert e.notion_page_id == "page-123"

    @pytest.mark.asyncio
    async def test_get_entries_empty(self, temp_db) -> None:
        """Get entries for a week with no entries should return empty list."""
        mgr = AutoCalendarManager(temp_db)
        entries = await mgr.get_entries_for_week(chat_id=999, week_start="2024-01-15")
        assert entries == []

    @pytest.mark.asyncio
    async def test_multiple_entries_same_week(self, temp_db) -> None:
        """Multiple entries in the same week should all be returned."""
        mgr = AutoCalendarManager(temp_db)
        week = "2024-01-15"

        for i in range(5):
            await mgr.add_entry(AutoCalendarEntry(
                chat_id=910, week_start=week, platform="Instagram",
                content_type="Post", topic=f"Topic {i}", caption=f"Caption {i}",
                hashtags="#tag",
            ))

        entries = await mgr.get_entries_for_week(chat_id=910, week_start=week)
        assert len(entries) == 5

    @pytest.mark.asyncio
    async def test_entries_isolated_per_chat(self, temp_db) -> None:
        """Entries for one chat should not appear for another."""
        mgr = AutoCalendarManager(temp_db)
        week = "2024-01-15"

        await mgr.add_entry(AutoCalendarEntry(
            chat_id=920, week_start=week, platform="IG", content_type="Post", topic="A",
        ))
        await mgr.add_entry(AutoCalendarEntry(
            chat_id=921, week_start=week, platform="IG", content_type="Post", topic="B",
        ))

        e1 = await mgr.get_entries_for_week(chat_id=920, week_start=week)
        e2 = await mgr.get_entries_for_week(chat_id=921, week_start=week)
        assert len(e1) == 1
        assert len(e2) == 1
        assert e1[0].topic == "A"
        assert e2[0].topic == "B"

    @pytest.mark.asyncio
    async def test_has_entries_for_week(self, temp_db) -> None:
        """has_entries_for_week should correctly detect existing entries."""
        mgr = AutoCalendarManager(temp_db)
        week = "2024-01-15"

        assert await mgr.has_entries_for_week(chat_id=930, week_start=week) is False

        await mgr.add_entry(AutoCalendarEntry(
            chat_id=930, week_start=week, platform="IG", content_type="Post", topic="X",
        ))
        assert await mgr.has_entries_for_week(chat_id=930, week_start=week) is True


class TestAutoCalendarEntry:
    """Test the AutoCalendarEntry dataclass."""

    def test_to_dict(self) -> None:
        """to_dict should return all fields."""
        entry = AutoCalendarEntry(
            chat_id=123, week_start="2024-01-15", platform="Instagram",
            content_type="Reel", topic="Test", caption="Hello",
            hashtags="#test", notion_page_id="page-1",
        )
        d = entry.to_dict()
        assert d["chat_id"] == 123
        assert d["platform"] == "Instagram"
        assert d["topic"] == "Test"
        assert d["notion_page_id"] == "page-1"

    def test_defaults(self) -> None:
        """Default values should be set."""
        entry = AutoCalendarEntry(chat_id=456, week_start="2024-01-15")
        assert entry.platform == ""
        assert entry.content_type == ""
        assert entry.topic == ""
        assert entry.caption == ""
        assert entry.hashtags == ""
        assert entry.notion_page_id is None
