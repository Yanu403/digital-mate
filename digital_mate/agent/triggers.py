"""Proactive trigger engine for user notifications.

Evaluates conditions and fires proactive notifications such as
weekly trend updates, content posting reminders, and campaign
performance alerts. Triggers are lightweight — conditions are
checked first, and LLM calls only happen when a trigger fires.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from digital_mate.memory.database import AsyncConnection

logger = logging.getLogger(__name__)

# Trigger definitions
TRIGGERS: dict[str, dict[str, Any]] = {
    "weekly_trends": {
        "interval_hours": 168,  # 7 days
        "condition": "has_brand_profile",
        "action": "search_and_suggest",
        "description": "Weekly industry trend digest",
    },
    "content_reminder": {
        "interval_hours": 72,  # 3 days
        "condition": "no_recent_content",
        "action": "remind_posting",
        "description": "Content posting reminder",
    },
    "campaign_check": {
        "interval_hours": 168,  # 7 days
        "condition": "has_active_campaign",
        "action": "suggest_report",
        "description": "Campaign performance check",
    },
}


class TriggerEngine:
    """Evaluates proactive triggers and manages trigger state.

    Checks user conditions (brand profile, recent activity, etc.)
    and determines which triggers should fire based on last-fired
    timestamps stored in the trigger_log table.

    Args:
        db: Open AsyncConnection to the SQLite database.
    """

    def __init__(self, db: AsyncConnection) -> None:
        self.db = db

    async def check_triggers(
        self,
        chat_id: int,
        has_brand_profile: bool = False,
        has_active_campaign: bool = False,
        recent_content_count: int = 0,
    ) -> list[dict[str, Any]]:
        """Check which triggers should fire for a user.

        Evaluates each trigger's condition and checks if enough time
        has passed since the last firing.

        Args:
            chat_id: Telegram chat ID.
            has_brand_profile: Whether user has a brand profile set up.
            has_active_campaign: Whether user has an active campaign.
            recent_content_count: Number of content pieces in last 3 days.

        Returns:
            List of trigger dicts that should fire. Each contains:
            trigger_name, description, action.
        """
        now = datetime.utcnow()
        due_triggers: list[dict[str, Any]] = []

        for trigger_name, trigger_def in TRIGGERS.items():
            # Check condition
            if not self._check_condition(
                trigger_def["condition"],
                has_brand_profile=has_brand_profile,
                has_active_campaign=has_active_campaign,
                recent_content_count=recent_content_count,
            ):
                continue

            # Check if enough time has passed since last firing
            last_fired = await self._get_last_fired(chat_id, trigger_name)
            interval = timedelta(hours=trigger_def["interval_hours"])

            if last_fired is None or (now - last_fired) >= interval:
                due_triggers.append({
                    "trigger_name": trigger_name,
                    "description": trigger_def["description"],
                    "action": trigger_def["action"],
                })

        return due_triggers

    async def record_trigger(
        self,
        chat_id: int,
        trigger_name: str,
        result_summary: str = "",
    ) -> None:
        """Record that a trigger was fired for a user.

        Args:
            chat_id: Telegram chat ID.
            trigger_name: Name of the trigger that fired.
            result_summary: Optional summary of what was sent.
        """
        await self.db.execute(
            """INSERT INTO trigger_log (chat_id, trigger_name, last_fired_at, result_summary)
               VALUES (?, ?, CURRENT_TIMESTAMP, ?)
               ON CONFLICT(chat_id, trigger_name)
               DO UPDATE SET last_fired_at = CURRENT_TIMESTAMP,
                             result_summary = excluded.result_summary""",
            (chat_id, trigger_name, result_summary),
        )
        await self.db.commit()
        logger.info("Recorded trigger %s for chat %d", trigger_name, chat_id)

    def _check_condition(
        self,
        condition: str,
        *,
        has_brand_profile: bool = False,
        has_active_campaign: bool = False,
        recent_content_count: int = 0,
    ) -> bool:
        """Evaluate a trigger condition.

        Args:
            condition: Condition name to check.
            has_brand_profile: Whether user has brand profile.
            has_active_campaign: Whether user has active campaign.
            recent_content_count: Content pieces in recent period.

        Returns:
            True if the condition is met.
        """
        if condition == "has_brand_profile":
            return has_brand_profile
        elif condition == "no_recent_content":
            return has_brand_profile and recent_content_count == 0
        elif condition == "has_active_campaign":
            return has_brand_profile and has_active_campaign
        return False

    async def _get_last_fired(
        self, chat_id: int, trigger_name: str
    ) -> datetime | None:
        """Get the last time a trigger was fired for a user.

        Args:
            chat_id: Telegram chat ID.
            trigger_name: Name of the trigger.

        Returns:
            Datetime of last firing, or None if never fired.
        """
        cursor = await self.db.execute(
            "SELECT last_fired_at FROM trigger_log WHERE chat_id = ? AND trigger_name = ?",
            (chat_id, trigger_name),
        )
        row = await cursor.fetchone()
        if row is None or row[0] is None:
            return None
        try:
            return datetime.fromisoformat(row[0])
        except (ValueError, TypeError):
            return None
