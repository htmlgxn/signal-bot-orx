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
            if mode == "search":
                normalized = _search_mode_with_backends(
                    ddgs=ddgs,
                    query=query,
                    settings=settings,
                    mode="search",
                    backends=settings.bot_search_backend_search_order,
                    max_results=settings.bot_search_text_max_results,
                    strategy=settings.bot_search_backend_strategy,
                )
                if not normalized:
                    raise SearchError("No search results found.")
                return normalized
            if mode == "news":
                normalized = _search_mode_with_backends(
                    ddgs=ddgs,
                    query=query,
                    settings=settings,
                    mode="news",
                    backends=settings.bot_search_backend_news_order,
                    max_results=settings.bot_search_news_max_results,
                    strategy=settings.bot_search_backend_strategy,
                )
                if not normalized:
                    raise SearchError("No search results found.")
                return normalized
            if mode == "wiki":
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

        normalized = _normalize_search_results(mode=mode, raw_results=raw_results)

        if not normalized:
            raise SearchError("No search results found.")

        return normalized


def _normalize_search_results(
    *, mode: SearchMode, raw_results: list[dict[str, object]]
) -> list[SearchResult]:
    normalized = [
        _normalize_result(mode=mode, result=item)
        for item in raw_results
        if isinstance(item, dict)
    ]
    return [item for item in normalized if item is not None]


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


def _search_mode_with_backends(
    *,
    ddgs: DDGS,
    query: str,
    settings: Settings,
    mode: Literal["search", "news"],
    backends: tuple[str, ...],
    max_results: int,
    strategy: Literal["first_non_empty", "aggregate"],
) -> list[SearchResult]:
    last_exception: Exception | None = None
    attempts = tuple(_dedupe_backends(backends))
    _debug_log(
        settings=settings,
        event="search_backend_chain",
        mode=mode,
        backend_count=len(attempts),
        strategy=strategy,
    )

    aggregate_results: list[SearchResult] = []
    if strategy == "aggregate":
        _debug_log(
            settings=settings,
            event="search_backend_aggregate_begin",
            mode=mode,
            backend_count=len(attempts),
        )

    for backend in attempts:
        try:
            raw_results = _run_backend_search(
                ddgs=ddgs,
                mode=mode,
                query=query,
                settings=settings,
                backend=backend,
                max_results=max_results,
            )
        except (DDGSException, TimeoutException, RatelimitException) as exc:
            last_exception = exc
            _debug_log(
                settings=settings,
                event="search_backend_attempt",
                mode=mode,
                backend=backend,
                status="error",
                reason_code=exc.__class__.__name__,
            )
            continue

        normalized_raw_results = _normalize_raw_results(raw_results)
        normalized = _normalize_search_results(mode=mode, raw_results=normalized_raw_results)
        _debug_log(
            settings=settings,
            event="search_backend_attempt",
            mode=mode,
            backend=backend,
            status="ok" if normalized else "empty",
            result_count=len(normalized),
        )
        if strategy == "first_non_empty":
            if normalized:
                return normalized
            continue

        aggregate_results.extend(normalized)

    if strategy == "aggregate":
        deduped = _dedupe_search_results(aggregate_results)
        capped = deduped[: max(1, max_results)]
        _debug_log(
            settings=settings,
            event="search_backend_aggregate_complete",
            mode=mode,
            merged_count=len(aggregate_results),
            deduped_count=len(deduped),
            returned_count=len(capped),
        )
        if capped:
            return capped

    _debug_log(
        settings=settings,
        event="search_backend_exhausted",
        mode=mode,
        backend_count=len(attempts),
        strategy=strategy,
        reason_code=(
            last_exception.__class__.__name__ if last_exception is not None else "empty"
        ),
    )
    if last_exception is not None:
        raise last_exception
    return []


def _run_backend_search(
    *,
    ddgs: DDGS,
    mode: Literal["search", "news"],
    query: str,
    settings: Settings,
    backend: str,
    max_results: int,
) -> list[dict[str, object]]:
    if mode == "search":
        return ddgs.text(
            query,
            region=settings.bot_search_region,
            safesearch=settings.bot_search_safesearch,
            max_results=max_results,
            backend=backend,
        )
    return ddgs.news(
        query,
        region=settings.bot_search_region,
        safesearch=settings.bot_search_safesearch,
        max_results=max_results,
        backend=backend,
    )


def _normalize_raw_results(raw_results: object) -> list[dict[str, object]]:
    if not isinstance(raw_results, list):
        return []
    cleaned: list[dict[str, object]] = []
    for item in raw_results:
        if isinstance(item, dict):
            cleaned.append(cast(dict[str, object], item))
    return cleaned


def _dedupe_search_results(results: list[SearchResult]) -> list[SearchResult]:
    deduped: list[SearchResult] = []
    seen_urls: set[str] = set()
    for result in results:
        key = result.url.strip()
        if not key or key in seen_urls:
            continue
        deduped.append(result)
        seen_urls.add(key)
    return deduped


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
