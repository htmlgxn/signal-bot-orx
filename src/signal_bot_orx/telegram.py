from __future__ import annotations

from typing import Any

from signal_bot_orx.parsing import as_dict, first_non_empty_str
from signal_bot_orx.types import IncomingMessage, Target


def parse_telegram_webhook(
    payload: dict[str, Any], *, bot_username: str | None = None
) -> IncomingMessage | None:
    update = as_dict(payload)
    message = as_dict(update.get("message")) or as_dict(update.get("edited_message"))
    if not message:
        return None

    text = first_non_empty_str(message, "text", "caption")
    if not text:
        return None

    from_data = as_dict(message.get("from"))
    chat_data = as_dict(message.get("chat"))
    sender_id = _coerce_id(from_data.get("id"))
    chat_id = _coerce_id(chat_data.get("id"))
    if sender_id is None or chat_id is None:
        return None

    chat_type = first_non_empty_str(chat_data, "type") or ""
    is_group = chat_type in {"group", "supergroup"}
    timestamp_raw = message.get("date")
    timestamp = int(timestamp_raw) if isinstance(timestamp_raw, int) else 0

    directed_to_bot = _is_directed_to_bot(
        message=message,
        text=text,
        bot_username=bot_username,
    )
    target = (
        Target(recipient=sender_id, group_id=chat_id)
        if is_group
        else Target(recipient=chat_id, group_id=None)
    )
    return IncomingMessage(
        sender=sender_id,
        text=text,
        timestamp=timestamp,
        target=target,
        transport="telegram",
        directed_to_bot=directed_to_bot,
    )


def _is_directed_to_bot(
    *,
    message: dict[str, Any],
    text: str,
    bot_username: str | None,
) -> bool:
    normalized_username = _normalize_username(bot_username)
    if normalized_username and _entities_mention_username(
        message=message,
        text=text,
        normalized_username=normalized_username,
    ):
        return True

    reply_to = as_dict(message.get("reply_to_message"))
    reply_from = as_dict(reply_to.get("from"))
    if not reply_from or not reply_from.get("is_bot"):
        return False

    if not normalized_username:
        return False

    reply_username = _normalize_username(first_non_empty_str(reply_from, "username"))
    return reply_username == normalized_username


def _entities_mention_username(
    *,
    message: dict[str, Any],
    text: str,
    normalized_username: str,
) -> bool:
    entities = message.get("entities")
    if not isinstance(entities, list):
        return False

    for raw_entity in entities:
        if not isinstance(raw_entity, dict):
            continue
        entity = as_dict(raw_entity)
        if first_non_empty_str(entity, "type") != "mention":
            continue
        offset = _as_int(entity.get("offset"))
        length = _as_int(entity.get("length"))
        if offset is None or length is None or offset < 0 or length <= 0:
            continue
        end = offset + length
        if end > len(text):
            continue
        mention_text = text[offset:end].strip().lower()
        if mention_text == f"@{normalized_username}":
            return True

    return False


def _coerce_id(value: object) -> str | None:
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _as_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            return int(stripped)
    return None


def _normalize_username(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower().removeprefix("@")
    if not normalized:
        return None
    return normalized
