from __future__ import annotations

import logging
from urllib.parse import quote

import httpx

from orx_search.base import SearchResult
from orx_search.registry import register

logger = logging.getLogger(__name__)

# Wikipedia requires a descriptive User-Agent
_HEADERS = {
    "User-Agent": "orx-search/0.1.0 (https://github.com/htmlgxn/signal-bot-orx; bot)",
}


@register
class WikipediaProvider:
    name = "wikipedia"

    def __init__(self, lang: str = "en") -> None:
        self._lang = lang
        self._http_client = httpx.Client(headers=_HEADERS, timeout=10)

    def search(self, query: str) -> list[SearchResult]:
        encoded_query = quote(query)

        # Phase 1: Opensearch to get the title and URL
        url = (
            f"https://{self._lang}.wikipedia.org/w/api.php"
            f"?action=opensearch&profile=fuzzy&limit=1&search={encoded_query}"
        )

        try:
            resp = self._http_client.get(url)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            logger.exception("Wikipedia opensearch failed")
            return []

        # Opensearch format: [query, [titles], [descriptions], [urls]]
        if not data or len(data) < 4 or not data[1]:
            return []

        title = data[1][0]
        article_url = data[3][0]

        # Phase 2: Get extract (snippet)
        snippet = self._get_extract(title)

        if "may refer to:" in snippet:
            return []

        return [
            SearchResult(
                title=title,
                url=article_url,
                snippet=snippet[:500] if snippet else "",
                source="Wikipedia",
            )
        ]

    def _get_extract(self, title: str) -> str:
        encoded_title = quote(title)
        url = (
            f"https://{self._lang}.wikipedia.org/w/api.php"
            f"?action=query&format=json&prop=extracts"
            f"&titles={encoded_title}&explaintext=0&exintro=0&redirects=1"
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
