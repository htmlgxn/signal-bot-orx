"""DuckDuckGo videos search provider via JSON API."""

from __future__ import annotations

import json
import logging

from orx_search.base import SearchResult
from orx_search.http_client import HttpClient
from orx_search.registry import register
from orx_search.utils import extract_vqd, normalize_text

logger = logging.getLogger(__name__)


@register
class DuckDuckGoVideosProvider:
    """DuckDuckGo video search via JSON API (v.js)."""

    name = "duckduckgo_videos"

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
            logger.exception("Failed to get VQD token for videos search")
            return []

        params = {
            "l": "us-en",
            "o": "json",
            "q": query,
            "vqd": vqd,
            "f": ",,,",
            "p": "-1",
        }

        try:
            resp = self._http_client.get("https://duckduckgo.com/v.js", params=params)
        except Exception:
            logger.exception("DuckDuckGo videos search request failed")
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
            content_url = str(item.get("content", ""))
            description = normalize_text(str(item.get("description", "")))
            duration = item.get("duration", "")
            publisher = item.get("publisher", "")
            uploader = item.get("uploader", "")
            published = item.get("published", "")

            snippet_parts = []
            if publisher or uploader:
                snippet_parts.append(f"by {uploader or publisher}")
            if duration:
                snippet_parts.append(f"[{duration}]")
            if published:
                snippet_parts.append(f"({published})")
            if description:
                snippet_parts.append(description)

            results.append(
                SearchResult(
                    title=title,
                    url=content_url,
                    snippet=" ".join(snippet_parts),
                    source="DuckDuckGo Videos",
                )
            )

        return results
