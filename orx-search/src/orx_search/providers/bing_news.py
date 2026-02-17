"""Bing News search engine provider."""

from __future__ import annotations

import logging
import re
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from fake_useragent import UserAgent
from lxml import html  # type: ignore

from orx_search.base import SearchResult
from orx_search.http_client import HttpClient
from orx_search.registry import register
from orx_search.utils import normalize_text

logger = logging.getLogger(__name__)


_DATE_RE = re.compile(
    r"\b(\d+)\s*(days|tagen|jours|giorni|dias|días|дн\.|день)?\b", re.IGNORECASE
)


def _extract_date(pub_date_str: str) -> str:
    """Extract and normalize date from Bing news date string."""
    date_formats = ["%d.%m.%Y", "%m/%d/%Y", "%d/%m/%Y"]
    for date_format in date_formats:
        with suppress(ValueError):
            return (
                datetime.strptime(pub_date_str, date_format).astimezone(UTC).isoformat()
            )

    match = _DATE_RE.search(pub_date_str)
    if match:
        days_ago = int(match.group(1))
        return (
            (datetime.now(UTC) - timedelta(days=days_ago))
            .replace(microsecond=0)
            .isoformat()
        )

    return pub_date_str


@register
class BingNewsProvider:
    """Bing news search via HTML scraping."""

    name = "bing_news"

    def __init__(self, proxy: str | None = None) -> None:
        self._ua = UserAgent()
        self._http_client = HttpClient(
            headers={"User-Agent": self._ua.random},
            proxy=proxy,
        )

    def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        params = {
            "q": query,
            "InfiniteScroll": "1",
            "first": "1",
            "SFX": "1",
        }

        try:
            resp = self._http_client.get(
                "https://www.bing.com/news/infinitescrollajax", params=params
            )
        except Exception:
            logger.exception("Bing News search request failed")
            return []

        if not resp.content:
            return []

        return self._extract_results(resp.text, limit)

    def _extract_results(self, html_text: str, limit: int) -> list[SearchResult]:
        tree = html.fromstring(html_text)
        items = tree.xpath("//div[contains(@class, 'newsitem')]")
        results: list[SearchResult] = []

        for item in items[:limit]:
            try:
                title = item.get("data-title", "")
                url = item.get("url", "")
                body = normalize_text(
                    " ".join(item.xpath(".//div[@class='snippet']//text()"))
                )
                date = " ".join(item.xpath(".//span[@aria-label]//@aria-label")).strip()
                source = item.get("data-author", "")

                if date:
                    date = _extract_date(date)

                snippet_parts = []
                if source:
                    snippet_parts.append(f"[{source}]")
                if date:
                    snippet_parts.append(f"({date})")
                if body:
                    snippet_parts.append(body)

                results.append(
                    SearchResult(
                        title=normalize_text(title),
                        url=url,
                        snippet=" ".join(snippet_parts),
                        source="Bing News",
                    )
                )
            except Exception:
                continue

        return results
