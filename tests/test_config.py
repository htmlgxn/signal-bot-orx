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
