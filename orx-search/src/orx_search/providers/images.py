"""DuckDuckGo images search provider via JSON API."""

from __future__ import annotations

import json
import logging

from orx_search.base import SearchResult
from orx_search.http_client import HttpClient
from orx_search.registry import register
from orx_search.utils import extract_vqd, normalize_text, normalize_url

logger = logging.getLogger(__name__)


@register
class DuckDuckGoImagesProvider:
    """DuckDuckGo image search via JSON API (i.js)."""

    name = "duckduckgo_images"

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
            logger.exception("Failed to get VQD token for images search")
            return []

        params = {
            "o": "json",
            "q": query,
            "l": "us-en",
            "vqd": vqd,
            "p": "1",
        }

        try:
            resp = self._http_client.get(
                "https://duckduckgo.com/i.js",
                params=params,
                headers={
                    "Referer": "https://duckduckgo.com/",
                    "Sec-Fetch-Mode": "cors",
                },
            )
        except Exception:
            logger.exception("DuckDuckGo images search request failed")
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
            image_url = normalize_url(str(item.get("image", "")))
            thumbnail = normalize_url(str(item.get("thumbnail", "")))
            source_url = normalize_url(str(item.get("url", "")))
            width = item.get("width", "")
            height = item.get("height", "")
            source = item.get("source", "")

            snippet_parts = []
            if width and height:
                snippet_parts.append(f"{width}x{height}")
            if source:
                snippet_parts.append(f"Source: {source}")
            if thumbnail:
                snippet_parts.append(f"Thumbnail: {thumbnail}")

            results.append(
                SearchResult(
                    title=title,
                    url=image_url or source_url,
                    snippet=" | ".join(snippet_parts),
                    source="DuckDuckGo Images",
                )
            )

        return results
