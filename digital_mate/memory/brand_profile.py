"""Persistent brand profile storage per chat.

Each Telegram chat can have one brand profile with brand details
used to personalize AI responses.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, asdict
from typing import Any

from digital_mate.memory.database import AsyncConnection

logger = logging.getLogger(__name__)


@dataclass
class BrandProfile:
    """Represents a brand profile for a specific chat.

    Attributes:
        chat_id: Telegram chat ID this profile belongs to.
        name: Brand name.
        industry: Industry sector.
        audience: Target audience description.
        tone: Desired tone of voice.
        products: Key products/services (comma-separated).
        hashtags: Preferred hashtags (comma-separated).
        competitors: Competitor names (comma-separated).
        language_pref: Language preference (bilingual/en/id).
    """
    chat_id: int
    name: str
    industry: str = ""
    audience: str = ""
    tone: str = ""
    products: str = ""
    hashtags: str = ""
    competitors: str = ""
    language_pref: str = "bilingual"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary.

        Returns:
            Dict representation of the brand profile.
        """
        return asdict(self)


class BrandProfileManager:
    """Manages CRUD operations for brand profiles in SQLite.

    Each chat_id can have at most one brand profile (UNIQUE constraint).
    """

    def __init__(self, db: AsyncConnection) -> None:
        """Initialize the brand profile manager.

        Args:
            db: Open AsyncConnection.
        """
        self.db = db

    async def create(self, profile: BrandProfile) -> BrandProfile:
        """Create a new brand profile.

        Args:
            profile: BrandProfile instance to create.

        Returns:
            The created BrandProfile.

        Raises:
            ValueError: If a profile already exists for this chat_id.
        """
        try:
            await self.db.execute(
                """INSERT INTO brand_profiles
                (chat_id, name, industry, audience, tone, products, hashtags, competitors, language_pref)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    profile.chat_id,
                    profile.name,
                    profile.industry,
                    profile.audience,
                    profile.tone,
                    profile.products,
                    profile.hashtags,
                    profile.competitors,
                    profile.language_pref,
                ),
            )
            await self.db.commit()
            logger.info("Created brand profile for chat %d", profile.chat_id)
            return profile
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"Brand profile already exists for chat {profile.chat_id}") from exc

    async def get(self, chat_id: int) -> BrandProfile | None:
        """Get the brand profile for a chat.

        Args:
            chat_id: Telegram chat ID.

        Returns:
            BrandProfile if found, None otherwise.
        """
        cursor = await self.db.execute(
            """SELECT chat_id, name, industry, audience, tone, products,
                      hashtags, competitors, language_pref
            FROM brand_profiles WHERE chat_id = ?""",
            (chat_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None

        return BrandProfile(
            chat_id=row[0],
            name=row[1],
            industry=row[2],
            audience=row[3],
            tone=row[4],
            products=row[5],
            hashtags=row[6],
            competitors=row[7],
            language_pref=row[8],
        )

    async def update(self, profile: BrandProfile) -> BrandProfile:
        """Update an existing brand profile.

        Args:
            profile: BrandProfile with updated fields.

        Returns:
            The updated BrandProfile.

        Raises:
            ValueError: If no profile exists for this chat_id.
        """
        cursor = await self.db.execute(
            """UPDATE brand_profiles SET
                name=?, industry=?, audience=?, tone=?,
                products=?, hashtags=?, competitors=?, language_pref=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE chat_id=?""",
            (
                profile.name,
                profile.industry,
                profile.audience,
                profile.tone,
                profile.products,
                profile.hashtags,
                profile.competitors,
                profile.language_pref,
                profile.chat_id,
            ),
        )
        await self.db.commit()
        if cursor.rowcount == 0:
            raise ValueError(f"No brand profile found for chat {profile.chat_id}")
        logger.info("Updated brand profile for chat %d", profile.chat_id)
        return profile

    async def delete(self, chat_id: int) -> bool:
        """Delete the brand profile for a chat.

        Args:
            chat_id: Telegram chat ID.

        Returns:
            True if a profile was deleted, False if none existed.
        """
        cursor = await self.db.execute(
            "DELETE FROM brand_profiles WHERE chat_id = ?",
            (chat_id,),
        )
        await self.db.commit()
        deleted = cursor.rowcount > 0
        if deleted:
            logger.info("Deleted brand profile for chat %d", chat_id)
        return deleted

    async def create_or_update(self, profile: BrandProfile) -> BrandProfile:
        """Create a new profile or update existing one.

        Args:
            profile: BrandProfile instance.

        Returns:
            The created or updated BrandProfile.
        """
        existing = await self.get(profile.chat_id)
        if existing is None:
            return await self.create(profile)
        return await self.update(profile)
