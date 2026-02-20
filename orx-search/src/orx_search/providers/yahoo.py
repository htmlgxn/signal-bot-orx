"""Yahoo search engine provider."""

from __future__ import annotations

import logging
from secrets import token_urlsafe
from urllib.parse import unquote_plus

from fake_useragent import UserAgent
from lxml import html

from orx_search.base import SearchResult
from orx_search.http_client import HttpClient
from orx_search.registry import register
from orx_search.utils import normalize_text, normalize_url

logger = logging.getLogger(__name__)


def _extract_yahoo_url(u: str) -> str:
    """Extract real URL from Yahoo redirect wrapper."""
    t = u.split("/RU=", 1)[1]
    return unquote_plus(t.split("/RK=", 1)[0].split("/RS=", 1)[0])


@register
class YahooProvider:
    """Yahoo text search via HTML scraping."""

    name = "yahoo"

    def __init__(self, proxy: str | None = None) -> None:
        self._ua = UserAgent()
        self._http_client = HttpClient(
            headers={"User-Agent": self._ua.random},
            proxy=proxy,
        )

    def search(self, query: str) -> list[SearchResult]:
        # Yahoo uses randomized URL tokens
        search_url = (
            f"https://search.yahoo.com/search;_ylt={token_urlsafe(24 * 3 // 4)}"
            f";_ylu={token_urlsafe(47 * 3 // 4)}"
        )
        params = {"p": query}

        try:
            resp = self._http_client.get(search_url, params=params)
        except Exception:
            logger.exception("Yahoo search request failed")
            return []

        if not resp.content:
            return []

        return self._extract_results(resp.text)

    def _extract_results(self, html_text: str) -> list[SearchResult]:
        tree = html.fromstring(html_text)
        items = tree.xpath("//div[contains(@class, 'relsrch')]")
        results: list[SearchResult] = []

        for item in items:
            try:
                title = normalize_text(
                    " ".join(
                        item.xpath(".//div[contains(@class, 'Title')]//h3//text()")
                    )
                )
                href = " ".join(
                    item.xpath(".//div[contains(@class, 'Title')]//a/@href")
                ).strip()
                body = normalize_text(
                    " ".join(item.xpath(".//div[contains(@class, 'Text')]//text()"))
                )

                # Filter ads
                if href.startswith("https://www.bing.com/aclick?"):
                    continue

                # Unwrap Yahoo redirect URLs
                if "/RU=" in href:
                    href = _extract_yahoo_url(href)

                href = normalize_url(href)
                if not href:
                    continue

                results.append(
                    SearchResult(title=title, url=href, snippet=body, source="Yahoo")
                )
            except Exception:
                continue

        return results
