from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from signal_box_orx.parsing import as_dict, first_non_empty_str


@dataclass(frozen=True)
class MentionSpan:
    start: int
    length: int
    number: str | None = None
    uuid: str | None = None


@dataclass(frozen=True)
class Target:
    recipient: str | None = None
    group_id: str | None = None


@dataclass(frozen=True)
class IncomingMessage:
    sender: str
    text: str
    timestamp: int
    target: Target
    mentions: tuple[MentionSpan, ...] = ()


def parse_signal_webhook(payload: dict[str, Any]) -> IncomingMessage | None:
    envelope = _resolve_envelope(payload)
    data_message = as_dict(envelope.get("dataMessage"))

    sender = first_non_empty_str(envelope, "sourceNumber", "source")
    if sender is None:
        return None

    message = first_non_empty_str(data_message, "message")
    if message is None:
        message = first_non_empty_str(envelope, "message")
    if message is None:
        return None

    group_info = as_dict(data_message.get("groupInfo"))
    group_id = first_non_empty_str(group_info, "groupId", "groupIdHex")

    timestamp = data_message.get("timestamp") or envelope.get("timestamp")
    if not isinstance(timestamp, int):
        timestamp = 0

    mentions = _extract_mentions(data_message)
    target = Target(recipient=sender, group_id=group_id)
    return IncomingMessage(
        sender=sender,
        text=message,
        timestamp=timestamp,
        target=target,
        mentions=mentions,
    )


def dedupe_key(message: IncomingMessage) -> str:
    return f"{message.sender}|{message.timestamp}|{message.text.strip()}"


def metadata_mentions_bot(
    message: IncomingMessage,
    bot_number: str,
    bot_uuid: str | None = None,
) -> bool:
    normalized_bot_number = _normalize_number(bot_number)
    normalized_bot_uuid = bot_uuid.strip().lower() if bot_uuid else None
    for mention in message.mentions:
        if (
            mention.number is not None
            and _normalize_number(mention.number) == normalized_bot_number
        ):
            return True
        if (
            mention.uuid is not None
            and normalized_bot_uuid
            and mention.uuid.strip().lower() == normalized_bot_uuid
        ):
            return True
    return False


def strip_mention_spans(text: str, mentions: tuple[MentionSpan, ...]) -> str:
    cleaned = text
    for mention in sorted(mentions, key=lambda item: item.start, reverse=True):
        start = mention.start
        end = mention.start + mention.length
        if start < 0 or end <= start or end > len(cleaned):
            continue
        cleaned = f"{cleaned[:start]} {cleaned[end:]}"
    return " ".join(cleaned.split())


def _extract_mentions(data_message: dict[str, Any]) -> tuple[MentionSpan, ...]:
    parsed_mentions: list[MentionSpan] = []

    raw_mentions = data_message.get("mentions")
    if isinstance(raw_mentions, list):
        for item in raw_mentions:
            mention = _parse_mention(item)
            if mention is not None:
                parsed_mentions.append(mention)

    raw_ranges = data_message.get("bodyRanges")
    if isinstance(raw_ranges, list):
        for item in raw_ranges:
            mention = _parse_mention(item)
            if mention is not None:
                parsed_mentions.append(mention)

    return tuple(parsed_mentions)


def _parse_mention(value: object) -> MentionSpan | None:
    if not isinstance(value, dict):
        return None

    mention_value = as_dict(value)

    start = _as_int(mention_value.get("start"))
    length = _as_int(mention_value.get("length"))
    if start is None or length is None or start < 0 or length <= 0:
        return None

    number = first_non_empty_str(
        mention_value,
        "number",
        "recipientNumber",
        "recipient",
        "phoneNumber",
        "sourceNumber",
        "mentionNumber",
    )
    uuid = first_non_empty_str(
        mention_value,
        "uuid",
        "recipientUuid",
        "mentionUuid",
        "aci",
        "mentionAci",
    )

    if number is None and uuid is None:
        return None

    return MentionSpan(start=start, length=length, number=number, uuid=uuid)


def _as_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit() or (stripped.startswith("-") and stripped[1:].isdigit()):
            return int(stripped)
    return None


def _resolve_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    params = as_dict(payload.get("params"))
    params_envelope = as_dict(params.get("envelope"))
    if params_envelope:
        return params_envelope

    top_level_envelope = as_dict(payload.get("envelope"))
    if top_level_envelope:
        return top_level_envelope

    return payload


def _normalize_number(value: str) -> str:
    return "".join(char for char in value if char.isdigit() or char == "+")
