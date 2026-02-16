from __future__ import annotations

from signal_bot_orx.telegram import parse_telegram_webhook


def test_parse_telegram_webhook_private_message() -> None:
    payload = {
        "update_id": 1,
        "message": {
            "message_id": 12,
            "date": 1730000000,
            "text": "hello",
            "from": {"id": 12345, "is_bot": False},
            "chat": {"id": 12345, "type": "private"},
        },
    }

    parsed = parse_telegram_webhook(payload, bot_username="sigbot")

    assert parsed is not None
    assert parsed.transport == "telegram"
    assert parsed.sender == "12345"
    assert parsed.target.recipient == "12345"
    assert parsed.target.group_id is None
    assert parsed.directed_to_bot is False


def test_parse_telegram_webhook_group_mention_sets_directed() -> None:
    payload = {
        "update_id": 1,
        "message": {
            "message_id": 12,
            "date": 1730000000,
            "text": "@sigbot summarize",
            "entities": [{"type": "mention", "offset": 0, "length": 7}],
            "from": {"id": 12345, "is_bot": False},
            "chat": {"id": -10099, "type": "supergroup"},
        },
    }

    parsed = parse_telegram_webhook(payload, bot_username="@sigbot")

    assert parsed is not None
    assert parsed.target.group_id == "-10099"
    assert parsed.target.recipient == "12345"
    assert parsed.directed_to_bot is True


def test_parse_telegram_webhook_reply_to_bot_sets_directed() -> None:
    payload = {
        "update_id": 1,
        "message": {
            "message_id": 12,
            "date": 1730000000,
            "text": "follow up",
            "from": {"id": 12345, "is_bot": False},
            "chat": {"id": -10099, "type": "supergroup"},
            "reply_to_message": {
                "from": {"id": 999, "is_bot": True, "username": "sigbot"}
            },
        },
    }

    parsed = parse_telegram_webhook(payload, bot_username="sigbot")

    assert parsed is not None
    assert parsed.directed_to_bot is True


def test_parse_telegram_webhook_ignores_non_text_updates() -> None:
    payload = {
        "update_id": 1,
        "message": {
            "message_id": 12,
            "date": 1730000000,
            "photo": [{"file_id": "abc"}],
            "from": {"id": 12345, "is_bot": False},
            "chat": {"id": 12345, "type": "private"},
        },
    }

    assert parse_telegram_webhook(payload, bot_username="sigbot") is None
