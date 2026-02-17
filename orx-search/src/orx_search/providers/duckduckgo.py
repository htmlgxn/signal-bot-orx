from __future__ import annotations

import logging

from fake_useragent import UserAgent
from lxml import html

from orx_search.base import SearchResult
from orx_search.http_client import HttpClient
from orx_search.registry import register

logger = logging.getLogger(__name__)
ua = UserAgent()


@register
class DuckDuckGoProvider:
    name = "duckduckgo"
    search_url = "https://html.duckduckgo.com/html/"

    def __init__(self, proxy: str | None = None) -> None:
        self._http_client = HttpClient(
            headers={"User-Agent": ua.random},
            proxy=proxy,
        )

    def search(self, query: str) -> list[SearchResult]:
        payload = {
            "q": query,
            "b": "",
            "l": "us-en",  # Default region
            "kl": "us-en",
        }

        try:
            resp = self._http_client.post(self.search_url, data=payload)
        except Exception:
            logger.exception("DuckDuckGo search request failed")
            return []

        if not resp.content:
            return []

        return self._extract_results(resp.text)

    def _extract_results(self, html_text: str) -> list[SearchResult]:
        tree = html.fromstring(html_text)

        # XPath selectors adapted from ddgs
        # items_xpath = "//div[contains(@class, 'body')]"
        # elements_xpath = {"title": ".//h2//text()", "href": "./a/@href", "body": "./a//text()"}

        items = tree.xpath("//div[contains(@class, 'body')]")
        results = []

        for item in items:
            try:
                title_parts = item.xpath(".//h2//text()")
                title = " ".join(part.strip() for part in title_parts).strip()

                href_parts = item.xpath("./a/@href")
                url = href_parts[0].strip() if href_parts else ""

                body_parts = item.xpath("./a//text()")
                snippet = " ".join(part.strip() for part in body_parts).strip()

                if not url or url.startswith("https://duckduckgo.com/y.js?"):
                    continue

                results.append(
                    SearchResult(
                        title=title,
                        url=url,
                        snippet=snippet,
                        source="DuckDuckGo",
                    )
                )
            except Exception:
                continue

        return results
