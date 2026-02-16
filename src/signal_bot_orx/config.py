from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

from signal_bot_orx.chat_prompt import DEFAULT_CHAT_SYSTEM_PROMPT

GroupReplyMode = Literal["group", "dm_fallback"]
SearchContextMode = Literal["no_context", "context"]
SearchBackendStrategy = Literal["first_non_empty", "aggregate"]

_SEARCH_ALLOWED_BACKENDS = frozenset(
    {
        "auto",
        "all",
        "bing",
        "brave",
        "duckduckgo",
        "google",
        "grokipedia",
        "mojeek",
        "wikipedia",
        "yahoo",
        "yandex",
    }
)
_NEWS_ALLOWED_BACKENDS = frozenset({"auto", "all", "bing", "duckduckgo", "yahoo"})
_NEWS_BLOCKED_BACKENDS = frozenset({"grokipedia", "wikipedia"})

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
    signal_enabled: bool = True
    telegram_enabled: bool = False
    telegram_bot_token: str | None = None
    telegram_webhook_secret: str | None = None
    telegram_allowed_user_ids: frozenset[str] = frozenset()
    telegram_allowed_chat_ids: frozenset[str] = frozenset()
    telegram_disable_auth: bool = False
    telegram_bot_username: str | None = None
    whatsapp_enabled: bool = False
    whatsapp_bridge_base_url: str | None = None
    whatsapp_bridge_token: str | None = None
    whatsapp_allowed_numbers: frozenset[str] = frozenset()
    whatsapp_disable_auth: bool = False
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
    bot_search_mode_videos_enabled: bool = True
    bot_search_debug_logging: bool = False
    bot_search_persona_enabled: bool = False
    bot_search_use_history_for_summary: bool = False
    bot_search_region: str = "us-en"
    bot_search_safesearch: Literal["on", "moderate", "off"] = "moderate"
    bot_search_backend_search: str = "auto"
    bot_search_backend_news: str = "auto"
    bot_search_backend_videos: str = "youtube"
    bot_search_backend_strategy: SearchBackendStrategy = "first_non_empty"
    bot_search_backend_search_order: tuple[str, ...] = (
        "duckduckgo",
        "bing",
        "google",
        "yandex",
        "grokipedia",
    )
    bot_search_backend_news_order: tuple[str, ...] = ("duckduckgo", "bing", "yahoo")
    bot_search_backend_wiki: str = "wikipedia"
    bot_search_backend_images: str = "duckduckgo"
    bot_search_text_max_results: int = 5
    bot_search_news_max_results: int = 5
    bot_search_wiki_max_results: int = 3
    bot_search_images_max_results: int = 3
    bot_search_videos_max_results: int = 5
    bot_search_timeout_seconds: float = 8.0
    bot_search_source_ttl_seconds: int = 1800
    weather_api_key: str | None = None
    weather_units: Literal["metric", "imperial"] = "metric"
    weather_default_location: str | None = None
    bot_group_reply_mode: GroupReplyMode = "group"
    bot_webhook_host: str = "127.0.0.1"
    bot_webhook_port: int = 8001

    @classmethod
    def from_env(cls) -> Settings:
        missing: list[str] = []
        signal_enabled = (
            _parse_bool(os.getenv("SIGNAL_ENABLED"))
            if os.getenv("SIGNAL_ENABLED") is not None
            else True
        )
        whatsapp_enabled = _parse_bool(os.getenv("WHATSAPP_ENABLED"))
        telegram_enabled = _parse_bool(os.getenv("TELEGRAM_ENABLED"))

        if not signal_enabled and not whatsapp_enabled and not telegram_enabled:
            raise RuntimeError(
                "No transports enabled. Enable at least one of SIGNAL_ENABLED, "
                "WHATSAPP_ENABLED, or TELEGRAM_ENABLED."
            )

        openrouter_chat_api_key = os.getenv("OPENROUTER_CHAT_API_KEY")
        if not openrouter_chat_api_key:
            missing.append("OPENROUTER_CHAT_API_KEY")

        allowed_numbers = _split_csv_set(os.getenv("SIGNAL_ALLOWED_NUMBERS"))
        legacy_allowed_number = os.getenv("SIGNAL_ALLOWED_NUMBER")
        if legacy_allowed_number:
            allowed_numbers.add(legacy_allowed_number.strip())

        allowed_group_ids = _split_csv_set(os.getenv("SIGNAL_ALLOWED_GROUP_IDS"))
        signal_disable_auth = _parse_bool(os.getenv("SIGNAL_DISABLE_AUTH"))
        signal_api_base_url = _parse_optional_non_empty_str(
            os.getenv("SIGNAL_API_BASE_URL")
        )
        signal_sender_number = _parse_optional_non_empty_str(
            os.getenv("SIGNAL_SENDER_NUMBER")
        )
        if signal_enabled:
            if not signal_api_base_url:
                missing.append("SIGNAL_API_BASE_URL")
            if not signal_sender_number:
                missing.append("SIGNAL_SENDER_NUMBER")
            if (
                not signal_disable_auth
                and not allowed_numbers
                and not allowed_group_ids
            ):
                raise RuntimeError(
                    "Missing Signal allowlist configuration: set SIGNAL_ALLOWED_NUMBER, "
                    "SIGNAL_ALLOWED_NUMBERS, or SIGNAL_ALLOWED_GROUP_IDS, or set "
                    "SIGNAL_DISABLE_AUTH=true"
                )

        whatsapp_allowed_numbers = _split_csv_set(os.getenv("WHATSAPP_ALLOWED_NUMBERS"))
        whatsapp_disable_auth = _parse_bool(os.getenv("WHATSAPP_DISABLE_AUTH"))
        if (
            whatsapp_enabled
            and not whatsapp_disable_auth
            and not whatsapp_allowed_numbers
        ):
            raise RuntimeError(
                "Missing WhatsApp allowlist configuration: set "
                "WHATSAPP_ALLOWED_NUMBERS or WHATSAPP_DISABLE_AUTH=true"
            )

        telegram_bot_token = _parse_optional_non_empty_str(
            os.getenv("TELEGRAM_BOT_TOKEN")
        )
        telegram_webhook_secret = _parse_optional_non_empty_str(
            os.getenv("TELEGRAM_WEBHOOK_SECRET")
        )
        telegram_allowed_user_ids = _split_csv_set(
            os.getenv("TELEGRAM_ALLOWED_USER_IDS")
        )
        telegram_allowed_chat_ids = _split_csv_set(
            os.getenv("TELEGRAM_ALLOWED_CHAT_IDS")
        )
        telegram_disable_auth = _parse_bool(os.getenv("TELEGRAM_DISABLE_AUTH"))
        if telegram_enabled:
            if not telegram_bot_token:
                missing.append("TELEGRAM_BOT_TOKEN")
            if (
                not telegram_disable_auth
                and not telegram_allowed_user_ids
                and not telegram_allowed_chat_ids
            ):
                raise RuntimeError(
                    "Missing Telegram allowlist configuration: set "
                    "TELEGRAM_ALLOWED_USER_IDS, TELEGRAM_ALLOWED_CHAT_IDS, or "
                    "TELEGRAM_DISABLE_AUTH=true"
                )

        if missing:
            details = ", ".join(sorted(set(missing)))
            raise RuntimeError(f"Missing required environment variables: {details}")

        mention_aliases = _split_csv_ordered(os.getenv("BOT_MENTION_ALIASES"))
        if not mention_aliases:
            mention_aliases = DEFAULT_MENTION_ALIASES

        backend_search_env = _parse_non_empty_str(
            os.getenv("BOT_SEARCH_BACKEND_SEARCH"),
            default="auto",
        )
        backend_news_env = _parse_non_empty_str(
            os.getenv("BOT_SEARCH_BACKEND_NEWS"),
            default="auto",
        )
        backend_search_order = _parse_backend_order_env(
            os.getenv("BOT_SEARCH_BACKEND_SEARCH_ORDER"),
            allowed_backends=_SEARCH_ALLOWED_BACKENDS,
            blocked_backends=frozenset(),
            env_name="BOT_SEARCH_BACKEND_SEARCH_ORDER",
        )
        backend_news_order = _parse_backend_order_env(
            os.getenv("BOT_SEARCH_BACKEND_NEWS_ORDER"),
            allowed_backends=_NEWS_ALLOWED_BACKENDS,
            blocked_backends=_NEWS_BLOCKED_BACKENDS,
            env_name="BOT_SEARCH_BACKEND_NEWS_ORDER",
        )

        return cls(
            signal_api_base_url=signal_api_base_url or "",
            signal_sender_number=signal_sender_number or "",
            signal_sender_uuid=os.getenv("SIGNAL_SENDER_UUID"),
            signal_allowed_numbers=frozenset(allowed_numbers),
            signal_allowed_group_ids=frozenset(allowed_group_ids),
            openrouter_chat_api_key=openrouter_chat_api_key or "",
            openrouter_model=os.getenv("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL),
            signal_enabled=signal_enabled,
            signal_disable_auth=signal_disable_auth,
            telegram_enabled=telegram_enabled,
            telegram_bot_token=telegram_bot_token,
            telegram_webhook_secret=telegram_webhook_secret,
            telegram_allowed_user_ids=frozenset(telegram_allowed_user_ids),
            telegram_allowed_chat_ids=frozenset(telegram_allowed_chat_ids),
            telegram_disable_auth=telegram_disable_auth,
            telegram_bot_username=_parse_optional_non_empty_str(
                os.getenv("TELEGRAM_BOT_USERNAME")
            ),
            whatsapp_enabled=whatsapp_enabled,
            whatsapp_bridge_base_url=_parse_optional_non_empty_str(
                os.getenv("WHATSAPP_BRIDGE_BASE_URL")
            ),
            whatsapp_bridge_token=_parse_optional_non_empty_str(
                os.getenv("WHATSAPP_BRIDGE_TOKEN")
            ),
            whatsapp_allowed_numbers=frozenset(whatsapp_allowed_numbers),
            whatsapp_disable_auth=whatsapp_disable_auth,
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
            bot_search_mode_videos_enabled=_parse_bool(
                os.getenv("BOT_SEARCH_MODE_VIDEOS_ENABLED")
            )
            if os.getenv("BOT_SEARCH_MODE_VIDEOS_ENABLED") is not None
            else True,
            bot_search_debug_logging=_parse_bool(os.getenv("BOT_SEARCH_DEBUG_LOGGING"))
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
            bot_search_backend_search=backend_search_env,
            bot_search_backend_news=backend_news_env,
            bot_search_backend_videos=_parse_non_empty_str(
                os.getenv("BOT_SEARCH_BACKEND_VIDEOS"),
                default="youtube",
            ),
            bot_search_backend_strategy=_parse_search_backend_strategy(
                os.getenv("BOT_SEARCH_BACKEND_STRATEGY")
            ),
            bot_search_backend_search_order=(
                backend_search_order
                if backend_search_order is not None
                else _resolve_search_backend_order(
                    legacy_backend=backend_search_env,
                )
            ),
            bot_search_backend_news_order=(
                backend_news_order
                if backend_news_order is not None
                else _resolve_news_backend_order(
                    legacy_backend=backend_news_env,
                )
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
            bot_search_videos_max_results=int(
                os.getenv("BOT_SEARCH_VIDEOS_MAX_RESULTS", "5")
            ),
            bot_search_timeout_seconds=float(
                os.getenv("BOT_SEARCH_TIMEOUT_SECONDS", "8")
            ),
            bot_search_source_ttl_seconds=int(
                os.getenv("BOT_SEARCH_SOURCE_TTL_SECONDS", "1800")
            ),
            weather_api_key=_parse_optional_non_empty_str(os.getenv("WEATHER_API_KEY")),
            weather_units=(
                "imperial"
                if (os.getenv("WEATHER_UNITS") or "").strip().lower() == "imperial"
                else "metric"
            ),
            weather_default_location=_parse_optional_non_empty_str(
                os.getenv("WEATHER_DEFAULT_LOCATION")
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


def _parse_search_backend_strategy(value: str | None) -> SearchBackendStrategy:
    if value is None:
        return "first_non_empty"

    normalized = value.strip().lower()
    if normalized == "first_non_empty":
        return "first_non_empty"
    if normalized == "aggregate":
        return "aggregate"

    raise RuntimeError(
        "Invalid BOT_SEARCH_BACKEND_STRATEGY. Expected 'first_non_empty' or "
        "'aggregate'."
    )


def _parse_non_empty_str(value: str | None, *, default: str) -> str:
    if value is None:
        return default
    stripped = value.strip().lower()
    if not stripped:
        return default
    return stripped


def _parse_optional_non_empty_str(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped


def _parse_backend_order_env(
    value: str | None,
    *,
    allowed_backends: frozenset[str],
    blocked_backends: frozenset[str],
    env_name: str,
) -> tuple[str, ...] | None:
    if value is None:
        return None

    raw_items = [item.strip().lower() for item in value.split(",")]
    seen: set[str] = set()
    ordered: list[str] = []
    for backend in raw_items:
        if not backend or backend in seen:
            continue
        if backend in blocked_backends:
            blocked = ", ".join(sorted(blocked_backends))
            raise RuntimeError(
                f"Invalid {env_name}. Backend '{backend}' is not allowed. "
                f"Blocked values: {blocked}."
            )
        if backend not in allowed_backends:
            allowed = ", ".join(sorted(allowed_backends))
            raise RuntimeError(
                f"Invalid {env_name}. Backend '{backend}' is not recognized. "
                f"Allowed values: {allowed}."
            )
        ordered.append(backend)
        seen.add(backend)

    if not ordered:
        return None
    return tuple(ordered)


def _resolve_search_backend_order(*, legacy_backend: str) -> tuple[str, ...]:
    if legacy_backend and legacy_backend != "auto":
        if legacy_backend not in _SEARCH_ALLOWED_BACKENDS:
            allowed = ", ".join(sorted(_SEARCH_ALLOWED_BACKENDS))
            raise RuntimeError(
                f"Invalid BOT_SEARCH_BACKEND_SEARCH. Allowed values: {allowed}."
            )
        return (legacy_backend,)
    return ("duckduckgo", "bing", "google", "yandex", "grokipedia")


def _resolve_news_backend_order(*, legacy_backend: str) -> tuple[str, ...]:
    if legacy_backend in _NEWS_BLOCKED_BACKENDS:
        blocked = ", ".join(sorted(_NEWS_BLOCKED_BACKENDS))
        raise RuntimeError(
            f"Invalid BOT_SEARCH_BACKEND_NEWS. Blocked values: {blocked}."
        )
    if legacy_backend and legacy_backend != "auto":
        if legacy_backend not in _NEWS_ALLOWED_BACKENDS:
            allowed = ", ".join(sorted(_NEWS_ALLOWED_BACKENDS))
            raise RuntimeError(
                f"Invalid BOT_SEARCH_BACKEND_NEWS. Allowed values: {allowed}."
            )
        return (legacy_backend,)
    return ("duckduckgo", "bing", "yahoo")


def _chat_system_prompt_from_env(value: str | None) -> str:
    if value is None:
        return DEFAULT_CHAT_SYSTEM_PROMPT
    stripped = value.strip()
    if not stripped:
        return DEFAULT_CHAT_SYSTEM_PROMPT
    return stripped
