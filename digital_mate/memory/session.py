"""Per-chat session context management.

Stores and retrieves the last N conversation turns for each Telegram chat.
"""

from __future__ import annotations

import logging

from digital_mate.memory.database import AsyncConnection

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages per-chat conversation context stored in SQLite.

    Maintains a sliding window of the most recent messages per chat_id.
    """

    def __init__(self, db: AsyncConnection, max_turns: int = 10) -> None:
        """Initialize the session manager.

        Args:
            db: Open AsyncConnection.
            max_turns: Maximum number of conversation turns to retain.
        """
        self.db = db
        self.max_turns = max_turns

    async def add_message(self, chat_id: int, role: str, content: str) -> None:
        """Add a message to the session context for a chat.

        Args:
            chat_id: Telegram chat ID.
            role: Message role ('user' or 'assistant').
            content: Message text content.
        """
        await self.db.execute(
            "INSERT INTO sessions (chat_id, role, content) VALUES (?, ?, ?)",
            (chat_id, role, content),
        )
        await self.db.commit()

        # Prune old messages beyond max_turns * 2 (user + assistant per turn)
        max_messages = self.max_turns * 2
        await self.db.execute(
            """DELETE FROM sessions WHERE chat_id = ? AND id NOT IN (
                SELECT id FROM sessions WHERE chat_id = ?
                ORDER BY id DESC LIMIT ?
            )""",
            (chat_id, chat_id, max_messages),
        )
        await self.db.commit()
        logger.debug("Added %s message for chat %d", role, chat_id)

    async def get_context(self, chat_id: int) -> list[dict[str, str]]:
        """Get the recent conversation context for a chat.

        Args:
            chat_id: Telegram chat ID.

        Returns:
            List of message dicts with 'role' and 'content' keys,
            ordered chronologically (oldest first).
        """
        cursor = await self.db.execute(
            """SELECT role, content FROM sessions
            WHERE chat_id = ?
            ORDER BY id DESC LIMIT ?""",
            (chat_id, self.max_turns * 2),
        )
        rows = await cursor.fetchall()
        # Reverse to get chronological order
        return [{"role": row[0], "content": row[1]} for row in reversed(rows)]

    async def clear(self, chat_id: int) -> int:
        """Clear all session context for a chat.

        Args:
            chat_id: Telegram chat ID.

        Returns:
            Number of messages deleted.
        """
        cursor = await self.db.execute(
            "SELECT COUNT(*) FROM sessions WHERE chat_id = ?",
            (chat_id,),
        )
        row = await cursor.fetchone()
        count = row[0] if row else 0

        await self.db.execute(
            "DELETE FROM sessions WHERE chat_id = ?",
            (chat_id,),
        )
        await self.db.commit()
        logger.info("Cleared %d messages for chat %d", count, chat_id)
        return count
