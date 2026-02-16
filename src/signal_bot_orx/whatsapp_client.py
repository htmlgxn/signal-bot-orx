from __future__ import annotations

import base64

import httpx

from signal_bot_orx.messaging import MessageSendError
from signal_bot_orx.types import Target


class WhatsAppSendError(MessageSendError):
    pass


class WhatsAppClient:
    def __init__(
        self,
        *,
        base_url: str,
        http_client: httpx.AsyncClient,
        token: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._http_client = http_client
        self._token = token

    async def send_text(
        self,
        *,
        target: Target,
        message: str,
        fallback_recipient: str | None = None,
    ) -> None:
        del fallback_recipient
        chat_id = _target_chat_id(target)
        payload = {"chatId": chat_id, "text": message}
        await self._post_json("/send/text", payload)

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
        payload: dict[str, object] = {
            "chatId": chat_id,
            "imageBase64": base64.b64encode(image_bytes).decode("ascii"),
            "mimeType": content_type,
        }
        if caption:
            payload["caption"] = caption
        await self._post_json("/send/image", payload)

    async def _post_json(self, path: str, payload: dict[str, object]) -> None:
        url = f"{self._base_url}{path}"
        headers: dict[str, str] = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        try:
            response = await self._http_client.post(
                url,
                json=payload,
                headers=headers or None,
                timeout=30,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise WhatsAppSendError("WhatsApp bridge network error.") from exc

        if response.status_code < 400:
            return

        detail = response.text.strip() or "No error detail"
        if len(detail) > 240:
            detail = f"{detail[:240]}..."
        raise WhatsAppSendError(
            f"WhatsApp bridge send failed ({response.status_code}): {detail}"
        )


def _target_chat_id(target: Target) -> str:
    chat_id = target.group_id or target.recipient
    if not chat_id:
        raise WhatsAppSendError("Missing WhatsApp chat target.")
    return chat_id
