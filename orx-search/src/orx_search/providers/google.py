"""Google search engine provider."""

from __future__ import annotations

import logging
from random import SystemRandom

from lxml import html

from orx_search.base import SearchResult
from orx_search.http_client import HttpClient
from orx_search.registry import register
from orx_search.utils import normalize_text, normalize_url

logger = logging.getLogger(__name__)
random = SystemRandom()


def _get_opera_ua() -> str:
    """Return a randomized Opera Mini User-Agent string."""
    patterns = [
        "Opera/9.80 (J2ME/MIDP; Opera Mini/{v}/{b}; U; {l}) Presto/{p} Version/{f}",
        "Opera/9.80 (Android; Linux; Opera Mobi/{b}; U; {l}) Presto/{p} Version/{f}",
        "Opera/9.80 (iPhone; Opera Mini/{v}/{b}; U; {l}) Presto/{p} Version/{f}",
        "Opera/9.80 (iPad; Opera Mini/{v}/{b}; U; {l}) Presto/{p} Version/{f}",
    ]
    mini_versions = ["4.0", "5.0.17381", "7.1.32444", "9.80"]
    mobi_builds = ["27", "447", "ADR-1011151731"]
    builds = ["18.678", "24.743", "503"]
    prestos = ["2.6.35", "2.7.60", "2.8.119"]
    finals = ["10.00", "11.10", "12.16"]
    langs = ["en-US", "en-GB", "de-DE", "fr-FR", "es-ES", "ru-RU", "zh-CN"]
    fallback = (
        "Opera/9.80 (iPad; Opera Mini/5.0.17381/503; U; eu) Presto/2.6.35 Version/11.10"
    )

    try:
        p = random.choice(patterns)
        vals = {
            "l": random.choice(langs),
            "p": random.choice(prestos),
            "f": random.choice(finals),
        }
        if "{v}" in p:
            vals["v"] = random.choice(mini_versions)
        if "{b}" in p:
            vals["b"] = (
                random.choice(mobi_builds)
                if "Opera Mobi" in p
                else random.choice(builds)
            )
        return p.format(**vals)
    except Exception:
        return fallback


@register
class GoogleProvider:
    """Google text search via HTML scraping."""

    name = "google"

    def __init__(self, proxy: str | None = None) -> None:
        self._http_client = HttpClient(
            headers={"User-Agent": _get_opera_ua()},
            proxy=proxy,
            http2=False,  # Google often fails with HPACK table size errors in randomized H2
        )

    def search(self, query: str, region: str = "us-en") -> list[SearchResult]:
        country, lang = region.split("-")
        params = {
            "q": query,
            "hl": f"{lang}-{country.upper()}",
            "lr": f"lang_{lang}",
            "cr": f"country{country.upper()}",
        }

        try:
            resp = self._http_client.get("https://www.google.com/search", params=params)
        except Exception:
            logger.exception("Google search request failed")
            return []

        if not resp.content:
            return []

        return self._extract_results(resp.text)

    def _extract_results(self, html_text: str) -> list[SearchResult]:
        tree = html.fromstring(html_text)
        items = tree.xpath("//div[div[@data-hveid]//div[h3]]")
        results: list[SearchResult] = []

        for item in items:
            try:
                title = normalize_text(" ".join(item.xpath(".//h3//text()")))
                href = " ".join(item.xpath(".//a/@href")).strip()
                body = normalize_text(" ".join(item.xpath("./div/div/div[2]//text()")))

                # Extract real URL from Google redirect
                if href.startswith("/url?q="):
                    href = href.split("?q=")[1].split("&")[0]

                href = normalize_url(href)

                if not href or href.startswith("/"):
                    continue

                results.append(
                    SearchResult(title=title, url=href, snippet=body, source="Google")
                )
            except Exception:
                continue

        return results
