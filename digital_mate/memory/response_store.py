"""Persistent storage for the last pillar response per chat.

Stores each generated pillar response (along with the original user request,
pillar name, and action) so that:

* Inline feedback buttons (👍 / 👎 / 🔄) can reference a stable ``log_id``.
* The 🔄 regenerate button can re-invoke the pillar with the original request.

Feedback buttons are *only* attached to pillar responses
(content / strategy / research / analytics). General chitchat, help, and brand
messages are deliberately **not** logged here.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import Any

from digital_mate.memory.database import AsyncConnection

logger = logging.getLogger(__name__)


@dataclass
class ResponseRecord:
    """A stored pillar response awaiting or carrying user feedback.

    Attributes:
        log_id: Primary key of the ``feedback_log`` row.
        chat_id: Telegram chat ID the response belongs to.
        pillar: Pillar name (content / strategy / research / analytics).
        action: Router action that produced the response.
        user_request: The original (sanitized) user message.
        response_text: The generated response text.
        feedback: User feedback if any (``"up"``, ``"down"``, or ``None``).
        regen_count: How many times the response has been regenerated.
    """

    log_id: int
    chat_id: int
    pillar: str
    action: str
    user_request: str
    response_text: str
    feedback: str | None = None
    regen_count: int = 0


class ResponseStore:
    """Manages persistence of pillar responses and their feedback.

    The store is intentionally **optional** — the bot accepts ``response_store``
    as ``None`` and simply skips feedback logging when it is not configured.
    This keeps existing tests and lightweight deployments working unchanged.
    """

    def __init__(self, db: AsyncConnection) -> None:
        """Initialize the response store.

        Args:
            db: Open AsyncConnection to the SQLite database.
        """
        self.db = db

    async def store(
        self,
        chat_id: int,
        pillar: str,
        action: str,
        user_request: str,
        response_text: str,
        regen_count: int = 0,
    ) -> int:
        """Persist a new pillar response and return its log_id.

        Args:
            chat_id: Telegram chat ID.
            pillar: Pillar name (content/strategy/research/analytics).
            action: Router action.
            user_request: The original sanitized user message.
            response_text: The generated response text.
            regen_count: Regeneration counter (0 for the original response,
                incremented for each 🔄 regeneration).

        Returns:
            The ``log_id`` (primary key) of the newly inserted row.
        """
        cursor = await self.db.execute(
            """INSERT INTO feedback_log
               (chat_id, pillar, action, user_request, response_text, regen_count)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (chat_id, pillar, action, user_request, response_text, regen_count),
        )
        await self.db.commit()
        log_id = cursor.lastrowid  # type: ignore[attr-defined]
        if log_id is None:
            # Fallback: query for the most recent row for this chat
            cur = await self.db.execute(
                "SELECT id FROM feedback_log WHERE chat_id = ? ORDER BY id DESC LIMIT 1",
                (chat_id,),
            )
            row = await cur.fetchone()
            log_id = row[0] if row else 0
        logger.debug(
            "Stored response log_id=%d for chat %d pillar=%s", log_id, chat_id, pillar
        )
        return int(log_id)

    async def get(self, log_id: int) -> ResponseRecord | None:
        """Retrieve a stored response by its log_id.

        Args:
            log_id: The primary key of the feedback_log row.

        Returns:
            A ``ResponseRecord`` if found, otherwise ``None``.
        """
        cursor = await self.db.execute(
            """SELECT id, chat_id, pillar, action, user_request,
                      response_text, feedback, regen_count
               FROM feedback_log WHERE id = ?""",
            (log_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return ResponseRecord(
            log_id=row[0],
            chat_id=row[1],
            pillar=row[2],
            action=row[3],
            user_request=row[4],
            response_text=row[5],
            feedback=row[6],
            regen_count=row[7],
        )

    async def update_feedback(self, log_id: int, feedback: str) -> None:
        """Record user feedback (``"up"`` or ``"down"``) for a response.

        Args:
            log_id: The primary key of the feedback_log row.
            feedback: The feedback value (``"up"`` or ``"down"``).
        """
        await self.db.execute(
            "UPDATE feedback_log SET feedback = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (feedback, log_id),
        )
        await self.db.commit()
        logger.debug("Updated feedback for log_id=%d -> %s", log_id, feedback)

    async def update_response(
        self, log_id: int, response_text: str, increment_regen: bool = True
    ) -> None:
        """Replace the stored response text (used after regeneration).

        Args:
            log_id: The primary key of the feedback_log row.
            response_text: The new regenerated response text.
            increment_regen: If True, bump the ``regen_count`` counter.
        """
        if increment_regen:
            await self.db.execute(
                """UPDATE feedback_log
                   SET response_text = ?, regen_count = regen_count + 1,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (response_text, log_id),
            )
        else:
            await self.db.execute(
                "UPDATE feedback_log SET response_text = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (response_text, log_id),
            )
        await self.db.commit()
        logger.debug("Updated response text for log_id=%d", log_id)

    async def get_last_for_chat(self, chat_id: int) -> ResponseRecord | None:
        """Retrieve the most recent stored response for a given chat.

        Args:
            chat_id: Telegram chat ID.

        Returns:
            A ``ResponseRecord`` if any exists for the chat, otherwise ``None``.
        """
        cursor = await self.db.execute(
            """SELECT id, chat_id, pillar, action, user_request,
                      response_text, feedback, regen_count
               FROM feedback_log WHERE chat_id = ?
               ORDER BY id DESC LIMIT 1""",
            (chat_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return ResponseRecord(
            log_id=row[0],
            chat_id=row[1],
            pillar=row[2],
            action=row[3],
            user_request=row[4],
            response_text=row[5],
            feedback=row[6],
            regen_count=row[7],
        )

    async def count_feedback(
        self, chat_id: int | None = None
    ) -> dict[str, int]:
        """Aggregate feedback counts (optionally scoped to a chat).

        Args:
            chat_id: Optional Telegram chat ID to scope the counts.

        Returns:
            A dict with keys ``"up"``, ``"down"``, and ``"none"``
            counting rows with each feedback state.
        """
        if chat_id is not None:
            cursor = await self.db.execute(
                """SELECT
                       SUM(CASE WHEN feedback = 'up' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN feedback = 'down' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN feedback IS NULL THEN 1 ELSE 0 END)
                   FROM feedback_log WHERE chat_id = ?""",
                (chat_id,),
            )
        else:
            cursor = await self.db.execute(
                """SELECT
                       SUM(CASE WHEN feedback = 'up' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN feedback = 'down' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN feedback IS NULL THEN 1 ELSE 0 END)
                   FROM feedback_log""",
            )
        row = await cursor.fetchone()
        up = int(row[0]) if row and row[0] is not None else 0
        down = int(row[1]) if row and row[1] is not None else 0
        none = int(row[2]) if row and row[2] is not None else 0
        return {"up": up, "down": down, "none": none}
