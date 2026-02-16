from __future__ import annotations

import httpx
import pytest

from signal_bot_orx.telegram_client import TelegramClient, TelegramSendError
from signal_bot_orx.types import Target


@pytest.mark.anyio
async def test_telegram_client_send_text_success() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/sendMessage")
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = TelegramClient(bot_token="token", http_client=http_client)
        await client.send_text(target=Target(recipient="123"), message="hello")


@pytest.mark.anyio
async def test_telegram_client_send_image_success() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/sendPhoto")
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = TelegramClient(bot_token="token", http_client=http_client)
        await client.send_image(
            target=Target(recipient="123"),
            image_bytes=b"img",
            content_type="image/png",
            caption="cap",
        )


@pytest.mark.anyio
async def test_telegram_client_http_error_maps_to_send_error() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad request")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = TelegramClient(bot_token="token", http_client=http_client)
        with pytest.raises(TelegramSendError):
            await client.send_text(target=Target(recipient="123"), message="hello")


@pytest.mark.anyio
async def test_telegram_client_missing_target_raises() -> None:
    async with httpx.AsyncClient() as http_client:
        client = TelegramClient(bot_token="token", http_client=http_client)
        with pytest.raises(TelegramSendError):
            await client.send_text(target=Target(), message="hello")
