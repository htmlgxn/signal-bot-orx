from __future__ import annotations

from signal_bot_orx.chat_context import ChatTurn
from signal_bot_orx.chat_prompt import build_chat_messages, coerce_plain_text_reply


def test_build_chat_messages_includes_system_prompt_and_history() -> None:
    messages = build_chat_messages(
        system_prompt="system prompt",
        history=(
            ChatTurn(role="user", content="old question"),
            ChatTurn(role="assistant", content="old answer"),
        ),
        prompt="new question",
    )

    assert messages == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "new question"},
    ]


def test_coerce_plain_text_reply_removes_markdown() -> None:
    text = (
        "# Heading\n"
        "- **hello** from `sigbot`\n"
        "> [read this](https://example.com)\n"
        "```md\n"
        "* fenced item*\n"
        "```"
    )

    assert coerce_plain_text_reply(text) == (
        "Heading\nhello from sigbot\nread this (https://example.com)\nfenced item"
    )


def test_coerce_plain_text_reply_is_idempotent_for_plain_text() -> None:
    text = "just a clean reply\nwith two lines"
    assert coerce_plain_text_reply(text) == text


def test_coerce_plain_text_reply_splits_inline_numbered_list() -> None:
    text = (
        "1. First thing. 2. Second thing. 3. Third thing. "
        "4. Fourth thing. 5. Fifth thing."
    )
    assert coerce_plain_text_reply(text) == (
        "1. First thing.\n"
        "2. Second thing.\n"
        "3. Third thing.\n"
        "4. Fourth thing.\n"
        "5. Fifth thing."
    )
