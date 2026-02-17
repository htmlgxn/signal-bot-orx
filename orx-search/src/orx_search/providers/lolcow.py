"""Lolcow wiki text search provider base class."""

from __future__ import annotations

import logging
from abc import abstractmethod
from urllib.parse import quote

import httpx

from orx_search.base import SearchResult

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "orx-search/0.1.0 (https://github.com/htmlgxn/signal-bot-orx; bot)",
}


class LolcowProvider:
    """Base class for lolcow wiki search providers."""

    name: str
    source: str
    base_url: str

    def __init__(self) -> None:
        self._http_client = httpx.Client(headers=_HEADERS, timeout=10)

    def search(self, query: str) -> list[SearchResult]:
        url = f"{self.base_url}?action=opensearch&profile=fuzzy&limit=1&search={quote(query)}"

        try:
            resp = self._http_client.get(url)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            logger.exception(f"{self.source} opensearch failed")
            return []

        if not data or len(data) < 4 or not data[1]:
            return []

        title = data[1][0]
        article_url = data[3][0]

        snippet = self._get_extract(title)

        if "may refer to:" in snippet:
            return []

        return [
            SearchResult(
                title=title,
                url=article_url,
                snippet=snippet[:500] if snippet else "",
                source=self.source,
            )
        ]

    def _get_extract(self, title: str) -> str:
        url = (
            f"{self.base_url}?action=query&format=json&prop=extracts"
            f"&titles={quote(title)}&explaintext=0&exintro=0&redirects=1"
        )

        try:
            resp = self._http_client.get(url)
            resp.raise_for_status()
            data = resp.json()
            pages = data.get("query", {}).get("pages", {})
            if not pages:
                return ""

            page = next(iter(pages.values()))
            return page.get("extract", "")
        except Exception:
            return ""
