"""Persistent key facts storage per chat.

Each Telegram chat can have multiple key facts extracted from conversations.
These facts are used to personalize future AI responses with long-term
context about the user (e.g., industry, preferences, budget, goals).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from digital_mate.memory.database import AsyncConnection

if TYPE_CHECKING:
    from digital_mate.llm.client import LLMClient

logger = logging.getLogger(__name__)


@dataclass
class KeyFact:
    """Represents a single key fact for a specific chat.

    Attributes:
        id: Database row ID.
        chat_id: Telegram chat ID this fact belongs to.
        fact_text: The fact content (e.g., "User focuses on Instagram Reels").
        fact_category: Category for grouping (default: 'general').
        is_active: Whether this fact is active (soft-delete support).
    """

    id: int
    chat_id: int
    fact_text: str
    fact_category: str = "general"
    is_active: bool = True


class KeyFactManager:
    """Manages CRUD operations for key facts in SQLite.

    Facts are deduplicated via a UNIQUE(chat_id, fact_text) constraint.
    Soft-delete is supported via the is_active flag.
    """

    def __init__(self, db: AsyncConnection) -> None:
        """Initialize the key fact manager.

        Args:
            db: Open AsyncConnection.
        """
        self.db = db

    async def add_fact(
        self,
        chat_id: int,
        fact_text: str,
        category: str = "general",
    ) -> bool:
        """Add a key fact for a chat (deduplicated via UNIQUE constraint).

        Uses INSERT OR IGNORE so duplicate facts are silently skipped.

        Args:
            chat_id: Telegram chat ID.
            fact_text: The fact content text.
            category: Optional category (default: 'general').

        Returns:
            True if a new row was inserted, False if it was a duplicate.
        """
        cursor = await self.db.execute(
            """INSERT OR IGNORE INTO key_facts (chat_id, fact_text, fact_category)
            VALUES (?, ?, ?)""",
            (chat_id, fact_text, category),
        )
        await self.db.commit()
        added = cursor.rowcount > 0
        if added:
            logger.debug("Added key fact for chat %d: %s", chat_id, fact_text[:80])
        return added

    async def get_facts(
        self,
        chat_id: int,
        active_only: bool = True,
    ) -> list[KeyFact]:
        """Get key facts for a chat.

        Args:
            chat_id: Telegram chat ID.
            active_only: If True, only return active facts (is_active=1).

        Returns:
            List of KeyFact instances, ordered by created_at ascending.
        """
        if active_only:
            query = (
                "SELECT id, chat_id, fact_text, fact_category, is_active "
                "FROM key_facts WHERE chat_id = ? AND is_active = 1 "
                "ORDER BY created_at ASC"
            )
        else:
            query = (
                "SELECT id, chat_id, fact_text, fact_category, is_active "
                "FROM key_facts WHERE chat_id = ? "
                "ORDER BY created_at ASC"
            )

        cursor = await self.db.execute(query, (chat_id,))
        rows = await cursor.fetchall()
        return [
            KeyFact(
                id=row[0],
                chat_id=row[1],
                fact_text=row[2],
                fact_category=row[3],
                is_active=bool(row[4]),
            )
            for row in rows
        ]

    async def deactivate_fact(self, fact_id: int) -> bool:
        """Soft-delete a key fact by setting is_active=0.

        Args:
            fact_id: Database row ID of the fact to deactivate.

        Returns:
            True if a row was updated, False if no matching active fact found.
        """
        cursor = await self.db.execute(
            "UPDATE key_facts SET is_active = 0, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND is_active = 1",
            (fact_id,),
        )
        await self.db.commit()
        deactivated = cursor.rowcount > 0
        if deactivated:
            logger.info("Deactivated key fact id=%d", fact_id)
        return deactivated

    async def get_facts_context(self, chat_id: int) -> str:
        """Get a formatted string of active key facts for prompt injection.

        Args:
            chat_id: Telegram chat ID.

        Returns:
            Formatted string like:
            "## Key Facts About This User\\n- fact1\\n- fact2"
            or empty string if no active facts exist.
        """
        facts = await self.get_facts(chat_id, active_only=True)
        if not facts:
            return ""

        lines = ["## Key Facts About This User"]
        for fact in facts:
            lines.append(f"- {fact.fact_text}")
        return "\n".join(lines)

    async def extract_facts_from_conversation(
        self,
        chat_id: int,
        llm_client: LLMClient,
        recent_messages: list[dict[str, str]],
    ) -> list[str]:
        """Extract key facts from recent conversation messages using the LLM.

        Sends recent messages to the LLM with a prompt to extract 1-3 key facts
        useful for future marketing conversations. Each extracted fact is
        persisted via add_fact() (deduplicated by UNIQUE constraint).

        Args:
            chat_id: Telegram chat ID.
            llm_client: LLM client for making the extraction call.
            recent_messages: List of message dicts with 'role' and 'content'.

        Returns:
            List of newly added fact texts (empty if LLM fails or all
            facts were duplicates).
        """
        from digital_mate.llm.client import LLMError

        # Build conversation summary for the LLM
        conversation_text = "\n".join(
            f"{msg['role']}: {msg['content']}" for msg in recent_messages[-10:]
        )

        system_prompt = (
            "You are a fact extraction assistant. Extract 1-3 key facts about "
            "this user that would be useful for future marketing conversations. "
            "Focus on: industry, audience, budget, platforms, goals, tone "
            "preferences, business stage, or other relevant details. "
            "Return JSON: {\"facts\": [\"fact1\", \"fact2\"]}"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Recent conversation:\n{conversation_text}"},
        ]

        try:
            result = await llm_client.chat_json(messages, max_tokens=512)
        except LLMError as exc:
            logger.warning("Fact extraction LLM error for chat %d: %s", chat_id, exc)
            return []
        except Exception as exc:
            logger.warning("Fact extraction unexpected error for chat %d: %s", chat_id, exc)
            return []

        raw_facts = result.get("facts", [])
        if not isinstance(raw_facts, list):
            logger.warning("Fact extraction returned non-list 'facts': %s", type(raw_facts))
            return []

        added_facts: list[str] = []
        for fact_text in raw_facts:
            if not isinstance(fact_text, str) or not fact_text.strip():
                continue
            was_added = await self.add_fact(chat_id, fact_text.strip())
            if was_added:
                added_facts.append(fact_text.strip())

        if added_facts:
            logger.info(
                "Extracted %d new fact(s) for chat %d: %s",
                len(added_facts), chat_id, added_facts,
            )
        return added_facts
