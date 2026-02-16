from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import BackgroundTasks

from signal_bot_orx.chat_context import ChatContextStore
from signal_bot_orx.config import Settings
from signal_bot_orx.dedupe import DedupeCache
from signal_bot_orx.signal_client import SignalClient
from signal_bot_orx.webhook import WebhookHandler


def make_settings(
    weather_api_key: str = "testkey",
    weather_default_location: str = "",
) -> Settings:
    # Minimal settings with weather enabled
    return Settings(
        signal_api_base_url="http://localhost:8080",
        signal_sender_number="+15550001111",
        signal_sender_uuid=None,
        signal_allowed_numbers=frozenset(["+15550002222"]),
        signal_allowed_group_ids=frozenset(),
        openrouter_chat_api_key="sk-or-test",
        openrouter_model="openai/gpt-4o-mini",
        signal_enabled=True,
        signal_disable_auth=False,
        telegram_enabled=False,
        telegram_bot_token=None,
        telegram_webhook_secret=None,
        telegram_allowed_user_ids=frozenset(),
        telegram_allowed_chat_ids=frozenset(),
        telegram_disable_auth=False,
        telegram_bot_username=None,
        whatsapp_enabled=False,
        whatsapp_bridge_base_url=None,
        whatsapp_bridge_token=None,
        whatsapp_allowed_numbers=frozenset(),
        whatsapp_disable_auth=False,
        openrouter_image_api_key=None,
        openrouter_image_model=None,
        openrouter_image_timeout_seconds=90.0,
        openrouter_base_url="https://openrouter.ai/api/v1",
        openrouter_timeout_seconds=45.0,
        openrouter_max_output_tokens=300,
        openrouter_http_referer=None,
        openrouter_app_title=None,
        bot_chat_temperature=0.6,
        bot_chat_context_turns=6,
        bot_chat_context_ttl_seconds=1800,
        bot_chat_system_prompt="You are a bot.",
        bot_chat_force_plain_text=True,
        bot_mention_aliases=("@signalbot", "@bot"),
        bot_max_prompt_chars=700,
        bot_search_enabled=True,
        bot_search_context_mode="no_context",
        bot_search_mode_search_enabled=True,
        bot_search_mode_news_enabled=True,
        bot_search_mode_wiki_enabled=True,
        bot_search_mode_images_enabled=True,
        bot_search_mode_videos_enabled=True,
        bot_search_debug_logging=False,
        bot_search_persona_enabled=False,
        bot_search_use_history_for_summary=False,
        bot_search_region="us-en",
        bot_search_safesearch="moderate",
        bot_search_backend_search="auto",
        bot_search_backend_news="auto",
        bot_search_backend_videos="youtube",
        bot_search_backend_strategy="first_non_empty",
        bot_search_backend_search_order=(
            "duckduckgo",
            "bing",
            "google",
            "yandex",
            "grokipedia",
        ),
        bot_search_backend_news_order=("duckduckgo", "bing", "yahoo"),
        bot_search_backend_wiki="wikipedia",
        bot_search_backend_images="duckduckgo",
        bot_search_text_max_results=5,
        bot_search_news_max_results=5,
        bot_search_wiki_max_results=3,
        bot_search_images_max_results=3,
        bot_search_videos_max_results=5,
        bot_search_timeout_seconds=8.0,
        bot_search_source_ttl_seconds=1800,
        weather_api_key=weather_api_key,
        weather_units="metric",  # valid literal
        weather_default_location=weather_default_location,
        bot_group_reply_mode="group",
        bot_webhook_host="127.0.0.1",
        bot_webhook_port=8001,
    )


def make_handler(
    settings: Settings | None = None, weather_enabled: bool = True
) -> WebhookHandler:
    settings = settings or make_settings()
    signal_client = MagicMock(spec=SignalClient)
    signal_client.send_text = AsyncMock()
    weather_client = MagicMock()
    weather_client.current = AsyncMock(
        return_value={
            "name": "London",
            "sys": {"country": "GB"},
            "weather": [{"description": "light rain"}],
            "main": {"temp": 10.5, "feels_like": 9.0, "humidity": 85},
            "wind": {"speed": 5.5},
        }
    )
    weather_client.forecast = AsyncMock(
        return_value={
            "city": {"name": "Tokyo", "country": "JP"},
            "list": [
                {
                    "dt_txt": "2025-02-16 12:00:00",
                    "weather": [{"description": "sunny"}],
                    "main": {"temp": 15},
                },
                {
                    "dt_txt": "2025-02-17 12:00:00",
                    "weather": [{"description": "cloudy"}],
                    "main": {"temp": 12},
                },
                {
                    "dt_txt": "2025-02-18 12:00:00",
                    "weather": [{"description": "rain"}],
                    "main": {"temp": 10},
                },
                {
                    "dt_txt": "2025-02-19 12:00:00",
                    "weather": [{"description": "storm"}],
                    "main": {"temp": 8},
                },
                {
                    "dt_txt": "2025-02-20 12:00:00",
                    "weather": [{"description": "snow"}],
                    "main": {"temp": 2},
                },
            ],
        }
    )
    if not weather_enabled:
        weather_client = None
    chat_context = ChatContextStore(max_turns=6, ttl_seconds=1800)
    dedupe = DedupeCache(ttl_seconds=300)
    return WebhookHandler(
        settings=settings,
        signal_client=signal_client,
        whatsapp_client=None,
        telegram_client=None,
        openrouter_client=MagicMock(),
        openrouter_image_client=None,
        chat_context=chat_context,
        dedupe=dedupe,
        weather_client=weather_client,
        search_service=None,
    )


