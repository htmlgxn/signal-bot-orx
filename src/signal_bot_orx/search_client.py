from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Literal

from ddgs import DDGS
from ddgs.exceptions import DDGSException, RatelimitException, TimeoutException

from signal_bot_orx.config import Settings

SearchMode = Literal["search", "news", "wiki", "images"]


class SearchError(Exception):
    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


@dataclass(frozen=True)
class SearchResult:
    mode: SearchMode
    title: str
    url: str
    snippet: str
    source: str | None = None
    date: str | None = None
    image_url: str | None = None


class SearchClient:
    async def search(
        self, mode: SearchMode, query: str, settings: Settings
    ) -> list[SearchResult]:
        normalized_query = " ".join(query.split()).strip()
        if not normalized_query:
            raise SearchError("Search query is empty.")

        try:
            return await asyncio.to_thread(
                self._search_sync,
                mode,
                normalized_query,
                settings,
            )
        except RatelimitException as exc:
            raise SearchError(
                "Search service is rate-limited. Try again soon."
            ) from exc
        except TimeoutException as exc:
            raise SearchError("Search service timed out. Try again.") from exc
        except DDGSException as exc:
            raise SearchError(f"Search failed: {exc}") from exc

    def _search_sync(
        self,
        mode: SearchMode,
        query: str,
        settings: Settings,
    ) -> list[SearchResult]:
        timeout = max(1, round(settings.bot_search_timeout_seconds))
        with DDGS(timeout=timeout) as ddgs:
            raw_results: list[dict[str, object]]
            if mode == "search":
                raw_results = ddgs.text(
                    query,
                    region=settings.bot_search_region,
                    safesearch=settings.bot_search_safesearch,
                    max_results=settings.bot_search_text_max_results,
                    backend=settings.bot_search_backend_search,
                )
            elif mode == "news":
                raw_results = ddgs.news(
                    query,
                    region=settings.bot_search_region,
                    safesearch=settings.bot_search_safesearch,
                    max_results=settings.bot_search_news_max_results,
                    backend=settings.bot_search_backend_news,
                )
            elif mode == "wiki":
                raw_results = ddgs.text(
                    query,
                    region=settings.bot_search_region,
                    safesearch=settings.bot_search_safesearch,
                    max_results=settings.bot_search_wiki_max_results,
                    backend=settings.bot_search_backend_wiki,
                )
            else:
                raw_results = ddgs.images(
                    query,
                    region=settings.bot_search_region,
                    safesearch=settings.bot_search_safesearch,
                    max_results=settings.bot_search_images_max_results,
                    backend=settings.bot_search_backend_images,
                )

        normalized = [
            _normalize_result(mode=mode, result=item)
            for item in raw_results
            if isinstance(item, dict)
        ]
        normalized = [item for item in normalized if item is not None]

        if not normalized:
            raise SearchError("No search results found.")

        return normalized


def _normalize_result(
    mode: SearchMode, result: dict[str, object]
) -> SearchResult | None:
    if mode == "images":
        title = _as_non_empty(result.get("title")) or "Untitled image"
        image_url = _as_non_empty(result.get("image"))
        source_url = _as_non_empty(result.get("url"))
        url = image_url or source_url
        if url is None:
            return None
        snippet = _as_non_empty(result.get("source")) or ""
        source = _as_non_empty(result.get("source"))
        return SearchResult(
            mode=mode,
            title=title,
            url=url,
            snippet=snippet,
            source=source,
            image_url=image_url,
        )

    title = _as_non_empty(result.get("title")) or "Untitled"
    snippet = (
        _as_non_empty(result.get("body")) or _as_non_empty(result.get("content")) or ""
    )
    url = _as_non_empty(result.get("href")) or _as_non_empty(result.get("url"))
    if url is None:
        return None

    return SearchResult(
        mode=mode,
        title=title,
        url=url,
        snippet=snippet,
        source=_as_non_empty(result.get("source")),
        date=_as_non_empty(result.get("date")),
        image_url=_as_non_empty(result.get("image")),
    )


def _as_non_empty(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    return None
