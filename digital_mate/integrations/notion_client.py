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
