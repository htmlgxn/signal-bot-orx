from __future__ import annotations

from dataclasses import replace

import pytest
from orx_search.base import SearchResult as ProviderSearchResult

from signal_bot_orx.config import Settings
from signal_bot_orx.search_client import SearchClient, SearchError


def _settings() -> Settings:
    return Settings(
        signal_api_base_url="http://localhost:8080",
        signal_sender_number="+15550001111",
        signal_sender_uuid=None,
        signal_allowed_numbers=frozenset({"+15550002222"}),
        signal_allowed_group_ids=frozenset({"group-1"}),
        openrouter_chat_api_key="or-key-chat",
        openrouter_model="openai/gpt-4o-mini",
    )


class _Provider:
    name = ""
    calls: list[tuple[str, str]]

    def __init__(self) -> None:
        pass

    def search(self, query: str) -> list[ProviderSearchResult]:
        raise NotImplementedError


def _provider_class(
    *,
    name: str,
    calls: list[tuple[str, str]],
    results: list[ProviderSearchResult] | None = None,
    error: Exception | None = None,
) -> type[_Provider]:
    class Provider(_Provider):
        def search(self, query: str) -> list[ProviderSearchResult]:
            calls.append((name, query))
            if error is not None:
                raise error
            return list(results or [])

    Provider.name = name
    Provider.calls = calls
    return Provider


@pytest.mark.anyio
async def test_search_client_routes_modes_and_backend_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []
    providers = {
        "duckduckgo": _provider_class(
            name="duckduckgo",
            calls=calls,
            results=[
                ProviderSearchResult(
                    title="Search",
                    url="https://search.example",
                    snippet="snippet",
                )
            ],
        ),
        "bing": _provider_class(name="bing", calls=calls, results=[]),
        "yahoo": _provider_class(name="yahoo", calls=calls, results=[]),
        "wikipedia": _provider_class(
            name="wikipedia",
            calls=calls,
            results=[
                ProviderSearchResult(
                    title="Wiki",
                    url="https://wikipedia.org/wiki/Test",
                    snippet="wiki",
                )
            ],
        ),
        "duckduckgo_images": _provider_class(
            name="duckduckgo_images",
            calls=calls,
            results=[
                ProviderSearchResult(
                    title="Image",
                    url="https://images.example",
                    snippet="image",
                    image_url="https://img.example/1.jpg",
                )
            ],
        ),
        "youtube_videos": _provider_class(
            name="youtube_videos",
            calls=calls,
            results=[
                ProviderSearchResult(
                    title="Video",
                    url="https://youtube.com/watch?v=abc123",
                    snippet="video",
                    image_url="https://img.example/v-small.jpg",
                )
            ],
        ),
    }
    monkeypatch.setattr(
        "signal_bot_orx.search_client.get_provider", lambda name: providers[name]
    )
    client = SearchClient()
    settings = _settings()

    text_results = await client.search("search", "hello", settings)
    news_results = await client.search("news", "hello", settings)
    wiki_results = await client.search("wiki", "hello", settings)
    image_results = await client.search("images", "hello", settings)
    video_results = await client.search("videos", "hello", settings)

    assert text_results[0].url == "https://search.example"
    assert news_results[0].url == "https://search.example"
    assert wiki_results[0].url == "https://wikipedia.org/wiki/Test"
    assert image_results[0].image_url == "https://img.example/1.jpg"
    assert video_results[0].url == "https://youtube.com/watch?v=abc123"
    assert video_results[0].thumbnail_url == "https://img.example/v-small.jpg"
    assert calls == [
        ("duckduckgo", "hello"),
        ("duckduckgo", "hello"),
        ("wikipedia", "hello"),
        ("duckduckgo_images", "hello"),
        ("youtube_videos", "hello"),
    ]


@pytest.mark.anyio
async def test_search_client_uses_configured_backends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []
    providers = {
        "google": _provider_class(
            name="google",
            calls=calls,
            results=[
                ProviderSearchResult(title="G", url="https://g.example", snippet="g")
            ],
        ),
        "yahoo": _provider_class(
            name="yahoo",
            calls=calls,
            results=[
                ProviderSearchResult(title="Y", url="https://y.example", snippet="y")
            ],
        ),
        "wikipedia": _provider_class(
            name="wikipedia",
            calls=calls,
            results=[
                ProviderSearchResult(title="W", url="https://w.example", snippet="w")
            ],
        ),
        "duckduckgo_images": _provider_class(
            name="duckduckgo_images",
            calls=calls,
            results=[
                ProviderSearchResult(title="I", url="https://i.example", snippet="i")
            ],
        ),
        "youtube_videos": _provider_class(
            name="youtube_videos",
            calls=calls,
            results=[
                ProviderSearchResult(title="V", url="https://v.example", snippet="v")
            ],
        ),
    }
    monkeypatch.setattr(
        "signal_bot_orx.search_client.get_provider", lambda name: providers[name]
    )
    client = SearchClient()
    settings = replace(
        _settings(),
        bot_search_backend_search="google",
        bot_search_backend_news="yahoo",
        bot_search_backend_wiki="wikipedia",
        bot_search_backend_images="duckduckgo",
        bot_search_backend_videos="youtube",
        bot_search_backend_search_order=("google",),
        bot_search_backend_news_order=("yahoo",),
    )

    await client.search("search", "hello", settings)
    await client.search("news", "hello", settings)
    await client.search("wiki", "hello", settings)
    await client.search("images", "hello", settings)
    await client.search("videos", "hello", settings)

    assert calls == [
        ("google", "hello"),
        ("yahoo", "hello"),
        ("wikipedia", "hello"),
        ("duckduckgo_images", "hello"),
        ("youtube_videos", "hello"),
    ]


