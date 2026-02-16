from __future__ import annotations

from typing import Any

from signal_bot_orx.parsing import as_dict, first_non_empty_str
from signal_bot_orx.types import IncomingMessage, Target


def parse_whatsapp_webhook(payload: dict[str, Any]) -> IncomingMessage | None:
    event = _resolve_event(payload)
    message_data = as_dict(event.get("message"))

    sender = first_non_empty_str(
        event,
        "from",
        "sender",
        "fromNumber",
        "author",
    ) or first_non_empty_str(
        message_data,
        "from",
        "sender",
        "author",
    )
    if sender is None:
        return None

    text = (
        first_non_empty_str(message_data, "text", "body", "message")
        or first_non_empty_str(event, "text", "body", "message")
        or ""
    )
    if not text:
        return None

    chat_id = first_non_empty_str(
        event,
        "chatId",
        "chat_id",
        "conversation",
        "thread",
    ) or first_non_empty_str(
        message_data,
        "chatId",
        "chat_id",
        "conversation",
        "thread",
    )

    is_group = bool(event.get("isGroup"))
    if not is_group and isinstance(chat_id, str):
        is_group = chat_id.endswith("@g.us")

    timestamp_raw = event.get("timestamp") or message_data.get("timestamp")
    timestamp = int(timestamp_raw) if isinstance(timestamp_raw, int) else 0

    target = (
        Target(recipient=sender, group_id=chat_id if is_group else None)
        if is_group
        else Target(recipient=sender, group_id=None)
    )
    return IncomingMessage(
        sender=sender,
        text=text,
        timestamp=timestamp,
        target=target,
        transport="whatsapp",
    )


def _resolve_event(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("event"), dict):
        return as_dict(payload.get("event"))
    if isinstance(payload.get("data"), dict):
        return as_dict(payload.get("data"))
    return payload
