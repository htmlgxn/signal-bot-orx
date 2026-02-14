from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from ddgs.exceptions import DDGSException, RatelimitException

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


class _FakeDDGS:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.text_responses_by_backend: dict[str, list[dict[str, Any]]] = {
            "auto": [
                {"title": "Title", "href": "https://example.com", "body": "snippet"}
            ],
            "duckduckgo": [
                {"title": "Title", "href": "https://example.com", "body": "snippet"}
            ],
            "bing": [{"title": "Bing", "href": "https://bing.example", "body": "b"}],
            "google": [
                {"title": "Google", "href": "https://google.example", "body": "g"}
            ],
            "yandex": [
                {"title": "Yandex", "href": "https://yandex.example", "body": "y"}
            ],
            "grokipedia": [
                {
                    "title": "Grokipedia",
                    "href": "https://grokipedia.example",
                    "body": "k",
                }
            ],
            "wikipedia": [
                {
                    "title": "Wikipedia",
                    "href": "https://wikipedia.org/wiki/Test",
                    "body": "wiki",
                }
            ],
        }
        self.news_responses_by_backend: dict[str, list[dict[str, Any]]] = {
            "auto": [{"title": "News", "url": "https://news.example", "body": "story"}],
            "duckduckgo": [
                {"title": "DDG", "url": "https://ddgnews.example", "body": "ddg"}
            ],
            "bing": [{"title": "Bing", "url": "https://bingnews.example", "body": "b"}],
            "yahoo": [
                {"title": "Yahoo", "url": "https://yahoonews.example", "body": "y"}
            ],
        }
        self.video_responses_by_backend: dict[str, list[dict[str, Any]]] = {
            "youtube": [
                {
                    "title": "Video",
                    "content": "https://youtube.com/watch?v=abc123",
                    "description": "desc",
                    "published": "2026-01-01",
                    "publisher": "Example Channel",
                    "images": {
                        "0": "https://img.example/v-small.jpg",
                        "1": "https://img.example/v-large.jpg",
                    },
                }
            ]
        }
        self.text_errors_by_backend: dict[str, Exception] = {}
        self.news_errors_by_backend: dict[str, Exception] = {}
        self.video_errors_by_backend: dict[str, Exception] = {}

    def __enter__(self) -> _FakeDDGS:
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        return None

    def text(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("text", query, kwargs))
        backend = str(kwargs.get("backend", "auto"))
        if error := self.text_errors_by_backend.get(backend):
            raise error
        return list(self.text_responses_by_backend.get(backend, []))

    def news(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("news", query, kwargs))
        backend = str(kwargs.get("backend", "auto"))
        if error := self.news_errors_by_backend.get(backend):
            raise error
        return list(self.news_responses_by_backend.get(backend, []))

    def images(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("images", query, kwargs))
        return [
            {
                "title": "Image",
                "image": "https://img.example/1.jpg",
                "url": "https://page.example/1",
                "source": "Example",
            }
        ]

    def videos(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("videos", query, kwargs))
        backend = str(kwargs.get("backend", "youtube"))
        if error := self.video_errors_by_backend.get(backend):
            raise error
        return list(self.video_responses_by_backend.get(backend, []))


@pytest.mark.anyio
async def test_search_client_routes_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeDDGS()
    monkeypatch.setattr("signal_bot_orx.search_client.DDGS", lambda **_: fake)
    client = SearchClient()
    settings = _settings()

    text_results = await client.search("search", "hello", settings)
    news_results = await client.search("news", "hello", settings)
    wiki_results = await client.search("wiki", "hello", settings)
    image_results = await client.search("images", "hello", settings)
    video_results = await client.search("videos", "hello", settings)

    assert text_results[0].url == "https://example.com"
    assert news_results[0].url == "https://ddgnews.example"
    assert wiki_results[0].url == "https://wikipedia.org/wiki/Test"
    assert image_results[0].image_url == "https://img.example/1.jpg"
    assert video_results[0].url == "https://youtube.com/watch?v=abc123"
    assert video_results[0].image_url == "https://img.example/v-small.jpg"

    assert [call[0] for call in fake.calls] == [
        "text",
        "news",
        "text",
        "images",
        "videos",
    ]
    assert fake.calls[0][2]["backend"] == "duckduckgo"
    assert fake.calls[1][2]["backend"] == "duckduckgo"
    assert fake.calls[2][2]["backend"] == "wikipedia"
    assert fake.calls[3][2]["backend"] == "duckduckgo"
    assert fake.calls[4][2]["backend"] == "youtube"


