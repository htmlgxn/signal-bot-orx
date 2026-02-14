from __future__ import annotations

import pytest

from signal_bot_orx.chat_prompt import DEFAULT_CHAT_SYSTEM_PROMPT
from signal_bot_orx.config import (
    DEFAULT_MENTION_ALIASES,
    DEFAULT_OPENROUTER_MODEL,
    Settings,
)


@pytest.fixture(autouse=True)
def clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    keys = [
        "SIGNAL_API_BASE_URL",
        "SIGNAL_SENDER_NUMBER",
        "SIGNAL_SENDER_UUID",
        "SIGNAL_ALLOWED_NUMBER",
        "SIGNAL_ALLOWED_NUMBERS",
        "SIGNAL_ALLOWED_GROUP_IDS",
        "SIGNAL_DISABLE_AUTH",
        "OPENROUTER_API_KEY",
        "OPENROUTER_CHAT_API_KEY",
        "OPENROUTER_IMAGE_API_KEY",
        "OPENROUTER_IMAGE_MODEL",
        "OPENROUTER_IMAGE_TIMEOUT_SECONDS",
        "OPENROUTER_MODEL",
        "OPENROUTER_BASE_URL",
        "OPENROUTER_TIMEOUT_SECONDS",
        "OPENROUTER_MAX_OUTPUT_TOKENS",
        "OPENROUTER_HTTP_REFERER",
        "OPENROUTER_APP_TITLE",
        "BOT_CHAT_TEMPERATURE",
        "BOT_CHAT_CONTEXT_TURNS",
        "BOT_CHAT_CONTEXT_TTL_SECONDS",
        "BOT_CHAT_SYSTEM_PROMPT",
        "BOT_CHAT_FORCE_PLAIN_TEXT",
        "BOT_MENTION_ALIASES",
        "BOT_MAX_PROMPT_CHARS",
        "BOT_SEARCH_ENABLED",
        "BOT_SEARCH_CONTEXT_MODE",
        "BOT_SEARCH_MODE_SEARCH_ENABLED",
        "BOT_SEARCH_MODE_NEWS_ENABLED",
        "BOT_SEARCH_MODE_WIKI_ENABLED",
        "BOT_SEARCH_MODE_IMAGES_ENABLED",
        "BOT_SEARCH_DEBUG_LOGGING",
        "BOT_SEARCH_PERSONA_ENABLED",
        "BOT_SEARCH_USE_HISTORY_FOR_SUMMARY",
        "BOT_SEARCH_REGION",
        "BOT_SEARCH_SAFESEARCH",
        "BOT_SEARCH_BACKEND_STRATEGY",
        "BOT_SEARCH_BACKEND_SEARCH",
        "BOT_SEARCH_BACKEND_NEWS",
        "BOT_SEARCH_BACKEND_SEARCH_ORDER",
        "BOT_SEARCH_BACKEND_NEWS_ORDER",
        "BOT_SEARCH_BACKEND_WIKI",
        "BOT_SEARCH_BACKEND_IMAGES",
        "BOT_SEARCH_TEXT_MAX_RESULTS",
        "BOT_SEARCH_NEWS_MAX_RESULTS",
        "BOT_SEARCH_WIKI_MAX_RESULTS",
        "BOT_SEARCH_IMAGES_MAX_RESULTS",
        "BOT_SEARCH_TIMEOUT_SECONDS",
        "BOT_SEARCH_SOURCE_TTL_SECONDS",
        "BOT_GROUP_REPLY_MODE",
        "BOT_WEBHOOK_HOST",
        "BOT_WEBHOOK_PORT",
    ]
    for key in keys:
        monkeypatch.delenv(key, raising=False)


def _set_base_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGNAL_API_BASE_URL", "http://localhost:8080")
    monkeypatch.setenv("SIGNAL_SENDER_NUMBER", "+15550001111")
    monkeypatch.setenv("SIGNAL_ALLOWED_NUMBER", "+15550002222")
    monkeypatch.setenv("OPENROUTER_CHAT_API_KEY", "or-key-chat")