def make_signal_webhook(sender: str, text: str, group_id: str | None = None) -> dict:
    envelope = {
        "source": sender,
        "dataMessage": {"message": text, "timestamp": 1},
    }
    if group_id:
        envelope["dataMessage"]["groupInfo"] = {"groupId": group_id}
    return {"envelope": envelope}


async def run_background_tasks(tasks: BackgroundTasks) -> None:
    for task in tasks.tasks:
        func = task.func
        # We rely on the fact that these are coroutines in our usage
        await func(*task.args, **task.kwargs)


@pytest.mark.asyncio
async def test_weather_current_command() -> None:
    handler = make_handler()
    payload = make_signal_webhook(sender="+15550002222", text="/weather London")
    background_tasks = BackgroundTasks()
    result = await handler.handle_webhook(
        payload, background_tasks, transport_hint="signal"
    )
    assert result["status"] == "accepted"
    assert result["reason"] == "weather_queued"
    await run_background_tasks(background_tasks)

    # Cast to MagicMock for type checking
    signal_client = cast(MagicMock, handler._signal_client)
    signal_client.send_text.assert_awaited_once()
    _, kwargs = signal_client.send_text.call_args
    reply_text = kwargs["message"]
    assert "Weather for London" in reply_text
    assert "10.5°C" in reply_text


@pytest.mark.asyncio
async def test_weather_forecast_command() -> None:
    handler = make_handler()
    payload = make_signal_webhook(sender="+15550002222", text="/forecast Tokyo")
    background_tasks = BackgroundTasks()
    result = await handler.handle_webhook(
        payload, background_tasks, transport_hint="signal"
    )
    assert result["status"] == "accepted"
    assert result["reason"] == "forecast_queued"
    await run_background_tasks(background_tasks)

    signal_client = cast(MagicMock, handler._signal_client)
    signal_client.send_text.assert_awaited_once()
    _, kwargs = signal_client.send_text.call_args
    reply_text = kwargs["message"]
    assert "5-day forecast for Tokyo" in reply_text


@pytest.mark.asyncio
async def test_weather_missing_location_uses_default() -> None:
    settings = make_settings(weather_default_location="Paris")
    handler = make_handler(settings=settings)
    payload = make_signal_webhook(sender="+15550002222", text="/weather")
    background_tasks = BackgroundTasks()
    result = await handler.handle_webhook(
        payload, background_tasks, transport_hint="signal"
    )
    assert result["status"] == "accepted"
    assert result["reason"] == "weather_queued"
    await run_background_tasks(background_tasks)

    signal_client = cast(MagicMock, handler._signal_client)
    signal_client.send_text.assert_awaited_once()

    weather_client = cast(MagicMock, handler._weather_client)
    weather_client.current.assert_awaited_with("Paris")

    _, kwargs = signal_client.send_text.call_args
    reply_text = kwargs["message"]
    # Mock returns London data regardless of input
    assert "Weather for London" in reply_text


@pytest.mark.asyncio
async def test_weather_disabled_when_no_client() -> None:
    handler = make_handler(weather_enabled=False)
    payload = make_signal_webhook(sender="+15550002222", text="/weather London")
    background_tasks = BackgroundTasks()
    result = await handler.handle_webhook(
        payload, background_tasks, transport_hint="signal"
    )
    assert result["status"] == "accepted"
    assert result["reason"] == "weather_disabled"
    await run_background_tasks(background_tasks)

    signal_client = cast(MagicMock, handler._signal_client)
    signal_client.send_text.assert_awaited_once()
    _, kwargs = signal_client.send_text.call_args
    reply_text = kwargs["message"]
    assert "Weather is not configured on this bot." in reply_text
