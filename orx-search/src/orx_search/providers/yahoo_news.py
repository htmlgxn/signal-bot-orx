"""Yahoo News search engine provider."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import unquote_plus

from fake_useragent import UserAgent
from lxml import html

from orx_search.base import SearchResult
from orx_search.http_client import HttpClient
from orx_search.registry import register
from orx_search.utils import normalize_text, normalize_url

logger = logging.getLogger(__name__)


_DATE_RE = re.compile(r"\b(\d+)\s*(year|month|week|day|hour|minute)s?\b", re.IGNORECASE)
_DATE_UNITS: dict[str, int] = {
    "minute": 60,
    "hour": 3600,
    "day": 86400,
    "week": 604800,
    "month": 2592000,
    "year": 31536000,
}


def _extract_date(pub_date_str: str) -> str:
    """Extract and normalize date from Yahoo news date string."""
    m = _DATE_RE.search(pub_date_str)
    if not m:
        return pub_date_str

    number = int(m.group(1))
    unit = m.group(2).lower()
    seconds = _DATE_UNITS.get(unit, 86400) * number
    dt = (datetime.now(UTC) - timedelta(seconds=seconds)).replace(microsecond=0)
    return dt.isoformat()


def _extract_yahoo_url(u: str) -> str:
    """Extract real URL from Yahoo redirect wrapper."""
    url = u.split("/RU=", 1)[1].split("/RK=", 1)[0].split("?", 1)[0]
    return unquote_plus(url)


def _extract_image(u: str) -> str:
    """Extract clean image URL from Yahoo image wrapper."""
    idx = u.find("-/")
    return u[idx + 2 :] if idx != -1 else u


def _extract_source(s: str) -> str:
    """Remove ' via Yahoo' from string."""
    return s.split(" ·  via Yahoo", maxsplit=1)[0]


@register
class YahooNewsProvider:
    """Yahoo News search via HTML scraping."""

    name = "yahoo_news"

    def __init__(self, proxy: str | None = None) -> None:
        self._ua = UserAgent()
        self._http_client = HttpClient(
            headers={"User-Agent": self._ua.random},
            proxy=proxy,
        )

    def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        params = {"p": query}

        try:
            resp = self._http_client.get(
                "https://news.search.yahoo.com/search", params=params
            )
        except Exception:
            logger.exception("Yahoo News search request failed")
            return []

        if not resp.content:
            return []

        return self._extract_results(resp.text, limit)

    def _extract_results(self, html_text: str, limit: int) -> list[SearchResult]:
        tree = html.fromstring(html_text)
        items = tree.xpath("//div[@id='web']//li[a]")
        results: list[SearchResult] = []

        for item in items[:limit]:
            try:
                title = normalize_text(" ".join(item.xpath(".//h4//text()")))
                url = " ".join(item.xpath(".//h4/a/@href")).strip()
                body = normalize_text(" ".join(item.xpath(".//p//text()")))
                date = " ".join(
                    item.xpath(".//span[contains(@class, 'time')]//text()")
                ).strip()
                source = " ".join(
                    item.xpath(".//span[contains(@class, 'source')]//text()")
                ).strip()

                # Post-process
                if date:
                    date = _extract_date(date)
                if "/RU=" in url:
                    url = _extract_yahoo_url(url)
                if source:
                    source = _extract_source(source)

                url = normalize_url(url)
                if not url:
                    continue

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
                        source="Yahoo News",
                    )
                )
            except Exception:
                continue

        return results
