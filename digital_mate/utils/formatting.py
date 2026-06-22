"""Telegram MarkdownV2 formatting utilities.

Provides helpers for escaping special characters, splitting long messages,
and formatting calendar/campaign data for display.
"""

from __future__ import annotations

import re

# Characters that need escaping in Telegram MarkdownV2
_MARKDOWN_V2_SPECIAL = r"_*[]()~`>#+-=|{}.!"


def escape_markdown_v2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2 parse mode.

    Args:
        text: Raw text to escape.

    Returns:
        Text with MarkdownV2 special characters escaped.
    """
    # Build regex pattern for special chars
    pattern = f"([{re.escape(_MARKDOWN_V2_SPECIAL)}])"
    return re.sub(pattern, r"\\\1", text)


def split_message(text: str, max_len: int = 4096) -> list[str]:
    """Split a long message at paragraph boundaries.

    Tries to split at double newlines first, then single newlines,
    and finally at the max_len boundary if needed.

    Args:
        text: The message text to split.
        max_len: Maximum length per chunk (default Telegram limit).

    Returns:
        List of message chunks, each within max_len.
    """
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break

        # Try to split at paragraph boundary (double newline)
        split_pos = remaining.rfind("\n\n", 0, max_len)
        if split_pos == -1 or split_pos < max_len // 2:
            # Try single newline
            split_pos = remaining.rfind("\n", 0, max_len)

        if split_pos == -1 or split_pos < max_len // 2:
            # Force split at max_len
            split_pos = max_len

        chunks.append(remaining[:split_pos])
        remaining = remaining[split_pos:].lstrip("\n")

    return chunks


def format_calendar_week(entries: list[dict[str, str]]) -> str:
    """Format content calendar entries for a week view.

    Args:
        entries: List of dicts with keys like 'date', 'platform',
                 'content_type', 'topic', 'status'.

    Returns:
        Formatted string showing the week's content calendar.
    """
    if not entries:
        return "📅 *No content scheduled for this week.*\n\nUse the Content pillar to plan your content calendar!"

    lines = ["📅 *This Week's Content Calendar*\n"]
    lines.append("─" * 30)

    for entry in entries:
        date = entry.get("date", "TBD")
        platform = entry.get("platform", "General")
        content_type = entry.get("content_type", "Post")
        topic = entry.get("topic", "Untitled")
        status = entry.get("status", "planned")

        status_emoji = {
            "published": "✅",
            "scheduled": "📤",
            "draft": "📝",
            "planned": "📋",
        }.get(status.lower(), "📋")

        lines.append(f"\n{status_emoji} *{date}*")
        lines.append(f"  Platform: {platform}")
        lines.append(f"  Type: {content_type}")
        lines.append(f"  Topic: {topic}")

    lines.append("\n" + "─" * 30)
    return "\n".join(lines)


def format_calendar_entry(entry: dict[str, str]) -> str:
    """Format a single content calendar entry for display.

    Args:
        entry: Dict with keys 'platform', 'content_type', 'topic',
               'caption', 'hashtags'.

    Returns:
        Formatted string showing the content entry.
    """
    platform = entry.get("platform", "General")
    content_type = entry.get("content_type", "Post")
    topic = entry.get("topic", "Untitled")
    caption = entry.get("caption", "")
    hashtags = entry.get("hashtags", "")

    lines = [
        f"📢 *{topic}*",
        f"  Platform: {platform}",
        f"  Type: {content_type}",
    ]
    if caption:
        lines.append(f"  Caption: {caption}")
    if hashtags:
        lines.append(f"  Hashtags: {hashtags}")

    return "\n".join(lines)


def format_campaign_table(campaigns: list[dict[str, str]]) -> str:
    """Format campaign data as a comparison table.

    Args:
        campaigns: List of dicts with keys like 'name', 'status',
                   'start_date', 'end_date', 'budget', 'reach',
                   'engagement', 'conversions'.

    Returns:
        Formatted string showing campaign comparison.
    """
    if not campaigns:
        return "📊 *No active campaigns found.*\n\nUse the Strategy pillar to plan your next campaign!"

    lines = ["📊 *Campaign Overview*\n"]
    lines.append("─" * 40)

    for campaign in campaigns:
        name = campaign.get("name", "Untitled Campaign")
        status = campaign.get("status", "active")
        start = campaign.get("start_date", "—")
        end = campaign.get("end_date", "—")
        budget = campaign.get("budget", "—")
        reach = campaign.get("reach", "—")
        engagement = campaign.get("engagement", "—")
        conversions = campaign.get("conversions", "—")

        status_emoji = {
            "active": "🟢",
            "completed": "✅",
            "paused": "⏸️",
            "planned": "📋",
        }.get(status.lower(), "📋")

        lines.append(f"\n{status_emoji} *{name}*")
        lines.append(f"  Period: {start} → {end}")
        if budget != "—":
            lines.append(f"  Budget: {budget}")
        if reach != "—":
            lines.append(f"  Reach: {reach}")
        if engagement != "—":
            lines.append(f"  Engagement: {engagement}")
        if conversions != "—":
            lines.append(f"  Conversions: {conversions}")

    lines.append("\n" + "─" * 40)
    return "\n".join(lines)
