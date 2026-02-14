from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from ddgs.exceptions import RatelimitException

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

    def __enter__(self) -> _FakeDDGS:
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        return None

    def text(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("text", query, kwargs))
        return [{"title": "Title", "href": "https://example.com", "body": "snippet"}]

    def news(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("news", query, kwargs))
        return [{"title": "News", "url": "https://news.example", "body": "story"}]

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

    assert text_results[0].url == "https://example.com"
    assert news_results[0].url == "https://news.example"
    assert wiki_results[0].url == "https://example.com"
    assert image_results[0].image_url == "https://img.example/1.jpg"

    assert [call[0] for call in fake.calls] == ["text", "news", "text", "images"]
    assert fake.calls[0][2]["backend"] == "auto"
    assert fake.calls[1][2]["backend"] == "auto"
    assert fake.calls[2][2]["backend"] == "wikipedia"
    assert fake.calls[3][2]["backend"] == "duckduckgo"


@pytest.mark.anyio
async def test_search_client_maps_rate_limit_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _RateLimitDDGS(_FakeDDGS):
        def text(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
            del query, kwargs
            raise RatelimitException("rate")

    monkeypatch.setattr(
        "signal_bot_orx.search_client.DDGS", lambda **_: _RateLimitDDGS()
    )
    client = SearchClient()

    with pytest.raises(SearchError) as exc:
        await client.search("search", "hello", _settings())

    assert "rate-limited" in exc.value.user_message


@pytest.mark.anyio
async def test_search_client_empty_results(monkeypatch: pytest.MonkeyPatch) -> None:
    class _EmptyDDGS(_FakeDDGS):
        def text(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
            del query, kwargs
            return []

    monkeypatch.setattr("signal_bot_orx.search_client.DDGS", lambda **_: _EmptyDDGS())
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
    )

    await client.search("search", "hello", settings)
    await client.search("news", "hello", settings)
    await client.search("wiki", "hello", settings)
    await client.search("images", "hello", settings)

    assert fake.calls[0][2]["backend"] == "google"
    assert fake.calls[1][2]["backend"] == "yahoo"
    assert fake.calls[2][2]["backend"] == "wikipedia"
    assert fake.calls[3][2]["backend"] == "duckduckgo"
