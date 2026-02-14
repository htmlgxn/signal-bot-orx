from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

from signal_bot_orx.chat_prompt import DEFAULT_CHAT_SYSTEM_PROMPT

GroupReplyMode = Literal["group", "dm_fallback"]
SearchContextMode = Literal["no_context", "context"]

DEFAULT_OPENROUTER_MODEL = "openai/gpt-4o-mini"
DEFAULT_MENTION_ALIASES = ("@signalbot", "@bot")


@dataclass(frozen=True)
class Settings:
    signal_api_base_url: str
    signal_sender_number: str
    signal_sender_uuid: str | None
    signal_allowed_numbers: frozenset[str]
    signal_allowed_group_ids: frozenset[str]
    openrouter_chat_api_key: str
    openrouter_model: str
    openrouter_image_api_key: str | None = None
    openrouter_image_model: str | None = None
    openrouter_image_timeout_seconds: float = 90.0
    signal_disable_auth: bool = False
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_timeout_seconds: float = 45.0
    openrouter_max_output_tokens: int = 300
    openrouter_http_referer: str | None = None
    openrouter_app_title: str | None = None
    bot_chat_temperature: float = 0.6
    bot_chat_context_turns: int = 6
    bot_chat_context_ttl_seconds: int = 1800
    bot_chat_system_prompt: str = DEFAULT_CHAT_SYSTEM_PROMPT
    bot_chat_force_plain_text: bool = True
    bot_mention_aliases: tuple[str, ...] = DEFAULT_MENTION_ALIASES
    bot_max_prompt_chars: int = 700
    bot_search_enabled: bool = True
    bot_search_context_mode: SearchContextMode = "no_context"
    bot_search_mode_search_enabled: bool = True
    bot_search_mode_news_enabled: bool = True
    bot_search_mode_wiki_enabled: bool = True
    bot_search_mode_images_enabled: bool = True
    bot_search_debug_logging: bool = False
    bot_search_persona_enabled: bool = False
    bot_search_use_history_for_summary: bool = False
    bot_search_region: str = "us-en"
    bot_search_safesearch: Literal["on", "moderate", "off"] = "moderate"
    bot_search_backend_search: str = "auto"
    bot_search_backend_news: str = "auto"
    bot_search_backend_wiki: str = "wikipedia"
    bot_search_backend_images: str = "duckduckgo"
    bot_search_text_max_results: int = 5
    bot_search_news_max_results: int = 5
    bot_search_wiki_max_results: int = 3
    bot_search_images_max_results: int = 3
    bot_search_timeout_seconds: float = 8.0
    bot_search_source_ttl_seconds: int = 1800
    bot_group_reply_mode: GroupReplyMode = "group"
    bot_webhook_host: str = "127.0.0.1"
    bot_webhook_port: int = 8001

    @classmethod
    def from_env(cls) -> Settings:
        missing: list[str] = []

        required = {
            "signal_api_base_url": os.getenv("SIGNAL_API_BASE_URL"),
            "signal_sender_number": os.getenv("SIGNAL_SENDER_NUMBER"),
            "openrouter_chat_api_key": os.getenv("OPENROUTER_CHAT_API_KEY"),
        }

        for key, value in required.items():
            if not value:
                missing.append(key.upper())

        if missing:
            details = ", ".join(sorted(missing))
            raise RuntimeError(f"Missing required environment variables: {details}")

        allowed_numbers = _split_csv_set(os.getenv("SIGNAL_ALLOWED_NUMBERS"))
        legacy_allowed_number = os.getenv("SIGNAL_ALLOWED_NUMBER")
        if legacy_allowed_number:
            allowed_numbers.add(legacy_allowed_number.strip())

        allowed_group_ids = _split_csv_set(os.getenv("SIGNAL_ALLOWED_GROUP_IDS"))
        signal_disable_auth = _parse_bool(os.getenv("SIGNAL_DISABLE_AUTH"))
        if not signal_disable_auth and not allowed_numbers and not allowed_group_ids:
            raise RuntimeError(
                "Missing allowlist configuration: set SIGNAL_ALLOWED_NUMBER, "
                "SIGNAL_ALLOWED_NUMBERS, or SIGNAL_ALLOWED_GROUP_IDS"
            )

        mention_aliases = _split_csv_ordered(os.getenv("BOT_MENTION_ALIASES"))
        if not mention_aliases:
            mention_aliases = DEFAULT_MENTION_ALIASES

        return cls(
            signal_api_base_url=required["signal_api_base_url"] or "",
            signal_sender_number=required["signal_sender_number"] or "",
            signal_sender_uuid=os.getenv("SIGNAL_SENDER_UUID"),
            signal_allowed_numbers=frozenset(allowed_numbers),
            signal_allowed_group_ids=frozenset(allowed_group_ids),
            signal_disable_auth=signal_disable_auth,
            openrouter_chat_api_key=required["openrouter_chat_api_key"] or "",
            openrouter_model=os.getenv("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL),
            openrouter_image_api_key=os.getenv("OPENROUTER_IMAGE_API_KEY"),
            openrouter_image_model=os.getenv("OPENROUTER_IMAGE_MODEL"),
            openrouter_image_timeout_seconds=float(
                os.getenv("OPENROUTER_IMAGE_TIMEOUT_SECONDS", "90")
            ),
            openrouter_base_url=os.getenv(
                "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
            ),
            openrouter_timeout_seconds=float(
                os.getenv("OPENROUTER_TIMEOUT_SECONDS", "45")
            ),
            openrouter_max_output_tokens=int(
                os.getenv("OPENROUTER_MAX_OUTPUT_TOKENS", "300")
            ),
            openrouter_http_referer=os.getenv("OPENROUTER_HTTP_REFERER"),
            openrouter_app_title=os.getenv("OPENROUTER_APP_TITLE"),
            bot_chat_temperature=float(os.getenv("BOT_CHAT_TEMPERATURE", "0.6")),
            bot_chat_context_turns=int(os.getenv("BOT_CHAT_CONTEXT_TURNS", "6")),
            bot_chat_context_ttl_seconds=int(
                os.getenv("BOT_CHAT_CONTEXT_TTL_SECONDS", "1800")
            ),
            bot_chat_system_prompt=_chat_system_prompt_from_env(
                os.getenv("BOT_CHAT_SYSTEM_PROMPT")
            ),
            bot_chat_force_plain_text=_parse_bool(
                os.getenv("BOT_CHAT_FORCE_PLAIN_TEXT")
            )
            if os.getenv("BOT_CHAT_FORCE_PLAIN_TEXT") is not None
            else True,
            bot_mention_aliases=mention_aliases,
            bot_max_prompt_chars=int(os.getenv("BOT_MAX_PROMPT_CHARS", "700")),
            bot_search_enabled=_parse_bool(os.getenv("BOT_SEARCH_ENABLED"))
            if os.getenv("BOT_SEARCH_ENABLED") is not None
            else True,
            bot_search_context_mode=_parse_search_context_mode(
                os.getenv("BOT_SEARCH_CONTEXT_MODE")
            ),
            bot_search_mode_search_enabled=_parse_bool(
                os.getenv("BOT_SEARCH_MODE_SEARCH_ENABLED")
            )
            if os.getenv("BOT_SEARCH_MODE_SEARCH_ENABLED") is not None
            else True,
            bot_search_mode_news_enabled=_parse_bool(
                os.getenv("BOT_SEARCH_MODE_NEWS_ENABLED")
            )
            if os.getenv("BOT_SEARCH_MODE_NEWS_ENABLED") is not None
            else True,
            bot_search_mode_wiki_enabled=_parse_bool(
                os.getenv("BOT_SEARCH_MODE_WIKI_ENABLED")
            )
            if os.getenv("BOT_SEARCH_MODE_WIKI_ENABLED") is not None
            else True,
            bot_search_mode_images_enabled=_parse_bool(
                os.getenv("BOT_SEARCH_MODE_IMAGES_ENABLED")
            )
            if os.getenv("BOT_SEARCH_MODE_IMAGES_ENABLED") is not None
            else True,
            bot_search_debug_logging=_parse_bool(
                os.getenv("BOT_SEARCH_DEBUG_LOGGING")
            )
            if os.getenv("BOT_SEARCH_DEBUG_LOGGING") is not None
            else False,
            bot_search_persona_enabled=_parse_bool(
                os.getenv("BOT_SEARCH_PERSONA_ENABLED")
            )
            if os.getenv("BOT_SEARCH_PERSONA_ENABLED") is not None
            else False,
            bot_search_use_history_for_summary=_parse_bool(
                os.getenv("BOT_SEARCH_USE_HISTORY_FOR_SUMMARY")
            )
            if os.getenv("BOT_SEARCH_USE_HISTORY_FOR_SUMMARY") is not None
            else False,
            bot_search_region=os.getenv("BOT_SEARCH_REGION", "us-en"),
            bot_search_safesearch=_parse_safesearch(os.getenv("BOT_SEARCH_SAFESEARCH")),
            bot_search_backend_search=_parse_non_empty_str(
                os.getenv("BOT_SEARCH_BACKEND_SEARCH"),
                default="auto",
            ),
            bot_search_backend_news=_parse_non_empty_str(
                os.getenv("BOT_SEARCH_BACKEND_NEWS"),
                default="auto",
            ),
            bot_search_backend_wiki=_parse_non_empty_str(
                os.getenv("BOT_SEARCH_BACKEND_WIKI"),
                default="wikipedia",
            ),
            bot_search_backend_images=_parse_non_empty_str(
                os.getenv("BOT_SEARCH_BACKEND_IMAGES"),
                default="duckduckgo",
            ),
            bot_search_text_max_results=int(
                os.getenv("BOT_SEARCH_TEXT_MAX_RESULTS", "5")
            ),
            bot_search_news_max_results=int(
                os.getenv("BOT_SEARCH_NEWS_MAX_RESULTS", "5")
            ),
            bot_search_wiki_max_results=int(
                os.getenv("BOT_SEARCH_WIKI_MAX_RESULTS", "3")
            ),
            bot_search_images_max_results=int(
                os.getenv("BOT_SEARCH_IMAGES_MAX_RESULTS", "3")
            ),
            bot_search_timeout_seconds=float(
                os.getenv("BOT_SEARCH_TIMEOUT_SECONDS", "8")
            ),
            bot_search_source_ttl_seconds=int(
                os.getenv("BOT_SEARCH_SOURCE_TTL_SECONDS", "1800")
            ),
            bot_group_reply_mode=_parse_group_reply_mode(
                os.getenv("BOT_GROUP_REPLY_MODE")
            ),
            bot_webhook_host=os.getenv("BOT_WEBHOOK_HOST", "127.0.0.1"),
            bot_webhook_port=int(os.getenv("BOT_WEBHOOK_PORT", "8001")),
        )


def _split_csv_set(value: str | None) -> set[str]:
    if value is None:
        return set()
    return {item.strip() for item in value.split(",") if item.strip()}


def _split_csv_ordered(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()

    seen: set[str] = set()
    ordered: list[str] = []
    for raw_item in value.split(","):
        item = raw_item.strip().lower()
        if not item or item in seen:
            continue
        ordered.append(item)
        seen.add(item)

    return tuple(ordered)


def _parse_bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_group_reply_mode(value: str | None) -> GroupReplyMode:
    if value is None:
        return "group"

    normalized = value.strip().lower()
    if normalized == "group":
        return "group"
    if normalized == "dm_fallback":
        return "dm_fallback"

    raise RuntimeError(
        "Invalid BOT_GROUP_REPLY_MODE. Expected 'group' or 'dm_fallback'."
    )


def _parse_safesearch(value: str | None) -> Literal["on", "moderate", "off"]:
    if value is None:
        return "moderate"

    normalized = value.strip().lower()
    if normalized == "on":
        return "on"
    if normalized == "moderate":
        return "moderate"
    if normalized == "off":
        return "off"

    raise RuntimeError(
        "Invalid BOT_SEARCH_SAFESEARCH. Expected 'on', 'moderate', or 'off'."
    )


def _parse_search_context_mode(value: str | None) -> SearchContextMode:
    if value is None:
        return "no_context"

    normalized = value.strip().lower()
    if normalized == "no_context":
        return "no_context"
    if normalized == "context":
        return "context"

    raise RuntimeError(
        "Invalid BOT_SEARCH_CONTEXT_MODE. Expected 'no_context' or 'context'."
    )


def _parse_non_empty_str(value: str | None, *, default: str) -> str:
    if value is None:
        return default
    stripped = value.strip().lower()
    if not stripped:
        return default
    return stripped


def _chat_system_prompt_from_env(value: str | None) -> str:
    if value is None:
        return DEFAULT_CHAT_SYSTEM_PROMPT
    stripped = value.strip()
    if not stripped:
        return DEFAULT_CHAT_SYSTEM_PROMPT
    return stripped
