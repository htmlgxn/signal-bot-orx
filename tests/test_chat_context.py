from __future__ import annotations

import pytest

from signal_box_orx.chat_context import ChatContextStore


def test_chat_context_trims_to_max_turns() -> None:
    store = ChatContextStore(max_turns=2, ttl_seconds=1800)

    store.append_turn("group:1", user_text="u1", assistant_text="a1")
    store.append_turn("group:1", user_text="u2", assistant_text="a2")
    store.append_turn("group:1", user_text="u3", assistant_text="a3")

    history = store.get_history("group:1")

    assert len(history) == 4
    assert [turn.content for turn in history] == ["u2", "a2", "u3", "a3"]


def test_chat_context_expires_by_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 0.0

    def fake_monotonic() -> float:
        return now

    monkeypatch.setattr("signal_box_orx.chat_context.time.monotonic", fake_monotonic)

    store = ChatContextStore(max_turns=2, ttl_seconds=10)
    store.append_turn("group:1", user_text="u1", assistant_text="a1")

    assert store.get_history("group:1")

    now = 11.0
    assert store.get_history("group:1") == ()
