"""Auto-generated weekly content calendar generator.

Uses the LLM to produce a structured 7-day content calendar based on the
user's brand profile, then optionally writes each entry to Notion and
logs it to the local database.
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Any

from digital_mate.llm.client import LLMClient, LLMError
from digital_mate.memory.autocalendar import (
    AutoCalendarManager,
    AutoCalendarEntry,
)
from digital_mate.memory.brand_profile import BrandProfile
from digital_mate.integrations.notion_client import NotionService

logger = logging.getLogger(__name__)

# JSON schema instructions embedded in the LLM prompt
_CALENDAR_JSON_INSTRUCTIONS = """\
Respond with ONLY a JSON object (no markdown fences, no extra text) in this exact format:
{
  "entries": [
    {
      "day": "Monday",
      "platform": "Instagram",
      "content_type": "Reel",
      "topic": "Behind the scenes: brewing process",
      "caption": "Full caption text with emojis and CTA",
      "hashtags": "#coffee #brewing"
    }
  ]
}
Include exactly 7 entries, one per day (Monday through Sunday)."""


class CalendarGenerator:
    """Generates weekly content calendars using the LLM and persists results.

    Orchestrates the full flow: build prompt → LLM call → parse JSON →
    save entries to DB → optionally push to Notion.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        manager: AutoCalendarManager,
        notion_service: NotionService | None = None,
    ) -> None:
        """Initialize the calendar generator.

        Args:
            llm_client: LLM client for generating calendar content.
            manager: AutoCalendar manager for DB persistence.
            notion_service: Optional Notion service for writing entries.
        """
        self.llm_client = llm_client
        self.manager = manager
        self.notion_service = notion_service

    def _build_prompt(
        self,
        brand_profile: BrandProfile | None,
        week_start: date,
    ) -> list[dict[str, str]]:
        """Build the LLM message list for calendar generation.

        Args:
            brand_profile: The user's brand profile (may be None).
            week_start: The Monday of the target week.

        Returns:
            List of message dicts for the LLM client.
        """
        brand_desc = "No brand profile set — generate a generic content calendar."
        if brand_profile:
            brand_desc = (
                f"Brand: {brand_profile.name}\n"
                f"Industry: {brand_profile.industry or 'N/A'}\n"
                f"Audience: {brand_profile.audience or 'N/A'}\n"
                f"Tone: {brand_profile.tone or 'N/A'}\n"
                f"Products/Services: {brand_profile.products or 'N/A'}\n"
                f"Preferred Hashtags: {brand_profile.hashtags or 'N/A'}\n"
                f"Competitors: {brand_profile.competitors or 'N/A'}"
            )

        week_end = week_start + timedelta(days=6)
        user_content = (
            f"Create a 7-day content calendar for the week of "
            f"{week_start.strftime('%Y-%m-%d')} to {week_end.strftime('%Y-%m-%d')}.\n\n"
            f"Brand Context:\n{brand_desc}\n\n"
            f"Requirements:\n"
            f"- One entry per day, Monday through Sunday\n"
            f"- Vary platforms (Instagram, TikTok, Twitter/X, LinkedIn, YouTube, etc.)\n"
            f"- Vary content types (Reel, Carousel, Story, Post, Video, Thread, etc.)\n"
            f"- Each caption should be engaging and ready to post\n"
            f"- Include 3-7 relevant hashtags per entry\n"
            f"- Match the brand's tone and target audience\n\n"
            f"{_CALENDAR_JSON_INSTRUCTIONS}"
        )

        return [
            {
                "role": "system",
                "content": (
                    "You are a expert social media content strategist. "
                    "You create detailed, actionable weekly content calendars. "
                    "Always respond with valid JSON when asked for structured output."
                ),
            },
            {"role": "user", "content": user_content},
        ]

    def _parse_calendar_response(
        self,
        raw: str,
        chat_id: int,
        week_start: date,
    ) -> list[AutoCalendarEntry]:
        """Parse the LLM JSON response into AutoCalendarEntry objects.

        Args:
            raw: Raw LLM response text.
            chat_id: Telegram chat ID.
            week_start: Monday of the target week.

        Returns:
            List of parsed entries. Empty list on parse failure.
        """
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown fences
            stripped = raw.strip()
            if "```" in stripped:
                start = stripped.find("{")
                end = stripped.rfind("}") + 1
                if start != -1 and end > start:
                    try:
                        data = json.loads(stripped[start:end])
                    except json.JSONDecodeError:
                        logger.error("Failed to parse calendar JSON after fence strip")
                        return []
            else:
                logger.error("Failed to parse calendar JSON: %s", raw[:200])
                return []

        entries_data = data.get("entries", []) if isinstance(data, dict) else []
        entries: list[AutoCalendarEntry] = []

        day_offset = 0
        for item in entries_data:
            if not isinstance(item, dict):
                continue
            entry_date = week_start + timedelta(days=day_offset)
            day_offset += 1
            if day_offset > 7:
                break

            entries.append(
                AutoCalendarEntry(
                    chat_id=chat_id,
                    week_start=week_start.isoformat(),
                    platform=str(item.get("platform", "")),
                    content_type=str(item.get("content_type", "")),
                    topic=str(item.get("topic", "")),
                    caption=str(item.get("caption", "")),
                    hashtags=str(item.get("hashtags", "")),
                    entry_date=entry_date.isoformat(),
                )
            )

        return entries

    async def generate_week(
        self,
        chat_id: int,
        brand_profile: BrandProfile | None = None,
        week_start: date | None = None,
    ) -> list[AutoCalendarEntry]:
        """Generate a weekly content calendar for a chat.

        Args:
            chat_id: Telegram chat ID.
            brand_profile: Optional brand profile for personalization.
            week_start: Monday of the target week (defaults to next Monday).

        Returns:
            List of generated and persisted AutoCalendarEntry objects.
            Empty list on failure.
        """
        if week_start is None:
            today = date.today()
            week_start = today + timedelta(days=(7 - today.weekday()) % 7 or 7)

        messages = self._build_prompt(brand_profile, week_start)

        try:
            raw_response = await self.llm_client.chat(
                messages,
                temperature=0.8,
                max_tokens=2048,
            )
        except LLMError as exc:
            logger.error("LLM error generating calendar for chat %d: %s", chat_id, exc)
            return []

        entries = self._parse_calendar_response(raw_response, chat_id, week_start)
        if not entries:
            logger.warning("No entries parsed for chat %d", chat_id)
            return []

        # Persist to database
        for entry in entries:
            await self.manager.add_entry(entry)

        # Optionally write to Notion
        if self.notion_service and self.notion_service.content_calendar_db:
            for entry in entries:
                page_id = await self.notion_service.create_content_entry(
                    topic=entry.topic,
                    platform=entry.platform,
                    content_type=entry.content_type,
                    date=entry.entry_date or entry.week_start,
                    status="Idea",
                    caption=entry.caption,
                    hashtags=entry.hashtags,
                )
                if page_id:
                    await self.manager.update_entry_notion_id(
                        entry.chat_id,
                        entry.week_start,
                        entry.topic,
                        page_id,
                    )

        # Mark subscription as run
        await self.manager.mark_run(chat_id)

        logger.info(
            "Generated %d calendar entries for chat %d (week of %s)",
            len(entries), chat_id, week_start.isoformat(),
        )
        return entries

    def format_calendar_summary(
        self,
        entries: list[AutoCalendarEntry],
    ) -> str:
        """Format calendar entries into a readable Telegram message.

        Args:
            entries: List of calendar entries to format.

        Returns:
            Formatted message string.
        """
        if not entries:
            return "📅 No calendar entries to display."

        lines = ["📅 *Auto-Generated Content Calendar*\n"]
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday",
                     "Friday", "Saturday", "Sunday"]

        for i, entry in enumerate(entries):
            day_name = day_names[i] if i < 7 else f"Day {i + 1}"
            lines.append(f"*\u2611\ufe0f {day_name}* — {entry.platform} | {entry.content_type}")
            lines.append(f"  \U0001f4cc {entry.topic}")
            if entry.caption:
                # Truncate long captions for Telegram
                caption = entry.caption if len(entry.caption) <= 200 else entry.caption[:197] + "..."
                lines.append(f"  \U0001f4dd {caption}")
            if entry.hashtags:
                lines.append(f"  \U0001f3f7 {entry.hashtags}")
            lines.append("")

        lines.append("_Entries saved to your Notion content calendar._")
        return "\n".join(lines)
