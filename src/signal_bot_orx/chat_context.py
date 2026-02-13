from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True)
class ChatTurn:
    role: str
    content: str


@dataclass
class _Conversation:
    turns: list[ChatTurn]
    expires_at: float


class ChatContextStore:
    def __init__(self, *, max_turns: int, ttl_seconds: int) -> None:
        self._max_turns = max(1, max_turns)
        self._ttl_seconds = max(1, ttl_seconds)
        self._conversations: dict[str, _Conversation] = {}

    def get_history(self, conversation_key: str) -> tuple[ChatTurn, ...]:
        now = time.monotonic()
        self._purge(now)

        conversation = self._conversations.get(conversation_key)
        if conversation is None:
            return ()

        conversation.expires_at = now + self._ttl_seconds
        return tuple(conversation.turns)

    def append_turn(
        self,
        conversation_key: str,
        *,
        user_text: str,
        assistant_text: str,
    ) -> None:
        now = time.monotonic()
        self._purge(now)

        conversation = self._conversations.get(conversation_key)
        if conversation is None:
            conversation = _Conversation(turns=[], expires_at=now + self._ttl_seconds)
            self._conversations[conversation_key] = conversation

        conversation.turns.extend(
            (
                ChatTurn(role="user", content=user_text),
                ChatTurn(role="assistant", content=assistant_text),
            )
        )

        max_messages = self._max_turns * 2
        if len(conversation.turns) > max_messages:
            conversation.turns = conversation.turns[-max_messages:]

        conversation.expires_at = now + self._ttl_seconds

    def _purge(self, now: float) -> None:
        expired = [
            key
            for key, conversation in self._conversations.items()
            if conversation.expires_at <= now
        ]
        for key in expired:
            del self._conversations[key]
