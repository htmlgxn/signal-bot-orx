from __future__ import annotations

from pathlib import Path

import pytest

import signal_bot_orx.chat_prompt as chat_prompt_module
from signal_bot_orx.chat_context import ChatTurn
from signal_bot_orx.chat_prompt import (
    DEFAULT_CHAT_SYSTEM_PROMPT,
    build_chat_messages,
    coerce_plain_text_reply,
)


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


def test_default_system_prompt_loaded_from_markdown_file() -> None:
    prompt_dir = (
        Path(__file__).parents[1]
        / "src"
        / "signal_bot_orx"
    )
    local_prompt_path = prompt_dir / "chat_system_prompt.md"
    default_prompt_path = prompt_dir / "default_chat_system_prompt.md"
    expected_path = default_prompt_path
    if local_prompt_path.exists() and local_prompt_path.read_text(
        encoding="utf-8"
    ).strip():
        expected_path = local_prompt_path

    assert (
        expected_path.read_text(encoding="utf-8").strip() == DEFAULT_CHAT_SYSTEM_PROMPT
    )


def test_default_system_prompt_prefers_local_prompt_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt_dir = (
        Path(__file__).parents[1]
        / "src"
        / "signal_bot_orx"
    )
    monkeypatch.setattr(
        chat_prompt_module,
        "_LOCAL_CHAT_PROMPT_PATH",
        prompt_dir / "chat_system_prompt.md",
    )
    monkeypatch.setattr(
        chat_prompt_module,
        "_DEFAULT_CHAT_PROMPT_PATH",
        prompt_dir / "default_chat_system_prompt.md",
    )

    loaded = chat_prompt_module._load_default_chat_system_prompt()
    assert loaded == (prompt_dir / "chat_system_prompt.md").read_text(
        encoding="utf-8"
    ).strip()
