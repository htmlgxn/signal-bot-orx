import asyncio
import logging
from dataclasses import dataclass
from typing import Literal

import orx_search.providers  # noqa: F401
from orx_search.registry import get_provider

from signal_bot_orx.config import Settings

SearchMode = Literal[
    "search",
    "news",
    "wiki",
    "images",
    "videos",
    "jmail",
    "lolcow_cyraxx",
    "lolcow_larson",
]
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
    thumbnail_url: str | None = None


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
        except Exception as exc:
            if isinstance(exc, SearchError):
                raise
            logger.exception("Search failed")
            raise SearchError(f"Search failed: {exc}") from exc

    def _search_sync(
        self,
        mode: SearchMode,
        query: str,
        settings: Settings,
    ) -> list[SearchResult]:
        # Determine providers based on mode and settings
        provider_names: list[str] = []
        if mode == "search":
            provider_names = list(settings.bot_search_backend_search_order)
        elif mode == "news":
            provider_names = list(settings.bot_search_backend_news_order)
        elif mode == "wiki":
            provider_names = [settings.bot_search_backend_wiki]
        elif mode == "images":
            # Map legacy 'duckduckgo' to 'duckduckgo_images' if needed
            backend = settings.bot_search_backend_images
            if backend == "duckduckgo":
                provider_names = ["duckduckgo_images"]
            else:
                provider_names = [backend]
        elif mode == "videos":
            backend = settings.bot_search_backend_videos
            if backend == "duckduckgo":
                provider_names = ["duckduckgo_videos"]
            elif backend == "youtube":
                provider_names = ["youtube_videos"]
            else:
                provider_names = [backend]
        elif mode == "jmail":
            provider_names = [settings.bot_search_backend_jmail]
        elif mode == "lolcow_cyraxx":
            provider_names = [settings.bot_search_backend_lolcow_cyraxx]
        elif mode == "lolcow_larson":
            provider_names = [settings.bot_search_backend_lolcow_larson]

        # Flatten comma-separated strings (common in env vars)
        final_names: list[str] = []
        for name in provider_names:
            if "," in name:
                final_names.extend(s.strip() for s in name.split(",") if s.strip())
            elif name.strip():
                final_names.append(name.strip())
        provider_names = final_names

        strategy = settings.bot_search_backend_strategy
        max_results = 5
        if mode == "search":
            max_results = settings.bot_search_text_max_results
        elif mode == "news":
            max_results = settings.bot_search_news_max_results
        elif mode == "images":
            max_results = settings.bot_search_images_max_results
        elif mode == "videos":
            max_results = settings.bot_search_videos_max_results
        elif mode == "wiki":
            max_results = settings.bot_search_wiki_max_results
        elif mode == "jmail":
            max_results = settings.bot_search_jmail_max_results
        elif mode == "lolcow_cyraxx":
            max_results = settings.bot_search_lolcow_cyraxx_max_results
        elif mode == "lolcow_larson":
            max_results = settings.bot_search_lolcow_larson_max_results

        all_results: list[SearchResult] = []
        for name in provider_names:
            try:
                provider_cls = get_provider(name)
                provider = provider_cls()

                # Execute search
                orx_results = provider.search(query)

                # Map to bot's SearchResult
                mapped = [
                    SearchResult(
                        mode=mode,
                        title=res.title,
                        url=res.url,
                        snippet=res.snippet,
                        source=res.source,
                        date=res.date,
                        image_url=res.image_url,
                        thumbnail_url=res.image_url,
                    )
                    for res in orx_results
                ]

                if strategy == "first_non_empty":
                    if mapped:
                        return mapped[:max_results]
                else:
                    all_results.extend(mapped)

            except Exception:
                logger.warning("Provider %s failed", name, exc_info=True)
                continue

        if not all_results:
            raise SearchError("No search results found.")

        # Deduplicate by URL
        seen_urls = set()
        deduped = []
        for res in all_results:
            if res.url not in seen_urls:
                deduped.append(res)
                seen_urls.add(res.url)

        return deduped[:max_results]