@pytest.mark.anyio
async def test_search_client_maps_rate_limit_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeDDGS()
    fake.text_errors_by_backend = {
        "duckduckgo": RatelimitException("rate"),
        "bing": RatelimitException("rate"),
        "google": RatelimitException("rate"),
        "yandex": RatelimitException("rate"),
        "grokipedia": RatelimitException("rate"),
    }
    monkeypatch.setattr("signal_bot_orx.search_client.DDGS", lambda **_: fake)
    client = SearchClient()

    with pytest.raises(SearchError) as exc:
        await client.search("search", "hello", _settings())

    assert "rate-limited" in exc.value.user_message


@pytest.mark.anyio
async def test_search_client_empty_results(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeDDGS()
    fake.text_responses_by_backend = {
        "duckduckgo": [],
        "bing": [],
        "google": [],
        "yandex": [],
        "grokipedia": [],
    }
    monkeypatch.setattr("signal_bot_orx.search_client.DDGS", lambda **_: fake)
    client = SearchClient()

    with pytest.raises(SearchError) as exc:
        await client.search("search", "hello", _settings())

    assert exc.value.user_message == "No search results found."


@pytest.mark.anyio
async def test_search_client_uses_configured_backends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeDDGS()
    monkeypatch.setattr("signal_bot_orx.search_client.DDGS", lambda **_: fake)
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

    assert fake.calls[0][2]["backend"] == "google"
    assert fake.calls[1][2]["backend"] == "yahoo"
    assert fake.calls[2][2]["backend"] == "wikipedia"
    assert fake.calls[3][2]["backend"] == "duckduckgo"
    assert fake.calls[4][2]["backend"] == "youtube"


@pytest.mark.anyio
async def test_search_client_search_fallback_uses_next_backend_on_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeDDGS()
    fake.text_responses_by_backend = {
        "duckduckgo": [],
        "bing": [{"title": "Bing", "href": "https://bing.example", "body": "b"}],
    }
    monkeypatch.setattr("signal_bot_orx.search_client.DDGS", lambda **_: fake)
    client = SearchClient()

    results = await client.search("search", "hello", _settings())

    assert results[0].url == "https://bing.example"
    assert [call[2]["backend"] for call in fake.calls if call[0] == "text"][:2] == [
        "duckduckgo",
        "bing",
    ]


@pytest.mark.anyio
async def test_search_client_news_fallback_uses_next_backend_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeDDGS()
    fake.news_errors_by_backend = {"duckduckgo": DDGSException("fail")}
    fake.news_responses_by_backend = {
        "duckduckgo": [],
        "bing": [{"title": "Bing", "url": "https://bingnews.example", "body": "b"}],
    }
    monkeypatch.setattr("signal_bot_orx.search_client.DDGS", lambda **_: fake)
    client = SearchClient()

    results = await client.search("news", "hello", _settings())

    assert results[0].url == "https://bingnews.example"
    assert [call[2]["backend"] for call in fake.calls if call[0] == "news"][:2] == [
        "duckduckgo",
        "bing",
    ]


@pytest.mark.anyio
async def test_search_client_aggregate_queries_all_backends_and_caps_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeDDGS()
    fake.text_responses_by_backend = {
        "duckduckgo": [
            {"title": "One", "href": "https://shared.example", "body": "ddg-1"},
            {"title": "Two", "href": "https://ddg-only.example", "body": "ddg-2"},
        ],
        "bing": [
            {"title": "Three", "href": "https://shared.example", "body": "bing-1"},
            {"title": "Four", "href": "https://bing-only.example", "body": "bing-2"},
        ],
        "google": [
            {"title": "Five", "href": "https://google-only.example", "body": "g-1"},
        ],
        "yandex": [],
        "grokipedia": [],
    }
    monkeypatch.setattr("signal_bot_orx.search_client.DDGS", lambda **_: fake)
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
    assert [call[2]["backend"] for call in fake.calls if call[0] == "text"] == [
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
    fake = _FakeDDGS()
    fake.text_errors_by_backend = {"duckduckgo": DDGSException("down")}
    fake.text_responses_by_backend = {
        "duckduckgo": [],
        "bing": [{"title": "B", "href": "https://bing-only.example", "body": "b"}],
        "google": [],
        "yandex": [],
        "grokipedia": [],
    }
    monkeypatch.setattr("signal_bot_orx.search_client.DDGS", lambda **_: fake)
    client = SearchClient()
    settings = replace(
        _settings(),
        bot_search_backend_strategy="aggregate",
    )

    results = await client.search("search", "hello", settings)

    assert [item.url for item in results] == ["https://bing-only.example"]


@pytest.mark.anyio
async def test_search_client_aggregate_raises_error_when_all_backends_fail_or_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeDDGS()
    fake.text_errors_by_backend = {
        "duckduckgo": DDGSException("down"),
        "bing": DDGSException("down"),
        "google": DDGSException("down"),
        "yandex": DDGSException("down"),
        "grokipedia": DDGSException("down"),
    }
    monkeypatch.setattr("signal_bot_orx.search_client.DDGS", lambda **_: fake)
    client = SearchClient()
    settings = replace(
        _settings(),
        bot_search_backend_strategy="aggregate",
    )

    with pytest.raises(SearchError):
        await client.search("search", "hello", settings)


@pytest.mark.anyio
async def test_search_client_video_empty_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeDDGS()
    fake.video_responses_by_backend = {"youtube": []}
    monkeypatch.setattr("signal_bot_orx.search_client.DDGS", lambda **_: fake)
    client = SearchClient()

    with pytest.raises(SearchError) as exc:
        await client.search("videos", "hello", _settings())

    assert exc.value.user_message == "No search results found."


@pytest.mark.anyio
async def test_search_client_video_uses_images_list_index_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeDDGS()
    fake.video_responses_by_backend = {
        "youtube": [
            {
                "title": "Video",
                "content": "https://youtube.com/watch?v=abc123",
                "images": [
                    "https://img.example/list-0.jpg",
                    "https://img.example/list-1.jpg",
                ],
            }
        ]
    }
    monkeypatch.setattr("signal_bot_orx.search_client.DDGS", lambda **_: fake)
    client = SearchClient()

    results = await client.search("videos", "hello", _settings())

    assert results[0].image_url == "https://img.example/list-0.jpg"


@pytest.mark.anyio
async def test_search_client_video_falls_back_to_images_one_then_thumbnail_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeDDGS()
    fake.video_responses_by_backend = {
        "youtube": [
            {
                "title": "Video",
                "content": "https://youtube.com/watch?v=abc123",
                "images": {"1": "https://img.example/large.jpg"},
                "thumbnail_url": "https://img.example/thumb-url.jpg",
            }
        ]
    }
    monkeypatch.setattr("signal_bot_orx.search_client.DDGS", lambda **_: fake)
    client = SearchClient()

    results = await client.search("videos", "hello", _settings())

    assert results[0].image_url == "https://img.example/large.jpg"


@pytest.mark.anyio
async def test_search_client_video_allows_missing_thumbnail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeDDGS()
    fake.video_responses_by_backend = {
        "youtube": [
            {
                "title": "Video",
                "content": "https://youtube.com/watch?v=abc123",
                "images": {"0": "not-a-url"},
            }
        ]
    }
    monkeypatch.setattr("signal_bot_orx.search_client.DDGS", lambda **_: fake)
    client = SearchClient()

    results = await client.search("videos", "hello", _settings())

    assert results[0].url == "https://youtube.com/watch?v=abc123"
    assert results[0].image_url is None
