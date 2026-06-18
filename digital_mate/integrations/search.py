"""Web search integration with Tavily (primary) and DuckDuckGo (fallback).

Provides async web search capabilities for the Research pillar.
Uses httpx directly — no SDK dependencies required.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote_plus

import httpx

logger = logging.getLogger(__name__)

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
DUCKDUCKGO_INSTANT_URL = "https://api.duckduckgo.com/"
DUCKDUCKGO_HTML_URL = "https://html.duckduckgo.com/html/"


class SearchError(Exception):
    """Raised when a web search fails."""

    pass


class SearchService:
    """Web search service with Tavily primary and DuckDuckGo fallback.

    If no API keys are configured, searches return a friendly message
    indicating that web search is not available.
    """

    def __init__(self, tavily_api_key: str | None = None) -> None:
        """Initialize the search service.

        Args:
            tavily_api_key: Optional Tavily API key for better results.
        """
        self.tavily_api_key = tavily_api_key

    @property
    def is_available(self) -> bool:
        """Check if any search backend is available.

        Returns:
            True — DuckDuckGo is always available as fallback.
        """
        return True  # DuckDuckGo is always available

    async def search(
        self,
        query: str,
        max_results: int = 5,
    ) -> list[dict[str, str]]:
        """Perform a web search and return results.

        Tries Tavily first (if configured), falls back to DuckDuckGo.

        Args:
            query: Search query string.
            max_results: Maximum number of results to return.

        Returns:
            List of dicts with 'title', 'url', and 'snippet' keys.
        """
        if self.tavily_api_key:
            try:
                return await self._search_tavily(query, max_results)
            except SearchError as exc:
                logger.warning("Tavily search failed, falling back to DuckDuckGo: %s", exc)

        return await self._search_duckduckgo(query, max_results)

    async def _search_tavily(
        self,
        query: str,
        max_results: int,
    ) -> list[dict[str, str]]:
        """Search using Tavily API.

        Args:
            query: Search query.
            max_results: Max results.

        Returns:
            List of search result dicts.

        Raises:
            SearchError: If the API call fails.
        """
        payload = {
            "api_key": self.tavily_api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
            "include_answer": True,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(TAVILY_SEARCH_URL, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            raise SearchError(f"Tavily API error: {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise SearchError(f"Tavily connection error: {exc}") from exc

        results: list[dict[str, str]] = []

        # Include the answer summary if available
        answer = data.get("answer", "")
        if answer:
            results.append({
                "title": "Summary",
                "url": "",
                "snippet": answer,
            })

        for item in data.get("results", [])[:max_results]:
            results.append({
                "title": item.get("title", "Untitled"),
                "url": item.get("url", ""),
                "snippet": item.get("content", "")[:500],
            })

        return results

    async def _search_duckduckgo(
        self,
        query: str,
        max_results: int,
    ) -> list[dict[str, str]]:
        """Search using DuckDuckGo Instant Answer API + HTML fallback.

        Args:
            query: Search query.
            max_results: Max results.

        Returns:
            List of search result dicts.
        """
        results: list[dict[str, str]] = []

        # Try instant answer API first
        try:
            params = {"q": query, "format": "json", "no_html": "1"}
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(DUCKDUCKGO_INSTANT_URL, params=params)
                response.raise_for_status()
                data = response.json()

            # Abstract (main answer)
            abstract = data.get("AbstractText", "")
            if abstract:
                results.append({
                    "title": data.get("Heading", "Result"),
                    "url": data.get("AbstractURL", ""),
                    "snippet": abstract[:500],
                })

            # Related topics
            for topic in data.get("RelatedTopics", [])[:max_results]:
                if isinstance(topic, dict) and "Text" in topic:
                    results.append({
                        "title": topic.get("Text", "")[:80],
                        "url": topic.get("FirstURL", ""),
                        "snippet": topic.get("Text", "")[:500],
                    })
                if len(results) >= max_results:
                    break

        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("DuckDuckGo instant search failed: %s", exc)

        # If no results from instant API, try HTML search
        if not results:
            try:
                results = await self._search_duckduckgo_html(query, max_results)
            except SearchError as exc:
                logger.warning("DuckDuckGo HTML search also failed: %s", exc)
                results = [{
                    "title": "Search Unavailable",
                    "url": "",
                    "snippet": f"Could not retrieve search results for: {query}",
                }]

        return results[:max_results]

    async def _search_duckduckgo_html(
        self,
        query: str,
        max_results: int,
    ) -> list[dict[str, str]]:
        """Search DuckDuckGo HTML endpoint as last resort.

        Args:
            query: Search query.
            max_results: Max results.

        Returns:
            List of search result dicts.

        Raises:
            SearchError: If the request fails.
        """
        try:
            params = {"q": query}
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                response = await client.get(
                    DUCKDUCKGO_HTML_URL,
                    params=params,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; DigitalMate/1.0)"},
                )
                response.raise_for_status()
                html = response.text
        except httpx.HTTPError as exc:
            raise SearchError(f"DuckDuckGo HTML error: {exc}") from exc

        # Simple HTML parsing for result links
        results: list[dict[str, str]] = []
        import re

        # Extract result snippets from DuckDuckGo HTML
        result_blocks = re.findall(
            r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
            r'class="result__snippet">(.*?)</[at]',
            html,
            re.DOTALL,
        )

        for url, title, snippet in result_blocks[:max_results]:
            # Clean HTML tags from title and snippet
            clean_title = re.sub(r"<[^>]+>", "", title).strip()
            clean_snippet = re.sub(r"<[^>]+>", "", snippet).strip()
            results.append({
                "title": clean_title,
                "url": url,
                "snippet": clean_snippet[:500],
            })

        return results


def format_search_context(results: list[dict[str, str]]) -> str:
    """Format search results into a context string for the LLM.

    Args:
        results: List of search result dicts.

    Returns:
        Formatted string suitable for injection into LLM prompts.
    """
    if not results:
        return ""

    lines = ["## Web Search Results\n"]
    for i, result in enumerate(results, 1):
        title = result.get("title", "Untitled")
        url = result.get("url", "")
        snippet = result.get("snippet", "")
        lines.append(f"{i}. **{title}**")
        if url:
            lines.append(f"   Source: {url}")
        lines.append(f"   {snippet}")
        lines.append("")

    return "\n".join(lines)
