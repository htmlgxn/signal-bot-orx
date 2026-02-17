"""YouTube videos search engine provider."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Generator, Mapping
from typing import Any

from orx_search.base import SearchResult
from orx_search.http_client import HttpClient
from orx_search.registry import register

logger = logging.getLogger(__name__)

_YT_INITIAL_DATA_RE = re.compile(r"ytInitialData\s*=\s*(\{.*?\});", re.DOTALL)


def _pick_text(value: object) -> str:
    """Extract text from YouTube's nested text objects."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if isinstance(value.get("simpleText"), str):
            return value["simpleText"]
        runs = value.get("runs")
        if isinstance(runs, list):
            return "".join(
                run.get("text", "") for run in runs if isinstance(run, dict)
            ).strip()
    return ""


def _extract_yt_initial_data(html_text: str) -> dict[str, Any]:
    """Extract ytInitialData JSON from YouTube HTML."""
    match = _YT_INITIAL_DATA_RE.search(html_text)
    if not match:
        return {}
    try:
        return json.loads(match.group(1))
    except Exception:
        logger.debug("Failed to parse ytInitialData")
        return {}


def _iter_video_renderers(obj: object) -> Generator[dict[str, Any]]:
    """Recursively find videoRenderer objects in YouTube data."""
    if isinstance(obj, Mapping):
        video_renderer = obj.get("videoRenderer")
        if isinstance(video_renderer, Mapping):
            yield dict(video_renderer)
        for value in obj.values():
            yield from _iter_video_renderers(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _iter_video_renderers(value)


@register
class YouTubeVideosProvider:
    """YouTube video search by parsing embedded ytInitialData JSON."""

    name = "youtube_videos"

    def __init__(self, proxy: str | None = None) -> None:
        self._http_client = HttpClient(
            headers={
                "Accept-Language": "en-US,en;q=0.9",
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
                    " (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
            },
            proxy=proxy,
        )

    def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        params = {"search_query": query}

        try:
            resp = self._http_client.get(
                "https://www.youtube.com/results", params=params
            )
        except Exception:
            logger.exception("YouTube search request failed")
            return []

        if not resp.content:
            return []

        data = _extract_yt_initial_data(resp.text)
        if not data:
            return []

        results: list[SearchResult] = []
        for item in _iter_video_renderers(data):
            if len(results) >= limit:
                break

            video_id = item.get("videoId")
            if not video_id:
                continue

            title = _pick_text(item.get("title"))
            description = _pick_text(item.get("descriptionSnippet"))
            duration = _pick_text(item.get("lengthText"))
            published = _pick_text(item.get("publishedTimeText"))
            uploader = _pick_text(item.get("ownerText"))
            views = _pick_text(item.get("viewCountText"))

            content_url = f"https://www.youtube.com/watch?v={video_id}"

            snippet_parts = []
            if uploader:
                snippet_parts.append(f"by {uploader}")
            if duration:
                snippet_parts.append(f"[{duration}]")
            if published:
                snippet_parts.append(f"({published})")
            if views:
                snippet_parts.append(f"- {views}")
            if description:
                snippet_parts.append(f"| {description}")

            results.append(
                SearchResult(
                    title=title,
                    url=content_url,
                    snippet=" ".join(snippet_parts),
                    source="YouTube",
                )
            )

        return results