def test_settings_requires_openrouter_chat_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGNAL_API_BASE_URL", "http://localhost:8080")
    monkeypatch.setenv("SIGNAL_SENDER_NUMBER", "+15550001111")
    monkeypatch.setenv("SIGNAL_ALLOWED_NUMBER", "+15550002222")

    with pytest.raises(RuntimeError) as exc:
        Settings.from_env()

    assert "OPENROUTER_CHAT_API_KEY" in str(exc.value)


def test_settings_does_not_fallback_to_legacy_openrouter_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIGNAL_API_BASE_URL", "http://localhost:8080")
    monkeypatch.setenv("SIGNAL_SENDER_NUMBER", "+15550001111")
    monkeypatch.setenv("SIGNAL_ALLOWED_NUMBER", "+15550002222")
    monkeypatch.setenv("OPENROUTER_API_KEY", "legacy-key")

    with pytest.raises(RuntimeError) as exc:
        Settings.from_env()

    assert "OPENROUTER_CHAT_API_KEY" in str(exc.value)


def test_settings_openrouter_model_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_base_required(monkeypatch)

    settings = Settings.from_env()

    assert settings.openrouter_model == DEFAULT_OPENROUTER_MODEL


def test_settings_chat_system_prompt_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_base_required(monkeypatch)

    settings = Settings.from_env()

    assert settings.bot_chat_system_prompt == DEFAULT_CHAT_SYSTEM_PROMPT


