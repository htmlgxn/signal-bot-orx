from __future__ import annotations

import logging

import httpx

from orx_search.base import SearchResult
from orx_search.registry import register

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "orx-search/0.1.0 (https://github.com/htmlgxn/signal-bot-orx; bot)",
}


@register
class BooksProvider:
    """Book search via Open Library API."""

    name = "books"

    def __init__(self) -> None:
        self._http_client = httpx.Client(headers=_HEADERS, timeout=10)

    def search(self, query: str) -> list[SearchResult]:
        url = "https://openlibrary.org/search.json"
        params = {"q": query, "limit": "5"}

        try:
            resp = self._http_client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            logger.exception("Books search failed")
            return []

        results = []
        for doc in data.get("docs", []):
            title = doc.get("title", "Untitled")
            author = ", ".join(doc.get("author_name", ["Unknown"]))
            year = doc.get("first_publish_year", "")
            key = doc.get("key", "")
            book_url = f"https://openlibrary.org{key}" if key else ""

            snippet = f"by {author}"
            if year:
                snippet += f" ({year})"

            results.append(
                SearchResult(
                    title=title,
                    url=book_url,
                    snippet=snippet,
                    source="Open Library",
                )
            )

        return results
