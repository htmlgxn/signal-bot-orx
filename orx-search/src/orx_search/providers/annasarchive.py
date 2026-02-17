"""Anna's Archive book search provider."""

from __future__ import annotations

import logging

from fake_useragent import UserAgent
from lxml import html  # type: ignore

from orx_search.base import SearchResult
from orx_search.http_client import HttpClient
from orx_search.registry import register
from orx_search.utils import normalize_text, normalize_url

logger = logging.getLogger(__name__)


@register
class AnnasArchiveProvider:
    """Anna's Archive book search via HTML scraping."""

    name = "annasarchive"

    def __init__(self, proxy: str | None = None) -> None:
        self._ua = UserAgent()
        self._http_client = HttpClient(
            headers={"User-Agent": self._ua.random},
            proxy=proxy,
        )

    def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        params = {"q": query}

        try:
            resp = self._http_client.get(
                "https://annas-archive.li/search", params=params
            )
        except Exception:
            logger.exception("Anna's Archive search request failed")
            return []

        if not resp.content:
            return []

        return self._extract_results(resp.text, limit)

    def _extract_results(self, html_text: str, limit: int) -> list[SearchResult]:
        # Pre-process: remove HTML comments that break parsing
        html_text = html_text.replace("<!--", "").replace("-->", "")

        tree = html.fromstring(html_text)
        items = tree.xpath("//div[contains(@class, 'record-list-outer')]/div")
        results: list[SearchResult] = []
        base_url = "https://annas-archive.li"

        for item in items[:limit]:
            try:
                title = normalize_text(
                    " ".join(item.xpath(".//a[contains(@class, 'text-lg')]//text()"))
                )
                author = normalize_text(
                    " ".join(item.xpath(".//a[span[contains(@class, 'user')]]//text()"))
                )
                publisher = normalize_text(
                    " ".join(
                        item.xpath(".//a[span[contains(@class, 'company')]]//text()")
                    )
                )
                info = normalize_text(
                    " ".join(
                        item.xpath(".//div[contains(@class, 'text-gray-800')]/text()")
                    )
                )
                url = " ".join(item.xpath("./a/@href")).strip()

                if url and not url.startswith("http"):
                    url = f"{base_url}{url}"
                url = normalize_url(url)

                if not title:
                    continue

                snippet_parts = []
                if author:
                    snippet_parts.append(f"by {author}")
                if publisher:
                    snippet_parts.append(f"Publisher: {publisher}")
                if info:
                    snippet_parts.append(info)

                results.append(
                    SearchResult(
                        title=title,
                        url=url,
                        snippet=" | ".join(snippet_parts),
                        source="Anna's Archive",
                    )
                )
            except Exception:
                continue

        return results