def test_settings_chat_system_prompt_override(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_base_required(monkeypatch)
    monkeypatch.setenv("BOT_CHAT_SYSTEM_PROMPT", "Reply in plain text only.")

    settings = Settings.from_env()

    assert settings.bot_chat_system_prompt == "Reply in plain text only."


def test_settings_chat_force_plain_text_defaults_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_base_required(monkeypatch)

    settings = Settings.from_env()

    assert settings.bot_chat_force_plain_text is True


def test_settings_chat_force_plain_text_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_base_required(monkeypatch)
    monkeypatch.setenv("BOT_CHAT_FORCE_PLAIN_TEXT", "false")

    settings = Settings.from_env()

    assert settings.bot_chat_force_plain_text is False


def test_settings_loads_openrouter_optional_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_base_required(monkeypatch)
    monkeypatch.setenv("OPENROUTER_HTTP_REFERER", "https://example.com")
    monkeypatch.setenv("OPENROUTER_APP_TITLE", "signal-bot-orx")

    settings = Settings.from_env()

    assert settings.openrouter_http_referer == "https://example.com"
    assert settings.openrouter_app_title == "signal-bot-orx"


def test_settings_openrouter_image_is_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_base_required(monkeypatch)

    settings = Settings.from_env()

    assert settings.openrouter_image_api_key is None
    assert settings.openrouter_image_model is None
    assert settings.openrouter_image_timeout_seconds == 90.0


def test_settings_loads_openrouter_image_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_base_required(monkeypatch)
    monkeypatch.setenv("OPENROUTER_IMAGE_API_KEY", "or-key-image")
    monkeypatch.setenv("OPENROUTER_IMAGE_MODEL", "openai/gpt-image-1")
    monkeypatch.setenv("OPENROUTER_IMAGE_TIMEOUT_SECONDS", "75")

    settings = Settings.from_env()

    assert settings.openrouter_image_api_key == "or-key-image"
    assert settings.openrouter_image_model == "openai/gpt-image-1"
    assert settings.openrouter_image_timeout_seconds == 75.0


def test_settings_loads_csv_allowed_numbers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGNAL_API_BASE_URL", "http://localhost:8080")
    monkeypatch.setenv("SIGNAL_SENDER_NUMBER", "+15550001111")
    monkeypatch.setenv(
        "SIGNAL_ALLOWED_NUMBERS", "+15550002222, +15550003333,+15550004444"
    )
    monkeypatch.setenv("OPENROUTER_CHAT_API_KEY", "or-key-chat")

    settings = Settings.from_env()

    assert settings.signal_allowed_numbers == frozenset(
        {"+15550002222", "+15550003333", "+15550004444"}
    )


def test_settings_accepts_group_only_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIGNAL_API_BASE_URL", "http://localhost:8080")
    monkeypatch.setenv("SIGNAL_SENDER_NUMBER", "+15550001111")
    monkeypatch.setenv("SIGNAL_ALLOWED_GROUP_IDS", "group-a,group-b")
    monkeypatch.setenv("OPENROUTER_CHAT_API_KEY", "or-key-chat")

    settings = Settings.from_env()

    assert settings.signal_allowed_group_ids == frozenset({"group-a", "group-b"})
    assert settings.signal_allowed_numbers == frozenset()


def test_settings_fails_without_any_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIGNAL_API_BASE_URL", "http://localhost:8080")
    monkeypatch.setenv("SIGNAL_SENDER_NUMBER", "+15550001111")
    monkeypatch.setenv("OPENROUTER_CHAT_API_KEY", "or-key-chat")

    with pytest.raises(RuntimeError) as exc:
        Settings.from_env()

    assert "Missing allowlist configuration" in str(exc.value)


def test_settings_disable_auth_default_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_base_required(monkeypatch)

    settings = Settings.from_env()

    assert settings.signal_disable_auth is False


def test_settings_disable_auth_true_allows_no_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIGNAL_API_BASE_URL", "http://localhost:8080")
    monkeypatch.setenv("SIGNAL_SENDER_NUMBER", "+15550001111")
    monkeypatch.setenv("OPENROUTER_CHAT_API_KEY", "or-key-chat")
    monkeypatch.setenv("SIGNAL_DISABLE_AUTH", "true")

    settings = Settings.from_env()

    assert settings.signal_disable_auth is True
    assert settings.signal_allowed_numbers == frozenset()
    assert settings.signal_allowed_group_ids == frozenset()


def test_settings_group_reply_mode_defaults_to_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_base_required(monkeypatch)

    settings = Settings.from_env()

    assert settings.bot_group_reply_mode == "group"


def test_settings_group_reply_mode_accepts_dm_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_base_required(monkeypatch)
    monkeypatch.setenv("BOT_GROUP_REPLY_MODE", "dm_fallback")

    settings = Settings.from_env()

    assert settings.bot_group_reply_mode == "dm_fallback"


def test_settings_group_reply_mode_rejects_invalid_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_base_required(monkeypatch)
    monkeypatch.setenv("BOT_GROUP_REPLY_MODE", "invalid")

    with pytest.raises(RuntimeError) as exc:
        Settings.from_env()

    assert "Invalid BOT_GROUP_REPLY_MODE" in str(exc.value)


def test_settings_webhook_port_defaults_to_8001(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_base_required(monkeypatch)

    settings = Settings.from_env()

    assert settings.bot_webhook_port == 8001


def test_settings_mention_aliases_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_base_required(monkeypatch)

    settings = Settings.from_env()

    assert settings.bot_mention_aliases == DEFAULT_MENTION_ALIASES


def test_settings_mention_aliases_parsed_and_deduped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_base_required(monkeypatch)
    monkeypatch.setenv("BOT_MENTION_ALIASES", "@Bot, @SignalBot, @bot")

    settings = Settings.from_env()

    assert settings.bot_mention_aliases == ("@bot", "@signalbot")


def test_settings_search_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_base_required(monkeypatch)

    settings = Settings.from_env()

    assert settings.bot_search_enabled is True
    assert settings.bot_search_context_mode == "no_context"
    assert settings.bot_search_mode_search_enabled is True
    assert settings.bot_search_mode_news_enabled is True
    assert settings.bot_search_mode_wiki_enabled is True
    assert settings.bot_search_mode_images_enabled is True
    assert settings.bot_search_debug_logging is False
    assert settings.bot_search_persona_enabled is False
    assert settings.bot_search_use_history_for_summary is False
    assert settings.bot_search_region == "us-en"
    assert settings.bot_search_safesearch == "moderate"
    assert settings.bot_search_backend_strategy == "first_non_empty"
    assert settings.bot_search_backend_search == "auto"
    assert settings.bot_search_backend_news == "auto"
    assert settings.bot_search_backend_search_order == (
        "duckduckgo",
        "bing",
        "google",
        "yandex",
        "grokipedia",
    )
    assert settings.bot_search_backend_news_order == ("duckduckgo", "bing", "yahoo")
    assert settings.bot_search_backend_wiki == "wikipedia"
    assert settings.bot_search_backend_images == "duckduckgo"
    assert settings.bot_search_text_max_results == 5
    assert settings.bot_search_news_max_results == 5
    assert settings.bot_search_wiki_max_results == 3
    assert settings.bot_search_images_max_results == 3
    assert settings.bot_search_timeout_seconds == 8.0
    assert settings.bot_search_source_ttl_seconds == 1800


def test_settings_search_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_base_required(monkeypatch)
    monkeypatch.setenv("BOT_SEARCH_ENABLED", "false")
    monkeypatch.setenv("BOT_SEARCH_CONTEXT_MODE", "context")
    monkeypatch.setenv("BOT_SEARCH_MODE_SEARCH_ENABLED", "false")
    monkeypatch.setenv("BOT_SEARCH_MODE_NEWS_ENABLED", "false")
    monkeypatch.setenv("BOT_SEARCH_MODE_WIKI_ENABLED", "false")
    monkeypatch.setenv("BOT_SEARCH_MODE_IMAGES_ENABLED", "false")
    monkeypatch.setenv("BOT_SEARCH_DEBUG_LOGGING", "true")
    monkeypatch.setenv("BOT_SEARCH_PERSONA_ENABLED", "true")
    monkeypatch.setenv("BOT_SEARCH_USE_HISTORY_FOR_SUMMARY", "true")
    monkeypatch.setenv("BOT_SEARCH_REGION", "ca-en")
    monkeypatch.setenv("BOT_SEARCH_SAFESEARCH", "off")
    monkeypatch.setenv("BOT_SEARCH_BACKEND_STRATEGY", "aggregate")
    monkeypatch.setenv("BOT_SEARCH_BACKEND_SEARCH", "google")
    monkeypatch.setenv("BOT_SEARCH_BACKEND_NEWS", "yahoo")
    monkeypatch.setenv(
        "BOT_SEARCH_BACKEND_SEARCH_ORDER",
        "duckduckgo, bing, google, yandex, grokipedia",
    )
    monkeypatch.setenv("BOT_SEARCH_BACKEND_NEWS_ORDER", "duckduckgo,bing,yahoo")
    monkeypatch.setenv("BOT_SEARCH_BACKEND_WIKI", "wikipedia")
    monkeypatch.setenv("BOT_SEARCH_BACKEND_IMAGES", "duckduckgo")
    monkeypatch.setenv("BOT_SEARCH_TEXT_MAX_RESULTS", "7")
    monkeypatch.setenv("BOT_SEARCH_NEWS_MAX_RESULTS", "6")
    monkeypatch.setenv("BOT_SEARCH_WIKI_MAX_RESULTS", "4")
    monkeypatch.setenv("BOT_SEARCH_IMAGES_MAX_RESULTS", "2")
    monkeypatch.setenv("BOT_SEARCH_TIMEOUT_SECONDS", "12")
    monkeypatch.setenv("BOT_SEARCH_SOURCE_TTL_SECONDS", "900")

    settings = Settings.from_env()

    assert settings.bot_search_enabled is False
    assert settings.bot_search_context_mode == "context"
    assert settings.bot_search_mode_search_enabled is False
    assert settings.bot_search_mode_news_enabled is False
    assert settings.bot_search_mode_wiki_enabled is False
    assert settings.bot_search_mode_images_enabled is False
    assert settings.bot_search_debug_logging is True
    assert settings.bot_search_persona_enabled is True
    assert settings.bot_search_use_history_for_summary is True
    assert settings.bot_search_region == "ca-en"
    assert settings.bot_search_safesearch == "off"
    assert settings.bot_search_backend_strategy == "aggregate"
    assert settings.bot_search_backend_search == "google"
    assert settings.bot_search_backend_news == "yahoo"
    assert settings.bot_search_backend_search_order == (
        "duckduckgo",
        "bing",
        "google",
        "yandex",
        "grokipedia",
    )
    assert settings.bot_search_backend_news_order == ("duckduckgo", "bing", "yahoo")
    assert settings.bot_search_backend_wiki == "wikipedia"
    assert settings.bot_search_backend_images == "duckduckgo"
    assert settings.bot_search_text_max_results == 7
    assert settings.bot_search_news_max_results == 6
    assert settings.bot_search_wiki_max_results == 4
    assert settings.bot_search_images_max_results == 2
    assert settings.bot_search_timeout_seconds == 12.0
    assert settings.bot_search_source_ttl_seconds == 900


def test_settings_search_safesearch_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_base_required(monkeypatch)
    monkeypatch.setenv("BOT_SEARCH_SAFESEARCH", "strict")

    with pytest.raises(RuntimeError) as exc:
        Settings.from_env()

    assert "Invalid BOT_SEARCH_SAFESEARCH" in str(exc.value)


def test_settings_search_context_mode_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_base_required(monkeypatch)
    monkeypatch.setenv("BOT_SEARCH_CONTEXT_MODE", "auto")

    with pytest.raises(RuntimeError) as exc:
        Settings.from_env()

    assert "Invalid BOT_SEARCH_CONTEXT_MODE" in str(exc.value)


def test_settings_search_backend_strategy_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_base_required(monkeypatch)
    monkeypatch.setenv("BOT_SEARCH_BACKEND_STRATEGY", "fanout")

    with pytest.raises(RuntimeError) as exc:
        Settings.from_env()

    assert "Invalid BOT_SEARCH_BACKEND_STRATEGY" in str(exc.value)


def test_settings_search_backend_order_uses_legacy_single_backend_when_no_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_base_required(monkeypatch)
    monkeypatch.setenv("BOT_SEARCH_BACKEND_SEARCH", "google")
    monkeypatch.setenv("BOT_SEARCH_BACKEND_NEWS", "bing")

    settings = Settings.from_env()

    assert settings.bot_search_backend_search_order == ("google",)
    assert settings.bot_search_backend_news_order == ("bing",)


def test_settings_search_backend_order_dedupes_and_normalizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_base_required(monkeypatch)
    monkeypatch.setenv(
        "BOT_SEARCH_BACKEND_SEARCH_ORDER",
        "DuckDuckGo, bing, duckduckgo, yandex",
    )
    monkeypatch.setenv("BOT_SEARCH_BACKEND_NEWS_ORDER", "duckduckgo, yahoo, yahoo")

    settings = Settings.from_env()

    assert settings.bot_search_backend_search_order == (
        "duckduckgo",
        "bing",
        "yandex",
    )
    assert settings.bot_search_backend_news_order == ("duckduckgo", "yahoo")


def test_settings_search_backend_order_rejects_invalid_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_base_required(monkeypatch)
    monkeypatch.setenv("BOT_SEARCH_BACKEND_SEARCH_ORDER", "duckduckgo,notreal")

    with pytest.raises(RuntimeError) as exc:
        Settings.from_env()

    assert "Invalid BOT_SEARCH_BACKEND_SEARCH_ORDER" in str(exc.value)


def test_settings_search_backend_news_order_rejects_encyclopedia_backends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_base_required(monkeypatch)
    monkeypatch.setenv("BOT_SEARCH_BACKEND_NEWS_ORDER", "duckduckgo,wikipedia")

    with pytest.raises(RuntimeError) as exc:
        Settings.from_env()

    assert "Invalid BOT_SEARCH_BACKEND_NEWS_ORDER" in str(exc.value)


def test_settings_search_backend_news_legacy_rejects_encyclopedia_backends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_base_required(monkeypatch)
    monkeypatch.setenv("BOT_SEARCH_BACKEND_NEWS", "grokipedia")

    with pytest.raises(RuntimeError) as exc:
        Settings.from_env()

    assert "Invalid BOT_SEARCH_BACKEND_NEWS" in str(exc.value)
