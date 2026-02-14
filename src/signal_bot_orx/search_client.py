from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Literal, cast

from ddgs import DDGS
from ddgs.exceptions import DDGSException, RatelimitException, TimeoutException

from signal_bot_orx.config import Settings

SearchMode = Literal["search", "news", "wiki", "images"]
logger = logging.getLogger(__name__)


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
                raw_results = _search_text_with_fallback(
                    ddgs=ddgs,
                    query=query,
                    settings=settings,
                    backends=settings.bot_search_backend_search_order,
                )
            elif mode == "news":
                raw_results = _search_news_with_fallback(
                    ddgs=ddgs,
                    query=query,
                    settings=settings,
                    backends=settings.bot_search_backend_news_order,
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


def _search_text_with_fallback(
    *,
    ddgs: DDGS,
    query: str,
    settings: Settings,
    backends: tuple[str, ...],
) -> list[dict[str, object]]:
    last_exception: Exception | None = None
    attempts = tuple(_dedupe_backends(backends))
    _debug_log(
        settings=settings,
        event="search_backend_chain",
        mode="search",
        backend_count=len(attempts),
    )
    for backend in attempts:
        try:
            raw_results = ddgs.text(
                query,
                region=settings.bot_search_region,
                safesearch=settings.bot_search_safesearch,
                max_results=settings.bot_search_text_max_results,
                backend=backend,
            )
        except (DDGSException, TimeoutException, RatelimitException) as exc:
            last_exception = exc
            _debug_log(
                settings=settings,
                event="search_backend_attempt",
                mode="search",
                backend=backend,
                status="error",
                reason_code=exc.__class__.__name__,
            )
            continue

        normalized = _normalize_raw_results(raw_results)
        _debug_log(
            settings=settings,
            event="search_backend_attempt",
            mode="search",
            backend=backend,
            status="ok" if normalized else "empty",
            result_count=len(normalized),
        )
        if normalized:
            return normalized

    _debug_log(
        settings=settings,
        event="search_backend_exhausted",
        mode="search",
        backend_count=len(attempts),
        reason_code=(
            last_exception.__class__.__name__ if last_exception is not None else "empty"
        ),
    )
    if last_exception is not None:
        raise last_exception
    return []


def _search_news_with_fallback(
    *,
    ddgs: DDGS,
    query: str,
    settings: Settings,
    backends: tuple[str, ...],
) -> list[dict[str, object]]:
    last_exception: Exception | None = None
    attempts = tuple(_dedupe_backends(backends))
    _debug_log(
        settings=settings,
        event="search_backend_chain",
        mode="news",
        backend_count=len(attempts),
    )
    for backend in attempts:
        try:
            raw_results = ddgs.news(
                query,
                region=settings.bot_search_region,
                safesearch=settings.bot_search_safesearch,
                max_results=settings.bot_search_news_max_results,
                backend=backend,
            )
        except (DDGSException, TimeoutException, RatelimitException) as exc:
            last_exception = exc
            _debug_log(
                settings=settings,
                event="search_backend_attempt",
                mode="news",
                backend=backend,
                status="error",
                reason_code=exc.__class__.__name__,
            )
            continue

        normalized = _normalize_raw_results(raw_results)
        _debug_log(
            settings=settings,
            event="search_backend_attempt",
            mode="news",
            backend=backend,
            status="ok" if normalized else "empty",
            result_count=len(normalized),
        )
        if normalized:
            return normalized

    _debug_log(
        settings=settings,
        event="search_backend_exhausted",
        mode="news",
        backend_count=len(attempts),
        reason_code=(
            last_exception.__class__.__name__ if last_exception is not None else "empty"
        ),
    )
    if last_exception is not None:
        raise last_exception
    return []


def _normalize_raw_results(raw_results: object) -> list[dict[str, object]]:
    if not isinstance(raw_results, list):
        return []
    cleaned: list[dict[str, object]] = []
    for item in raw_results:
        if isinstance(item, dict):
            cleaned.append(cast(dict[str, object], item))
    return cleaned


def _dedupe_backends(backends: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for backend in backends:
        normalized = backend.strip().lower()
        if not normalized or normalized in seen:
            continue
        ordered.append(normalized)
        seen.add(normalized)
    return tuple(ordered)


def _debug_log(settings: Settings, event: str, **fields: object) -> None:
    if not settings.bot_search_debug_logging:
        return
    logger.info(
        "search_backend_debug event=%s %s",
        event,
        " ".join(
            f"{key}={str(value).replace('\n', ' ').strip() or '-'}"
            for key, value in sorted(fields.items())
        ),
    )
