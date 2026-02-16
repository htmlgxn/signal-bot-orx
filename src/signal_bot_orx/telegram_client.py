from __future__ import annotations

import httpx

from signal_bot_orx.messaging import MessageSendError
from signal_bot_orx.types import Target


class TelegramSendError(MessageSendError):
    pass


class TelegramClient:
    def __init__(
        self,
        *,
        bot_token: str,
        http_client: httpx.AsyncClient,
        base_url: str = "https://api.telegram.org",
    ) -> None:
        self._http_client = http_client
        self._base_url = base_url.rstrip("/")
        self._bot_token = bot_token.strip()

    async def send_text(
        self,
        *,
        target: Target,
        message: str,
        fallback_recipient: str | None = None,
    ) -> None:
        del fallback_recipient
        chat_id = _target_chat_id(target)
        await self._post_json(
            method="sendMessage",
            payload={"chat_id": chat_id, "text": message},
        )

    async def send_image(
        self,
        *,
        target: Target,
        image_bytes: bytes,
        content_type: str,
        caption: str | None = None,
        fallback_recipient: str | None = None,
    ) -> None:
        del fallback_recipient
        chat_id = _target_chat_id(target)
        form_data = {"chat_id": chat_id}
        if caption:
            form_data["caption"] = caption

        files = {
            "photo": (
                _photo_filename_for_content_type(content_type),
                image_bytes,
                content_type,
            )
        }
        await self._post_multipart(
            method="sendPhoto",
            data=form_data,
            files=files,
        )

    async def _post_json(self, *, method: str, payload: dict[str, object]) -> None:
        url = f"{self._base_url}/bot{self._bot_token}/{method}"
        try:
            response = await self._http_client.post(url, json=payload, timeout=30)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise TelegramSendError(
                "Telegram send failed due to network error."
            ) from exc

        _raise_for_telegram_error(response)

    async def _post_multipart(
        self,
        *,
        method: str,
        data: dict[str, str],
        files: dict[str, tuple[str, bytes, str]],
    ) -> None:
        url = f"{self._base_url}/bot{self._bot_token}/{method}"
        try:
            response = await self._http_client.post(
                url,
                data=data,
                files=files,
                timeout=30,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise TelegramSendError(
                "Telegram send failed due to network error."
            ) from exc

        _raise_for_telegram_error(response)


def _target_chat_id(target: Target) -> str:
    chat_id = target.group_id or target.recipient
    if not chat_id:
        raise TelegramSendError("Missing Telegram chat target.")
    return chat_id


def _photo_filename_for_content_type(content_type: str) -> str:
    if "png" in content_type:
        return "image.png"
    if "jpeg" in content_type or "jpg" in content_type:
        return "image.jpg"
    if "webp" in content_type:
        return "image.webp"
    return "image.bin"


def _raise_for_telegram_error(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    detail = response.text.strip() or "No error detail"
    if len(detail) > 240:
        detail = f"{detail[:240]}..."
    raise TelegramSendError(
        f"Telegram API send failed ({response.status_code}): {detail}"
    )
