"""Notion API integration for content calendar and campaign tracking.

Uses httpx directly against the Notion API (no SDK dependency).
Provides methods to query content calendar and campaign tracker databases.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

NOTION_API_VERSION = "2022-06-28"
NOTION_BASE_URL = "https://api.notion.com/v1"


class NotionError(Exception):
    """Raised when a Notion API call fails."""

    pass


class NotionService:
    """Wrapper around the Notion API for content calendar and campaign databases.

    Provides methods to query databases and extract structured data
    for use by the bot's pillars.
    """

    def __init__(
        self,
        api_key: str,
        content_calendar_db: str | None = None,
        campaign_tracker_db: str | None = None,
    ) -> None:
        """Initialize the Notion service.

        Args:
            api_key: Notion integration API key.
            content_calendar_db: Database ID for the content calendar.
            campaign_tracker_db: Database ID for the campaign tracker.
        """
        self.api_key = api_key
        self.content_calendar_db = content_calendar_db
        self.campaign_tracker_db = campaign_tracker_db
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Notion-Version": NOTION_API_VERSION,
            "Content-Type": "application/json",
        }

    @property
    def is_configured(self) -> bool:
        """Check if at least one Notion database is configured.

        Returns:
            True if any database ID is set.
        """
        return bool(self.content_calendar_db or self.campaign_tracker_db)

    async def _request(
        self,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated request to the Notion API.

        Args:
            method: HTTP method.
            path: API endpoint path.
            json_body: Optional JSON request body.

        Returns:
            Parsed JSON response.

        Raises:
            NotionError: If the request fails.
        """
        url = f"{NOTION_BASE_URL}{path}"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(
                    method,
                    url,
                    headers=self._headers,
                    json=json_body,
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            logger.error("Notion API error %d: %s", exc.response.status_code, exc.response.text)
            raise NotionError(f"Notion API error: {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            logger.error("Notion request failed: %s", exc)
            raise NotionError(f"Notion connection error: {exc}") from exc

    async def create_page(
        self,
        database_id: str,
        properties: dict[str, Any],
        children: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create a new page (row) in a Notion database.

        Args:
            database_id: The Notion database ID to add the page to.
            properties: Notion property object mapping property names
                to typed value dicts (e.g. {"Name": {"title": [...]}}).
            children: Optional list of block objects for page content.

        Returns:
            The created page object from the Notion API.

        Raises:
            NotionError: If the request fails.
        """
        body: dict[str, Any] = {
            "parent": {"database_id": database_id},
            "properties": properties,
        }
        if children:
            body["children"] = children

        return await self._request("POST", "/pages", body)

    @staticmethod
    def _build_title_property(value: str) -> dict[str, Any]:
        """Build a Notion title property from a string.

        Args:
            value: The title text.

        Returns:
            Notion title property dict.
        """
        return {"title": [{"text": {"content": value}}]}

    @staticmethod
    def _build_rich_text_property(value: str) -> dict[str, Any]:
        """Build a Notion rich_text property from a string.

        Args:
            value: The text content.

        Returns:
            Notion rich_text property dict.
        """
        return {"rich_text": [{"text": {"content": value}}]}

    @staticmethod
    def _build_select_property(value: str) -> dict[str, Any]:
        """Build a Notion select property from a string.

        Args:
            value: The select option name.

        Returns:
            Notion select property dict.
        """
        return {"select": {"name": value}}

    @staticmethod
    def _build_date_property(date_str: str) -> dict[str, Any]:
        """Build a Notion date property from an ISO date string.

        Args:
            date_str: ISO date string (YYYY-MM-DD).

        Returns:
            Notion date property dict.
        """
        return {"date": {"start": date_str}}

    async def create_content_entry(
        self,
        topic: str,
        platform: str = "",
        content_type: str = "",
        date: str = "",
        status: str = "Idea",
        caption: str = "",
        hashtags: str = "",
    ) -> str | None:
        """Create a new content calendar entry in Notion.

        Args:
            topic: The content topic / title.
            platform: Target platform (e.g. Instagram, TikTok).
            content_type: Content type (e.g. Reel, Carousel, Post).
            date: ISO date string for the scheduled post date.
            status: Status label (default "Idea").
            caption: Full caption text for the post.
            hashtags: Hashtags string.

        Returns:
            The Notion page ID of the created entry, or None if
            the content calendar database is not configured or creation fails.
        """
        if not self.content_calendar_db:
            logger.warning("Cannot create content entry: no content calendar DB configured")
            return None

        properties: dict[str, Any] = {
            "Name": self._build_title_property(topic),
            "Status": self._build_select_property(status),
        }
        if platform:
            properties["Platform"] = self._build_select_property(platform)
        if content_type:
            properties["Content Type"] = self._build_select_property(content_type)
        if date:
            properties["Date"] = self._build_date_property(date)
        if caption:
            properties["Caption"] = self._build_rich_text_property(caption)
        if hashtags:
            properties["Hashtags"] = self._build_rich_text_property(hashtags)

        try:
            page = await self.create_page(self.content_calendar_db, properties)
            page_id = page.get("id")
            logger.info("Created Notion content entry: %s (id=%s)", topic, page_id)
            return page_id
        except NotionError as exc:
            logger.error("Failed to create Notion content entry '%s': %s", topic, exc)
            return None

    async def query_database(
        self,
        database_id: str,
        filter_body: dict[str, Any] | None = None,
        sorts: list[dict[str, Any]] | None = None,
        page_size: int = 20,
    ) -> list[dict[str, Any]]:
        """Query a Notion database and return raw page results.

        Args:
            database_id: The Notion database ID.
            filter_body: Optional Notion filter object.
            sorts: Optional sort criteria.
            page_size: Number of results per page.

        Returns:
            List of page objects from the database.
        """
        body: dict[str, Any] = {"page_size": page_size}
        if filter_body:
            body["filter"] = filter_body
        if sorts:
            body["sorts"] = sorts

        data = await self._request("POST", f"/databases/{database_id}/query", body)
        return data.get("results", [])

    @staticmethod
    def _extract_property(page: dict[str, Any], prop_name: str) -> str:
        """Extract a text value from a Notion page property.

        Supports title, rich_text, select, status, date, and number types.

        Args:
            page: Notion page object.
            prop_name: Property name to extract.

        Returns:
            Extracted text value or empty string.
        """
        props = page.get("properties", {})
        prop = props.get(prop_name, {})
        prop_type = prop.get("type", "")

        if prop_type == "title":
            title_arr = prop.get("title", [])
            return "".join(t.get("plain_text", "") for t in title_arr)
        elif prop_type == "rich_text":
            text_arr = prop.get("rich_text", [])
            return "".join(t.get("plain_text", "") for t in text_arr)
        elif prop_type == "select":
            select = prop.get("select")
            return select.get("name", "") if select else ""
        elif prop_type == "status":
            status = prop.get("status")
            return status.get("name", "") if status else ""
        elif prop_type == "date":
            date_obj = prop.get("date")
            if date_obj:
                return date_obj.get("start", "")
            return ""
        elif prop_type == "number":
            num = prop.get("number")
            return str(num) if num is not None else ""
        elif prop_type == "url":
            return prop.get("url", "")
        elif prop_type == "multi_select":
            ms = prop.get("multi_select", [])
            return ", ".join(s.get("name", "") for s in ms)
        else:
            return ""

    async def get_content_calendar(
        self,
        days: int = 7,
    ) -> list[dict[str, str]]:
        """Get upcoming content calendar entries.

        Args:
            days: Number of days ahead to look.

        Returns:
            List of content entries with date, platform, content_type,
            topic, and status fields.
        """
        if not self.content_calendar_db:
            return []

        try:
            pages = await self.query_database(
                self.content_calendar_db,
                sorts=[{"property": "Date", "direction": "ascending"}],
                page_size=20,
            )
        except NotionError as exc:
            logger.warning("Failed to fetch content calendar: %s", exc)
            return []

        entries: list[dict[str, str]] = []
        for page in pages:
            entry = {
                "date": self._extract_property(page, "Date"),
                "platform": self._extract_property(page, "Platform"),
                "content_type": self._extract_property(page, "Content Type"),
                "topic": self._extract_property(page, "Title"),
                "status": self._extract_property(page, "Status"),
            }
            entries.append(entry)

        return entries

    async def get_campaigns(
        self,
        status: str | None = None,
    ) -> list[dict[str, str]]:
        """Get campaign data from the campaign tracker database.

        Args:
            status: Optional status filter (e.g., 'Active', 'Completed').

        Returns:
            List of campaign dicts with name, status, dates, and metrics.
        """
        if not self.campaign_tracker_db:
            return []

        filter_body: dict[str, Any] | None = None
        if status:
            filter_body = {
                "property": "Status",
                "select": {"equals": status},
            }

        try:
            pages = await self.query_database(
                self.campaign_tracker_db,
                filter_body=filter_body,
                page_size=20,
            )
        except NotionError as exc:
            logger.warning("Failed to fetch campaigns: %s", exc)
            return []

        campaigns: list[dict[str, str]] = []
        for page in pages:
            campaign = {
                "name": self._extract_property(page, "Name"),
                "status": self._extract_property(page, "Status"),
                "start_date": self._extract_property(page, "Start Date"),
                "end_date": self._extract_property(page, "End Date"),
                "budget": self._extract_property(page, "Budget"),
                "reach": self._extract_property(page, "Reach"),
                "engagement": self._extract_property(page, "Engagement"),
                "conversions": self._extract_property(page, "Conversions"),
            }
            campaigns.append(campaign)

        return campaigns
