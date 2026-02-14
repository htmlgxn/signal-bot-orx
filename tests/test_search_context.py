from __future__ import annotations

import pytest

from signal_bot_orx.search_client import SearchResult
from signal_bot_orx.search_context import SearchContextStore


def _result(*, title: str, url: str, snippet: str = "") -> SearchResult:
    return SearchResult(
        mode="search",
        title=title,
        url=url,
        snippet=snippet,
    )


def test_search_context_returns_recent_sources_for_empty_claim() -> None:
    store = SearchContextStore(ttl_seconds=1800)
    store.remember_results(
        "group:1",
        mode="search",
        results=[
            _result(title="First", url="https://a.example"),
            _result(title="Second", url="https://b.example"),
        ],
    )

    found = store.find_sources("group:1", "", limit=2)

    assert [item.url for item in found] == ["https://b.example", "https://a.example"]


def test_search_context_fuzzy_match_prefers_overlap() -> None:
    store = SearchContextStore(ttl_seconds=1800)
    store.remember_results(
        "group:1",
        mode="search",
        results=[
            _result(
                title="OpenRouter docs",
                url="https://openrouter.ai/docs",
                snippet="Authentication and models",
            ),
            _result(
                title="Other result",
                url="https://example.com",
                snippet="Unrelated topic",
            ),
        ],
    )

    found = store.find_sources("group:1", "source for openrouter auth", limit=1)

    assert len(found) == 1
    assert found[0].url == "https://openrouter.ai/docs"


def test_search_context_expires_records_by_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 0.0

    def fake_monotonic() -> float:
        return now

    monkeypatch.setattr("signal_bot_orx.search_context.time.monotonic", fake_monotonic)
    store = SearchContextStore(ttl_seconds=5)

    store.remember_results(
        "group:1",
        mode="search",
        results=[_result(title="First", url="https://a.example")],
    )
    assert store.find_sources("group:1", "", limit=1)
    assert store.recent_records("group:1", limit=1)

    now = 6.0
    assert store.find_sources("group:1", "", limit=1) == []
    assert store.recent_records("group:1", limit=1) == []


def test_search_context_recent_records_returns_newest_first() -> None:
    store = SearchContextStore(ttl_seconds=1800)
    store.remember_results(
        "group:1",
        mode="search",
        results=[
            _result(title="First", url="https://a.example"),
            _result(title="Second", url="https://b.example"),
            _result(title="Third", url="https://c.example"),
        ],
    )

    found = store.recent_records("group:1", limit=2)

    assert [item.url for item in found] == ["https://c.example", "https://b.example"]


def test_search_context_pending_followup_lifecycle() -> None:
    store = SearchContextStore(ttl_seconds=1800)
    store.set_pending_followup(
        "group:1",
        original_prompt="who is he in islam",
        template_prompt="who is {subject} in islam",
        reason="low_confidence",
    )

    pending = store.get_pending_followup("group:1")
    assert pending is not None
    assert pending.original_prompt == "who is he in islam"
    assert pending.template_prompt == "who is {subject} in islam"
    assert pending.reason == "low_confidence"
    assert pending.attempts == 0

    attempts = store.bump_pending_attempt("group:1")
    assert attempts == 1
    pending = store.get_pending_followup("group:1")
    assert pending is not None
    assert pending.attempts == 1

    store.clear_pending_followup("group:1")
    assert store.get_pending_followup("group:1") is None


def test_search_context_pending_followup_expires_by_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 0.0

    def fake_monotonic() -> float:
        return now

    monkeypatch.setattr("signal_bot_orx.search_context.time.monotonic", fake_monotonic)
    store = SearchContextStore(ttl_seconds=5)

    store.set_pending_followup(
        "group:1",
        original_prompt="who is he in islam",
        template_prompt="who is {subject} in islam",
        reason="low_confidence",
    )
    assert store.get_pending_followup("group:1") is not None

    now = 6.0
    assert store.get_pending_followup("group:1") is None


def test_search_context_pending_video_selection_lifecycle() -> None:
    store = SearchContextStore(ttl_seconds=1800)
    store.set_pending_video_selection(
        "group:1",
        query="nick land interview",
        results=[
            SearchResult(
                mode="videos",
                title="First video",
                url="https://youtube.com/watch?v=abc123",
                snippet="",
                image_url="https://img.example/thumb.jpg",
            )
        ],
    )

    pending = store.get_pending_video_selection("group:1")
    assert pending is not None
    assert pending.query == "nick land interview"
    assert len(pending.results) == 1
    assert pending.results[0].title == "First video"

    store.clear_pending_video_selection("group:1")
    assert store.get_pending_video_selection("group:1") is None


def test_search_context_pending_video_selection_expires_by_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 0.0

    def fake_monotonic() -> float:
        return now

    monkeypatch.setattr("signal_bot_orx.search_context.time.monotonic", fake_monotonic)
    store = SearchContextStore(ttl_seconds=5)
    store.set_pending_video_selection(
        "group:1",
        query="nick land interview",
        results=[
            SearchResult(
                mode="videos",
                title="First video",
                url="https://youtube.com/watch?v=abc123",
                snippet="",
                image_url="https://img.example/thumb.jpg",
            )
        ],
    )
    assert store.get_pending_video_selection("group:1") is not None

    now = 6.0
    assert store.get_pending_video_selection("group:1") is None
