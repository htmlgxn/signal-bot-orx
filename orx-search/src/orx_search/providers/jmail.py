"""JMail search engine provider for Jeffrey Epstein's email archive."""

from __future__ import annotations

import logging
import re

from orx_search.base import SearchResult
from orx_search.http_client import HttpClient
from orx_search.registry import register
from orx_search.utils import normalize_text

logger = logging.getLogger(__name__)


@register
class JMailProvider:
    """JMail search provider extracting data from Next.js RSC and hydration scripts."""

    name = "jmail"

    def __init__(self, proxy: str | None = None) -> None:
        self._http_client = HttpClient(
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            },
            proxy=proxy,
            http2=True,
        )

    def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """Search JMail for emails."""
        # Step 1: Get result list from RSC
        rsc_headers = {
            "Accept": "text/x-component",
            "Next-Router-State-Tree": "%5B%22%22%2C%7B%22children%22%3A%5B%22(joogle)%22%2C%7B%22children%22%3A%5B%22search%22%2C%7B%22children%22%3A%5B%22__PAGE__%22%2C%7B%7D%5D%7D%5D%7D%5D%7D%5D",
        }

        try:
            resp = self._http_client.get(
                "https://jmail.world/search", params={"q": query}, headers=rsc_headers
            )
        except Exception:
            logger.exception("JMail search request failed")
            return []

        if not resp.text:
            return []

        # Extract EFTA IDs from RSC payload
        # Common pattern: "EFTA02639428"
        efta_ids = sorted(list(set(re.findall(r"EFTA[0-9]{8}", resp.text))))

        results: list[SearchResult] = []
        for doc_id in efta_ids[:limit]:
            try:
                result = self._fetch_thread_details(doc_id)
                if result:
                    results.append(result)
            except Exception:
                logger.debug(
                    f"Failed to fetch details for thread {doc_id}", exc_info=True
                )
                continue

        return results

    def _fetch_thread_details(self, doc_id: str) -> SearchResult | None:
        """Fetch full email body from a thread page."""
        url = f"https://jmail.world/thread/{doc_id}?view=inbox"

        try:
            resp = self._http_client.get(url)
        except Exception:
            return None

        if not resp.text:
            return None

        # Extract title from <title> tag
        title_match = re.search(r"<title>([^<]+)</title>", resp.text)
        title = title_match.group(1) if title_match else f"JMail Email {doc_id}"
        title = normalize_text(title.replace("— Epstein Emails", "").strip())

        # 2. Extract Body - Strategy:
        # a) Prefer og:description if it's thread-specific
        # b) Prefer Article description from JSON-LD
        # c) Fallback to non-site-wide text chunks

        body = ""
        date = None
        site_desc_marker = "Interactive archive of Jeffrey Epstein"

        # Try og:description first (it's usually the cleanest thread-specific snippet)
        og_match = re.search(r'property="og:description"\s+content="(.*?)"', resp.text)
        if og_match:
            text = (
                og_match.group(1)
                .encode("utf-8")
                .decode("unicode-escape", errors="ignore")
            )
            if site_desc_marker not in text:
                body = normalize_text(text)

        # Try to find Article metadata for body and date
        # Date pattern: "datePublished":"2013-11-11T16:31:14.000Z"
        date_match = re.search(r'"datePublished":"(.*?)"', resp.text)
        if date_match:
            date = date_match.group(1).split("T")[0]  # Take YYYY-MM-DD

        if not body:
            article_desc = re.search(
                r'"@type":"Article".*?"description":"(.*?)"', resp.text
            )
            if article_desc:
                text = (
                    article_desc.group(1)
                    .encode("utf-8")
                    .decode("unicode-escape", errors="ignore")
                )
                if site_desc_marker not in text:
                    body = normalize_text(text)

        # Heuristic Fallback: Any long-ish clean string that isn't the site description
        if not body:
            all_blobs = re.findall(r'"(.*?)"', resp.text)
            for blob in all_blobs:
                try:
                    text = blob.encode("utf-8").decode(
                        "unicode-escape", errors="ignore"
                    )
                    text = normalize_text(text)
                    if (
                        len(text) > 50
                        and site_desc_marker not in text
                        and "{" not in text
                        and "[" not in text
                        and not text.startswith("$")
                        and not text.startswith("animation:")
                    ):
                        body = text
                        break
                except Exception:
                    continue

        return SearchResult(
            title=title, url=url.split("?")[0], snippet=body, source="JMail", date=date
        )
