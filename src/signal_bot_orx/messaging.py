from __future__ import annotations

from typing import Protocol

from signal_bot_orx.types import Target


class MessageSendError(Exception):
    pass


class MessengerClient(Protocol):
    async def send_text(
        self,
        *,
        target: Target,
        message: str,
        fallback_recipient: str | None = None,
    ) -> None: ...

    async def send_image(
        self,
        *,
        target: Target,
        image_bytes: bytes,
        content_type: str,
        caption: str | None = None,
        fallback_recipient: str | None = None,
    ) -> None: ...
