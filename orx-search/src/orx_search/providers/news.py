"""DuckDuckGo news search provider via JSON API."""

from __future__ import annotations

import json
import logging

from orx_search.base import SearchResult
from orx_search.http_client import HttpClient
from orx_search.registry import register
from orx_search.utils import extract_vqd, normalize_date, normalize_text, normalize_url

logger = logging.getLogger(__name__)


@register
class DuckDuckGoNewsProvider:
    """DuckDuckGo news search via JSON API (news.js)."""

    name = "duckduckgo_news"

    def __init__(self, proxy: str | None = None) -> None:
        self._http_client = HttpClient(proxy=proxy)

    def _get_vqd(self, query: str) -> str:
        """Get vqd token for a search query."""
        resp = self._http_client.get("https://duckduckgo.com", params={"q": query})
        return extract_vqd(resp.content, query)

    def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        try:
            vqd = self._get_vqd(query)
        except Exception:
            logger.exception("Failed to get VQD token for news search")
            return []

        params = {
            "l": "us-en",
            "o": "json",
            "noamp": "1",
            "q": query,
            "vqd": vqd,
            "p": "-1",
        }

        try:
            resp = self._http_client.get(
                "https://duckduckgo.com/news.js", params=params
            )
        except Exception:
            logger.exception("DuckDuckGo news search request failed")
            return []

        if not resp.content:
            return []

        try:
            data = json.loads(resp.text)
        except json.JSONDecodeError:
            return []

        items = data.get("results", [])
        results = []
        for item in items[:limit]:
            title = normalize_text(str(item.get("title", "")))
            url = normalize_url(str(item.get("url", "")))
            body = normalize_text(str(item.get("excerpt", "")))
            date = item.get("date", "")
            if date:
                date = normalize_date(date)
            source = item.get("source", "")

            snippet_parts = []
            if source:
                snippet_parts.append(f"[{source}]")
            if date:
                snippet_parts.append(f"({date})")
            if body:
                snippet_parts.append(body)

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=" ".join(snippet_parts),
                    source="DuckDuckGo News",
                )
            )

        return results
