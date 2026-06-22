"""Auto-calendar subscription and entry-log management.

Stores per-chat opt-in preferences and a log of generated calendar
entries so the bot can avoid duplicate generation and track history.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from typing import Any

from digital_mate.memory.database import AsyncConnection

logger = logging.getLogger(__name__)

# Default scheduling: Monday 09:00
DEFAULT_DAY_OF_WEEK = 0
DEFAULT_HOUR = 9

_VALID_DAYS = set(range(7))      # 0=Monday … 6=Sunday
_VALID_HOURS = set(range(24))    # 0-23


@dataclass
class AutoCalendarSubscription:
    """Represents an auto-calendar subscription for a chat.

    Attributes:
        chat_id: Telegram chat ID.
        enabled: Whether auto-generation is active.
        day_of_week: Day of week to generate (0=Monday … 6=Sunday).
        hour: Hour of the day to generate (0-23, UTC).
        last_run_at: ISO timestamp of the last generation, or None.
        created_at: When the subscription was first created.
        updated_at: When the subscription was last modified.
    """

    chat_id: int
    enabled: bool = True
    day_of_week: int = DEFAULT_DAY_OF_WEEK
    hour: int = DEFAULT_HOUR
    last_run_at: str | None = None
    created_at: str = ""
    updated_at: str = ""


def _row_to_subscription(row: tuple[Any, ...]) -> AutoCalendarSubscription:
    """Convert a database row to an AutoCalendarSubscription.

    Args:
        row: Tuple from SELECT query.

    Returns:
        AutoCalendarSubscription instance.
    """
    return AutoCalendarSubscription(
        chat_id=row[1],
        enabled=bool(row[2]),
        day_of_week=row[3],
        hour=row[4],
        last_run_at=row[5],
        created_at=row[6] or "",
        updated_at=row[7] or "",
    )


@dataclass
class AutoCalendarEntry:
    """A single generated calendar entry.

    Attributes:
        chat_id: Telegram chat ID.
        week_start: ISO date string for the Monday of the target week.
        platform: Target platform (Instagram, TikTok, etc.).
        content_type: Content type (Reel, Carousel, Post, etc.).
        topic: Topic / title of the post.
        caption: Full caption text.
        hashtags: Hashtags string.
        notion_page_id: Notion page ID if pushed, or None.
    """

    chat_id: int
    week_start: str
    platform: str = ""
    content_type: str = ""
    topic: str = ""
    caption: str = ""
    hashtags: str = ""
    notion_page_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary.

        Returns:
            Dict representation of the entry.
        """
        return asdict(self)


