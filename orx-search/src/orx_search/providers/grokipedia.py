"""Grokipedia text search provider."""

from __future__ import annotations

import json
import logging

from orx_search.base import SearchResult
from orx_search.http_client import HttpClient
from orx_search.registry import register

logger = logging.getLogger(__name__)


@register
class GrokipediaProvider:
    """Grokipedia text search via JSON API."""

    name = "grokipedia"

    def __init__(self, proxy: str | None = None) -> None:
        self._http_client = HttpClient(proxy=proxy)

    def search(self, query: str) -> list[SearchResult]:
        url = "https://grokipedia.com/api/typeahead"
        params = {"query": query, "limit": "1"}

        try:
            resp = self._http_client.get(url, params=params)
        except Exception:
            logger.exception("Grokipedia search request failed")
            return []

        if not resp.content:
            return []

        try:
            data = json.loads(resp.text)
        except json.JSONDecodeError:
            return []

        items = data.get("results", [])
        if not items:
            return []

        item = items[0]
        title = item.get("title", "").strip("_")
        body = item.get("snippet", "")
        # Remove header from snippet if present
        if "\n\n" in body:
            body = body.split("\n\n", 1)[1]
        slug = item.get("slug", "")
        article_url = f"https://grokipedia.com/page/{slug}" if slug else ""

        return [
            SearchResult(
                title=title,
                url=article_url,
                snippet=body[:500] if body else "",
                source="Grokipedia",
            )
        ]
