"""Brand profile service for the web dashboard.

Wraps the existing BrandProfileManager with dict-based
API convenience methods.
"""

from __future__ import annotations

import logging
from typing import Any

from digital_mate.memory.brand_profile import BrandProfile, BrandProfileManager
from digital_mate.memory.database import AsyncConnection

logger = logging.getLogger(__name__)


class BrandService:
    """Web-facing brand profile service."""

    def __init__(self, db: AsyncConnection) -> None:
        self._manager = BrandProfileManager(db)
        self._db = db

    async def close(self) -> None:
        """Close the database connection."""
        await self._db.close()

    async def get(self, chat_id: int) -> dict[str, Any] | None:
        """Get a brand profile as dict."""
        profile = await self._manager.get(chat_id)
        if profile is None:
            return None
        return profile.to_dict()

    async def list_all(self) -> list[dict[str, Any]]:
        """List all brand profiles."""
        cursor = await self._db.execute(
            """SELECT chat_id, name, industry, audience, tone, products,
                      hashtags, competitors, language_pref,
                      platform_preference, budget_range, business_stage
               FROM brand_profiles ORDER BY updated_at DESC"""
        )
        rows = await cursor.fetchall()
        profiles = []
        for row in rows:
            profile = BrandProfile(
                chat_id=row[0],
                name=row[1],
                industry=row[2],
                audience=row[3],
                tone=row[4],
                products=row[5],
                hashtags=row[6],
                competitors=row[7],
                language_pref=row[8],
                platform_preference=row[9],
                budget_range=row[10],
                business_stage=row[11],
            )
            profiles.append(profile.to_dict())
        return profiles

    async def create_or_update(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create or update a brand profile from dict data.

        Args:
            data: Dict with brand profile fields. Must include chat_id.

        Returns:
            The saved brand profile as dict.
        """
        chat_id = data.get("chat_id")
        if not chat_id:
            raise ValueError("chat_id is required")

        profile = BrandProfile(
            chat_id=int(chat_id),
            name=data.get("name", ""),
            industry=data.get("industry", ""),
            audience=data.get("audience", ""),
            tone=data.get("tone", ""),
            products=data.get("products", ""),
            hashtags=data.get("hashtags", ""),
            competitors=data.get("competitors", ""),
            language_pref=data.get("language_pref", "bilingual"),
            platform_preference=data.get("platform_preference", ""),
            budget_range=data.get("budget_range", ""),
            business_stage=data.get("business_stage", ""),
        )
        result = await self._manager.create_or_update(profile)
        return result.to_dict()