class AutoCalendarManager:
    """Manages auto-calendar subscriptions and entry logs in SQLite.

    Each chat_id has at most one subscription (UNIQUE constraint).
    Generated entries are stored for history and deduplication.
    """

    def __init__(self, db: AsyncConnection) -> None:
        """Initialize the manager.

        Args:
            db: Open AsyncConnection.
        """
        self.db = db

    # ------------------------------------------------------------------
    # Subscription CRUD
    # ------------------------------------------------------------------

    async def get_subscription(self, chat_id: int) -> AutoCalendarSubscription | None:
        """Get the auto-calendar subscription for a chat.

        Args:
            chat_id: Telegram chat ID.

        Returns:
            AutoCalendarSubscription if one exists, otherwise None.
        """
        cursor = await self.db.execute(
            """SELECT id, chat_id, enabled, day_of_week, hour, last_run_at,
                      created_at, updated_at
               FROM autocalendar WHERE chat_id = ?""",
            (chat_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_subscription(row)

    async def upsert_subscription(
        self,
        chat_id: int,
        enabled: bool = True,
        day_of_week: int = DEFAULT_DAY_OF_WEEK,
        hour: int = DEFAULT_HOUR,
    ) -> AutoCalendarSubscription:
        """Create or update a subscription.

        Args:
            chat_id: Telegram chat ID.
            enabled: Whether auto-generation is active.
            day_of_week: Day of week (0=Monday … 6=Sunday).
            hour: Hour of the day (0-23).

        Returns:
            The created or updated AutoCalendarSubscription.

        Raises:
            ValueError: If day_of_week or hour is out of range.
        """
        if day_of_week not in _VALID_DAYS:
            raise ValueError(f"day_of_week must be 0-6, got {day_of_week}")
        if hour not in _VALID_HOURS:
            raise ValueError(f"hour must be 0-23, got {hour}")

        existing = await self.get_subscription(chat_id)
        if existing is None:
            await self.db.execute(
                """INSERT INTO autocalendar
                   (chat_id, enabled, day_of_week, hour)
                   VALUES (?, ?, ?, ?)""",
                (chat_id, int(enabled), day_of_week, hour),
            )
        else:
            await self.db.execute(
                """UPDATE autocalendar
                   SET enabled = ?, day_of_week = ?, hour = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE chat_id = ?""",
                (int(enabled), day_of_week, hour, chat_id),
            )
        await self.db.commit()
        logger.info(
            "Auto-calendar subscription for chat %d: enabled=%s day=%d hour=%d",
            chat_id, enabled, day_of_week, hour,
        )
        sub = await self.get_subscription(chat_id)
        assert sub is not None  # just inserted/updated
        return sub

    async def set_enabled(self, chat_id: int, enabled: bool) -> AutoCalendarSubscription | None:
        """Enable or disable auto-calendar for a chat.

        Creates a subscription with default schedule if one doesn't exist.

        Args:
            chat_id: Telegram chat ID.
            enabled: True to enable, False to disable.

        Returns:
            The updated subscription, or None if no subscription exists
            and we're disabling (nothing to disable).
        """
        existing = await self.get_subscription(chat_id)
        if existing is None:
            if not enabled:
                return None
            return await self.upsert_subscription(chat_id, enabled=True)

        await self.db.execute(
            "UPDATE autocalendar SET enabled = ?, updated_at = CURRENT_TIMESTAMP WHERE chat_id = ?",
            (int(enabled), chat_id),
        )
        await self.db.commit()
        return await self.get_subscription(chat_id)

    async def delete_subscription(self, chat_id: int) -> bool:
        """Delete a subscription.

        Args:
            chat_id: Telegram chat ID.

        Returns:
            True if deleted, False if none existed.
        """
        cursor = await self.db.execute(
            "DELETE FROM autocalendar WHERE chat_id = ?",
            (chat_id,),
        )
        await self.db.commit()
        deleted = cursor.rowcount > 0
        if deleted:
            logger.info("Deleted auto-calendar subscription for chat %d", chat_id)
        return deleted

    async def update_last_run(self, chat_id: int) -> None:
        """Set last_run_at to the current timestamp for a chat.

        Args:
            chat_id: Telegram chat ID.
        """
        await self.db.execute(
            "UPDATE autocalendar SET last_run_at = CURRENT_TIMESTAMP WHERE chat_id = ?",
            (chat_id,),
        )
        await self.db.commit()

    async def get_enabled_subscriptions(self) -> list[AutoCalendarSubscription]:
        """Get all enabled subscriptions.

        Returns:
            List of all enabled AutoCalendarSubscription instances.
        """
        cursor = await self.db.execute(
            """SELECT id, chat_id, enabled, day_of_week, hour, last_run_at,
                      created_at, updated_at
               FROM autocalendar WHERE enabled = 1
               ORDER BY chat_id""",
        )
        rows = await cursor.fetchall()
        return [_row_to_subscription(r) for r in rows]

    # ------------------------------------------------------------------
    # Entry log
    # ------------------------------------------------------------------

    async def add_entry(self, entry: AutoCalendarEntry) -> None:
        """Log a generated calendar entry.

        Args:
            entry: AutoCalendarEntry to store.
        """
        await self.db.execute(
            """INSERT INTO autocalendar_entries
               (chat_id, week_start, platform, content_type, topic, caption,
                hashtags, notion_page_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.chat_id,
                entry.week_start,
                entry.platform,
                entry.content_type,
                entry.topic,
                entry.caption,
                entry.hashtags,
                entry.notion_page_id,
            ),
        )
        await self.db.commit()
        logger.debug(
            "Logged auto-calendar entry for chat %d: %s",
            entry.chat_id, entry.topic,
        )

    async def get_entries_for_week(self, chat_id: int, week_start: str) -> list[AutoCalendarEntry]:
        """Get logged entries for a specific chat and week.

        Args:
            chat_id: Telegram chat ID.
            week_start: ISO date string for the Monday of the target week.

        Returns:
            List of AutoCalendarEntry instances for that week.
        """
        cursor = await self.db.execute(
            """SELECT chat_id, week_start, platform, content_type, topic,
                      caption, hashtags, notion_page_id
               FROM autocalendar_entries
               WHERE chat_id = ? AND week_start = ?
               ORDER BY id""",
            (chat_id, week_start),
        )
        rows = await cursor.fetchall()
        return [
            AutoCalendarEntry(
                chat_id=r[0],
                week_start=r[1],
                platform=r[2],
                content_type=r[3],
                topic=r[4],
                caption=r[5],
                hashtags=r[6],
                notion_page_id=r[7],
            )
            for r in rows
        ]

    async def has_entries_for_week(self, chat_id: int, week_start: str) -> bool:
        """Check if entries already exist for a given chat and week.

        Useful for deduplication — avoids generating twice for the same week.

        Args:
            chat_id: Telegram chat ID.
            week_start: ISO date string for the Monday of the target week.

        Returns:
            True if at least one entry exists for that week.
        """
        cursor = await self.db.execute(
            "SELECT COUNT(*) FROM autocalendar_entries WHERE chat_id = ? AND week_start = ?",
            (chat_id, week_start),
        )
        row = await cursor.fetchone()
        return bool(row and row[0] > 0)
