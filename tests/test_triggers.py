"""Tests for the proactive trigger engine.

Covers trigger definitions, condition checking, interval logic,
and the trigger_log persistence.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
import pytest_asyncio

from digital_mate.agent.triggers import TriggerEngine, TRIGGERS
from digital_mate.memory.database import init_memory_db, AsyncConnection


class TestTriggerDefinitions:
    """Verify trigger definitions are correctly configured."""

    def test_weekly_trends_trigger(self) -> None:
        trigger = TRIGGERS["weekly_trends"]
        assert trigger["interval_hours"] == 168
        assert trigger["condition"] == "has_brand_profile"
        assert trigger["action"] == "search_and_suggest"

    def test_content_reminder_trigger(self) -> None:
        trigger = TRIGGERS["content_reminder"]
        assert trigger["interval_hours"] == 72
        assert trigger["condition"] == "no_recent_content"

    def test_campaign_check_trigger(self) -> None:
        trigger = TRIGGERS["campaign_check"]
        assert trigger["interval_hours"] == 168
        assert trigger["condition"] == "has_active_campaign"

    def test_all_triggers_have_required_keys(self) -> None:
        for name, trigger in TRIGGERS.items():
            assert "interval_hours" in trigger, f"{name} missing interval_hours"
            assert "condition" in trigger, f"{name} missing condition"
            assert "action" in trigger, f"{name} missing action"
            assert "description" in trigger, f"{name} missing description"


@pytest_asyncio.fixture
async def db() -> AsyncConnection:
    conn = await init_memory_db()
    yield conn
    await conn.close()


class TestTriggerEngine:
    """Test the TriggerEngine.check_triggers() method."""

    async def test_no_triggers_without_brand_profile(self, db: AsyncConnection) -> None:
        engine = TriggerEngine(db)
        due = await engine.check_triggers(
            chat_id=123,
            has_brand_profile=False,
        )
        assert due == []

    async def test_weekly_trends_fires_for_brand_profile(self, db: AsyncConnection) -> None:
        engine = TriggerEngine(db)
        due = await engine.check_triggers(
            chat_id=123,
            has_brand_profile=True,
        )
        names = [t["trigger_name"] for t in due]
        assert "weekly_trends" in names

    async def test_content_reminder_fires_when_no_recent_content(self, db: AsyncConnection) -> None:
        engine = TriggerEngine(db)
        due = await engine.check_triggers(
            chat_id=123,
            has_brand_profile=True,
            recent_content_count=0,
        )
        names = [t["trigger_name"] for t in due]
        assert "content_reminder" in names

    async def test_content_reminder_no_fire_with_recent_content(self, db: AsyncConnection) -> None:
        engine = TriggerEngine(db)
        due = await engine.check_triggers(
            chat_id=123,
            has_brand_profile=True,
            recent_content_count=5,
        )
        names = [t["trigger_name"] for t in due]
        assert "content_reminder" not in names

    async def test_campaign_check_fires_with_active_campaign(self, db: AsyncConnection) -> None:
        engine = TriggerEngine(db)
        due = await engine.check_triggers(
            chat_id=123,
            has_brand_profile=True,
            has_active_campaign=True,
        )
        names = [t["trigger_name"] for t in due]
        assert "campaign_check" in names

    async def test_campaign_check_no_fire_without_campaign(self, db: AsyncConnection) -> None:
        engine = TriggerEngine(db)
        due = await engine.check_triggers(
            chat_id=123,
            has_brand_profile=True,
            has_active_campaign=False,
        )
        names = [t["trigger_name"] for t in due]
        assert "campaign_check" not in names

    async def test_no_duplicate_triggers_after_firing(self, db: AsyncConnection) -> None:
        engine = TriggerEngine(db)
        # Fire trigger
        await engine.record_trigger(123, "weekly_trends", "sent digest")
        # Should not fire again immediately
        due = await engine.check_triggers(
            chat_id=123,
            has_brand_profile=True,
        )
        names = [t["trigger_name"] for t in due]
        assert "weekly_trends" not in names

    async def test_trigger_fires_after_interval(self, db: AsyncConnection) -> None:
        engine = TriggerEngine(db)
        # Record a trigger that fired long ago
        old_time = (datetime.utcnow() - timedelta(hours=200)).isoformat()
        await db.execute(
            """INSERT INTO trigger_log (chat_id, trigger_name, last_fired_at, result_summary)
               VALUES (?, ?, ?, ?)""",
            (123, "weekly_trends", old_time, "old digest"),
        )
        await db.commit()

        due = await engine.check_triggers(
            chat_id=123,
            has_brand_profile=True,
        )
        names = [t["trigger_name"] for t in due]
        assert "weekly_trends" in names

    async def test_different_users_independent(self, db: AsyncConnection) -> None:
        engine = TriggerEngine(db)
        await engine.record_trigger(123, "weekly_trends", "sent")

        # User 456 should still get the trigger
        due = await engine.check_triggers(
            chat_id=456,
            has_brand_profile=True,
        )
        names = [t["trigger_name"] for t in due]
        assert "weekly_trends" in names


class TestRecordTrigger:
    """Test the TriggerEngine.record_trigger() method."""

    async def test_record_creates_entry(self, db: AsyncConnection) -> None:
        engine = TriggerEngine(db)
        await engine.record_trigger(123, "weekly_trends", "sent digest")

        cursor = await db.execute(
            "SELECT trigger_name, result_summary FROM trigger_log WHERE chat_id = ?",
            (123,),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "weekly_trends"
        assert row[1] == "sent digest"

    async def test_record_upserts_on_duplicate(self, db: AsyncConnection) -> None:
        engine = TriggerEngine(db)
        await engine.record_trigger(123, "weekly_trends", "first")
        await engine.record_trigger(123, "weekly_trends", "second")

        cursor = await db.execute(
            "SELECT COUNT(*) FROM trigger_log WHERE chat_id = ? AND trigger_name = ?",
            (123, "weekly_trends"),
        )
        row = await cursor.fetchone()
        assert row[0] == 1  # Only one row, not two

        cursor = await db.execute(
            "SELECT result_summary FROM trigger_log WHERE chat_id = ? AND trigger_name = ?",
            (123, "weekly_trends"),
        )
        row = await cursor.fetchone()
        assert row[0] == "second"  # Updated to latest