@pytest.mark.anyio
async def test_search_client_first_non_empty_uses_next_backend_on_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []
    providers = {
        "duckduckgo": _provider_class(name="duckduckgo", calls=calls, results=[]),
        "bing": _provider_class(
            name="bing",
            calls=calls,
            results=[
                ProviderSearchResult(
                    title="Bing",
                    url="https://bing.example",
                    snippet="b",
                )
            ],
        ),
        "google": _provider_class(name="google", calls=calls, results=[]),
        "yandex": _provider_class(name="yandex", calls=calls, results=[]),
        "grokipedia": _provider_class(name="grokipedia", calls=calls, results=[]),
    }
    monkeypatch.setattr(
        "signal_bot_orx.search_client.get_provider", lambda name: providers[name]
    )
    client = SearchClient()

    results = await client.search("search", "hello", _settings())

    assert results[0].url == "https://bing.example"
    assert calls[:2] == [("duckduckgo", "hello"), ("bing", "hello")]


@pytest.mark.anyio
async def test_search_client_aggregate_queries_all_backends_and_caps_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []
    providers = {
        "duckduckgo": _provider_class(
            name="duckduckgo",
            calls=calls,
            results=[
                ProviderSearchResult(
                    title="One",
                    url="https://shared.example",
                    snippet="ddg-1",
                ),
                ProviderSearchResult(
                    title="Two",
                    url="https://ddg-only.example",
                    snippet="ddg-2",
                ),
            ],
        ),
        "bing": _provider_class(
            name="bing",
            calls=calls,
            results=[
                ProviderSearchResult(
                    title="Three",
                    url="https://shared.example",
                    snippet="bing-1",
                ),
                ProviderSearchResult(
                    title="Four",
                    url="https://bing-only.example",
                    snippet="bing-2",
                ),
            ],
        ),
        "google": _provider_class(
            name="google",
            calls=calls,
            results=[
                ProviderSearchResult(
                    title="Five",
                    url="https://google-only.example",
                    snippet="g-1",
                )
            ],
        ),
        "yandex": _provider_class(name="yandex", calls=calls, results=[]),
        "grokipedia": _provider_class(name="grokipedia", calls=calls, results=[]),
    }
    monkeypatch.setattr(
        "signal_bot_orx.search_client.get_provider", lambda name: providers[name]
    )
    client = SearchClient()
    settings = replace(
        _settings(),
        bot_search_backend_strategy="aggregate",
        bot_search_text_max_results=3,
    )

    results = await client.search("search", "hello", settings)

    assert [item.url for item in results] == [
        "https://shared.example",
        "https://ddg-only.example",
        "https://bing-only.example",
    ]
    assert [name for name, _query in calls] == [
        "duckduckgo",
        "bing",
        "google",
        "yandex",
        "grokipedia",
    ]


@pytest.mark.anyio
async def test_search_client_aggregate_tolerates_partial_backend_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []
    providers = {
        "duckduckgo": _provider_class(
            name="duckduckgo",
            calls=calls,
            error=RuntimeError("down"),
        ),
        "bing": _provider_class(
            name="bing",
            calls=calls,
            results=[
                ProviderSearchResult(
                    title="B",
                    url="https://bing-only.example",
                    snippet="b",
                )
            ],
        ),
        "google": _provider_class(name="google", calls=calls, results=[]),
        "yandex": _provider_class(name="yandex", calls=calls, results=[]),
        "grokipedia": _provider_class(name="grokipedia", calls=calls, results=[]),
    }
    monkeypatch.setattr(
        "signal_bot_orx.search_client.get_provider", lambda name: providers[name]
    )
    client = SearchClient()
    settings = replace(
        _settings(),
        bot_search_backend_strategy="aggregate",
    )

    results = await client.search("search", "hello", settings)

    assert [item.url for item in results] == ["https://bing-only.example"]


@pytest.mark.anyio
async def test_search_client_raises_when_all_backends_fail_or_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []
    providers = {
        "duckduckgo": _provider_class(
            name="duckduckgo",
            calls=calls,
            error=RuntimeError("down"),
        ),
        "bing": _provider_class(
            name="bing",
            calls=calls,
            error=RuntimeError("down"),
        ),
        "google": _provider_class(
            name="google",
            calls=calls,
            error=RuntimeError("down"),
        ),
        "yandex": _provider_class(
            name="yandex",
            calls=calls,
            error=RuntimeError("down"),
        ),
        "grokipedia": _provider_class(
            name="grokipedia",
            calls=calls,
            error=RuntimeError("down"),
        ),
    }
    monkeypatch.setattr(
        "signal_bot_orx.search_client.get_provider", lambda name: providers[name]
    )
    client = SearchClient()
    settings = replace(
        _settings(),
        bot_search_backend_strategy="aggregate",
    )

    with pytest.raises(SearchError) as exc:
        await client.search("search", "hello", settings)

    assert exc.value.user_message == "No search results found."


@pytest.mark.anyio
async def test_search_client_rejects_empty_query() -> None:
    with pytest.raises(SearchError) as exc:
        await SearchClient().search("search", "   ", _settings())
    assert exc.value.user_message == "Search query is empty."
