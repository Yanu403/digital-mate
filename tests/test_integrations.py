"""Tests for digital_mate.integrations module (Notion, Search)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from digital_mate.integrations.notion_client import NotionService, NotionError
from digital_mate.integrations.search import SearchService, SearchError, format_search_context


class TestNotionService:
    """Test Notion API integration."""

    def test_is_configured_with_both_dbs(self) -> None:
        """Test is_configured returns True when both databases set."""
        service = NotionService(
            api_key="test-key",
            content_calendar_db="cal-db",
            campaign_tracker_db="camp-db",
        )
        assert service.is_configured is True

    def test_is_configured_with_one_db(self) -> None:
        """Test is_configured returns True when one database set."""
        service = NotionService(api_key="test-key", content_calendar_db="cal-db")
        assert service.is_configured is True

    def test_is_not_configured(self) -> None:
        """Test is_configured returns False when no databases set."""
        service = NotionService(api_key="test-key")
        assert service.is_configured is False

    def test_extract_property_title(self) -> None:
        """Test extracting title property from Notion page."""
        page = {
            "properties": {
                "Title": {
                    "type": "title",
                    "title": [{"plain_text": "My Post"}],
                }
            }
        }
        result = NotionService._extract_property(page, "Title")
        assert result == "My Post"

    def test_extract_property_rich_text(self) -> None:
        """Test extracting rich_text property."""
        page = {
            "properties": {
                "Description": {
                    "type": "rich_text",
                    "rich_text": [{"plain_text": "Hello "}, {"plain_text": "World"}],
                }
            }
        }
        result = NotionService._extract_property(page, "Description")
        assert result == "Hello World"

    def test_extract_property_select(self) -> None:
        """Test extracting select property."""
        page = {
            "properties": {
                "Platform": {
                    "type": "select",
                    "select": {"name": "Instagram"},
                }
            }
        }
        result = NotionService._extract_property(page, "Platform")
        assert result == "Instagram"

    def test_extract_property_status(self) -> None:
        """Test extracting status property."""
        page = {
            "properties": {
                "Status": {
                    "type": "status",
                    "status": {"name": "Published"},
                }
            }
        }
        result = NotionService._extract_property(page, "Status")
        assert result == "Published"

    def test_extract_property_date(self) -> None:
        """Test extracting date property."""
        page = {
            "properties": {
                "Date": {
                    "type": "date",
                    "date": {"start": "2024-01-15"},
                }
            }
        }
        result = NotionService._extract_property(page, "Date")
        assert result == "2024-01-15"

    def test_extract_property_number(self) -> None:
        """Test extracting number property."""
        page = {
            "properties": {
                "Budget": {
                    "type": "number",
                    "number": 5000,
                }
            }
        }
        result = NotionService._extract_property(page, "Budget")
        assert result == "5000"

    def test_extract_property_missing(self) -> None:
        """Test extracting nonexistent property returns empty string."""
        page = {"properties": {}}
        result = NotionService._extract_property(page, "Nonexistent")
        assert result == ""

    def test_extract_property_multi_select(self) -> None:
        """Test extracting multi_select property."""
        page = {
            "properties": {
                "Tags": {
                    "type": "multi_select",
                    "multi_select": [{"name": "SEO"}, {"name": "Content"}],
                }
            }
        }
        result = NotionService._extract_property(page, "Tags")
        assert result == "SEO, Content"

    @pytest.mark.asyncio
    async def test_get_content_calendar_no_db(self) -> None:
        """Test get_content_calendar returns empty when no DB configured."""
        service = NotionService(api_key="test-key")
        result = await service.get_content_calendar()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_campaigns_no_db(self) -> None:
        """Test get_campaigns returns empty when no DB configured."""
        service = NotionService(api_key="test-key")
        result = await service.get_campaigns()
        assert result == []


class TestSearchService:
    """Test web search integration."""

    def test_is_available(self) -> None:
        """Test that search is always available (DuckDuckGo fallback)."""
        service = SearchService()
        assert service.is_available is True

    def test_is_available_with_tavily(self) -> None:
        """Test availability with Tavily key."""
        service = SearchService(tavily_api_key="test-key")
        assert service.is_available is True

    def test_format_search_context_empty(self) -> None:
        """Test formatting empty search results."""
        result = format_search_context([])
        assert result == ""

    def test_format_search_context_with_results(self) -> None:
        """Test formatting search results into context string."""
        results = [
            {"title": "Test Article", "url": "https://example.com", "snippet": "This is a test snippet."},
            {"title": "Another Article", "url": "https://example.org", "snippet": "Another snippet."},
        ]
        context = format_search_context(results)
        assert "Test Article" in context
        assert "https://example.com" in context
        assert "This is a test snippet." in context
        assert "Another Article" in context

    @pytest.mark.asyncio
    async def test_search_with_mocked_tavily(self) -> None:
        """Test search with mocked Tavily response."""
        service = SearchService(tavily_api_key="test-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "answer": "Test answer",
            "results": [
                {"title": "Result 1", "url": "https://r1.com", "content": "Content 1"},
                {"title": "Result 2", "url": "https://r2.com", "content": "Content 2"},
            ],
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client

            results = await service.search("test query")
            assert len(results) >= 1
            # Should have answer + results
            assert any("Test answer" in r.get("snippet", "") for r in results)


class TestFormatSearchContext:
    """Test format_search_context function."""

    def test_with_url_and_snippet(self) -> None:
        """Test formatting with full result data."""
        results = [{"title": "A", "url": "http://a.com", "snippet": "Snippet A"}]
        ctx = format_search_context(results)
        assert "A" in ctx
        assert "http://a.com" in ctx
        assert "Snippet A" in ctx

    def test_without_url(self) -> None:
        """Test formatting result without URL."""
        results = [{"title": "Summary", "url": "", "snippet": "Just a summary"}]
        ctx = format_search_context(results)
        assert "Summary" in ctx
        assert "Just a summary" in ctx
