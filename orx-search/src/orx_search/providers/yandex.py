"""Yandex search engine provider."""

from __future__ import annotations

import logging
from random import SystemRandom

from fake_useragent import UserAgent
from lxml import html  # type: ignore

from orx_search.base import SearchResult
from orx_search.http_client import HttpClient
from orx_search.registry import register
from orx_search.utils import normalize_text, normalize_url

logger = logging.getLogger(__name__)
random = SystemRandom()


@register
class YandexProvider:
    """Yandex text search via HTML scraping."""

    name = "yandex"

    def __init__(self, proxy: str | None = None) -> None:
        self._ua = UserAgent()
        self._http_client = HttpClient(
            headers={"User-Agent": self._ua.random},
            proxy=proxy,
        )

    def search(self, query: str) -> list[SearchResult]:
        params = {
            "text": query,
            "web": "1",
            "searchid": str(random.randint(1000000, 9999999)),
        }

        try:
            resp = self._http_client.get(
                "https://yandex.com/search/site/", params=params
            )
        except Exception:
            logger.exception("Yandex search request failed")
            return []

        if not resp.content:
            return []

        return self._extract_results(resp.text)

    def _extract_results(self, html_text: str) -> list[SearchResult]:
        tree = html.fromstring(html_text)
        items = tree.xpath("//li[contains(@class, 'serp-item')]")
        results: list[SearchResult] = []

        for item in items:
            try:
                title = normalize_text(" ".join(item.xpath(".//h3//text()")))
                href = " ".join(item.xpath(".//h3//a/@href")).strip()
                body = normalize_text(
                    " ".join(item.xpath(".//div[contains(@class, 'text')]//text()"))
                )

                href = normalize_url(href)
                if not href:
                    continue

                results.append(
                    SearchResult(title=title, url=href, snippet=body, source="Yandex")
                )
            except Exception:
                continue

        return results
