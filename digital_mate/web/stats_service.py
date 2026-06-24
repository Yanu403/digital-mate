"""Stats service — reads bot statistics from the SQLite database.

Provides aggregated stats for the dashboard overview page.
"""

from __future__ import annotations

import logging
from typing import Any

from digital_mate.memory.database import AsyncConnection

logger = logging.getLogger(__name__)


class StatsService:
    """Reads aggregated statistics from the bot database."""

    def __init__(self, db: AsyncConnection) -> None:
        self._db = db

    async def close(self) -> None:
        """Close the database connection."""
        await self._db.close()

    async def get_stats(self) -> dict[str, Any]:
        """Get aggregated bot statistics.

        Returns:
            Dict with total_messages, active_users, plans_created,
            feedback_score, and recent_activity.
        """
        try:
            return {
                "total_messages": await self._total_messages(),
                "active_users": await self._active_users(),
                "plans_created": await self._plans_created(),
                "feedback_score": await self._feedback_score(),
                "recent_activity": await self._recent_activity(),
            }
        except Exception as exc:
            logger.warning("Stats query failed: %s", exc)
            return {
                "total_messages": 0,
                "active_users": 0,
                "plans_created": 0,
                "feedback_score": 0.0,
                "recent_activity": [],
            }

    async def _total_messages(self) -> int:
        cursor = await self._db.execute("SELECT COUNT(*) FROM sessions")
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def _active_users(self) -> int:
        cursor = await self._db.execute(
            "SELECT COUNT(DISTINCT chat_id) FROM sessions WHERE created_at > datetime('now', '-7 days')"
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def _plans_created(self) -> int:
        try:
            cursor = await self._db.execute("SELECT COUNT(*) FROM plans")
            row = await cursor.fetchone()
            return row[0] if row else 0
        except Exception:
            return 0

    async def _feedback_score(self) -> float:
        try:
            cursor = await self._db.execute(
                "SELECT COUNT(*) FROM feedback_log WHERE feedback = 'up'"
            )
            result = await cursor.fetchone()
            positive = result[0] if result else 0
            cursor = await self._db.execute(
                "SELECT COUNT(*) FROM feedback_log WHERE feedback IS NOT NULL AND feedback != ''"
            )
            result2 = await cursor.fetchone()
            total = result2[0] if result2 else 0
            if total == 0:
                return 0.0
            return round(positive / total * 100, 1)
        except Exception:
            return 0.0

    async def _recent_activity(self) -> list[dict[str, Any]]:
        try:
            cursor = await self._db.execute(
                """SELECT chat_id, content, created_at
                   FROM sessions
                   WHERE role = 'user'
                   ORDER BY created_at DESC LIMIT 5"""
            )
            rows = await cursor.fetchall()
            return [
                {
                    "chat_id": row[0],
                    "preview": row[1][:100] if row[1] else "",
                    "timestamp": row[2],
                }
                for row in rows
            ]
        except Exception:
            return []
