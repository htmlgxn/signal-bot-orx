from __future__ import annotations

from signal_box_orx.config import Settings
from signal_box_orx.types import IncomingMessage, Target
from signal_box_orx.webhook import is_authorized_message


def _settings(
    *, numbers: set[str], groups: set[str], disable_auth: bool = False
) -> Settings:
    return Settings(
        signal_api_base_url="http://localhost:8080",
        signal_sender_number="+15550001111",
        signal_sender_uuid=None,
        signal_allowed_numbers=frozenset(numbers),
        signal_allowed_group_ids=frozenset(groups),
        signal_disable_auth=disable_auth,
        openrouter_chat_api_key="or-key-chat",
        openrouter_model="openai/gpt-4o-mini",
    )


def test_authorized_by_number() -> None:
    settings = _settings(numbers={"+15550002222"}, groups=set())
    message = IncomingMessage(
        sender="+15550002222",
        text="hello",
        timestamp=1,
        target=Target(recipient="+15550002222", group_id=None),
    )

    assert is_authorized_message(message, settings) is True


def test_authorized_by_group_id() -> None:
    settings = _settings(numbers=set(), groups={"group-123"})
    message = IncomingMessage(
        sender="+19999999999",
        text="hello",
        timestamp=1,
        target=Target(recipient="+19999999999", group_id="group-123"),
    )

    assert is_authorized_message(message, settings) is True


def test_unauthorized_when_not_in_any_allowlist() -> None:
    settings = _settings(numbers={"+15550002222"}, groups={"group-123"})
    message = IncomingMessage(
        sender="+17777777777",
        text="hello",
        timestamp=1,
        target=Target(recipient="+17777777777", group_id="group-999"),
    )

    assert is_authorized_message(message, settings) is False


def test_authorized_when_disable_auth_enabled() -> None:
    settings = _settings(numbers=set(), groups=set(), disable_auth=True)
    message = IncomingMessage(
        sender="+17777777777",
        text="hello",
        timestamp=1,
        target=Target(recipient="+17777777777", group_id="group-999"),
    )

    assert is_authorized_message(message, settings) is True
