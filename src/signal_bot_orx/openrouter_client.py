from __future__ import annotations

import asyncio
import base64
import binascii
from typing import Any

import httpx


class ChatReplyError(Exception):
    def __init__(self, user_message: str, *, status_code: int | None = None) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.status_code = status_code


class ImageGenerationError(Exception):
    def __init__(self, user_message: str, *, status_code: int | None = None) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.status_code = status_code


class OpenRouterClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        http_client: httpx.AsyncClient,
        base_url: str,
        timeout_seconds: float,
        max_output_tokens: int,
        temperature: float,
        http_referer: str | None = None,
        app_title: str | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._http_client = http_client
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._temperature = temperature
        self._http_referer = http_referer
        self._app_title = app_title

    async def generate_reply(self, messages: list[dict[str, str]]) -> str:
        url = f"{self._base_url}/chat/completions"
        headers = _build_headers(
            api_key=self._api_key,
            http_referer=self._http_referer,
            app_title=self._app_title,
        )

        payload = {
            "model": self._model,
            "messages": messages,
            "max_tokens": self._max_output_tokens,
            "temperature": self._temperature,
        }

        for attempt in range(3):
            try:
                response = await self._http_client.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=self._timeout_seconds,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt == 2:
                    raise ChatReplyError("Chat service timed out. Try again.") from exc
                await asyncio.sleep(0.5 * (attempt + 1))
                continue

            if response.status_code < 400:
                return _extract_reply_text(response)

            if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue

            if response.status_code in {401, 403}:
                raise ChatReplyError(
                    "Chat service authorization failed.",
                    status_code=response.status_code,
                )

            detail = _extract_response_detail(response)
            raise ChatReplyError(
                f"Chat reply failed: {detail}",
                status_code=response.status_code,
            )

        raise ChatReplyError("Chat service failed unexpectedly.")


class OpenRouterImageClient:
    def __init__(
        self,
        *,
        api_key: str,
        http_client: httpx.AsyncClient,
        base_url: str,
        timeout_seconds: float,
        http_referer: str | None = None,
        app_title: str | None = None,
    ) -> None:
        self._api_key = api_key
        self._http_client = http_client
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._http_referer = http_referer
        self._app_title = app_title

    async def generate_images(
        self, *, prompt: str, model: str
    ) -> list[tuple[bytes, str]]:
        url = f"{self._base_url}/chat/completions"
        headers = _build_headers(
            api_key=self._api_key,
            http_referer=self._http_referer,
            app_title=self._app_title,
        )
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "modalities": ["image"],
        }

        for attempt in range(3):
            try:
                response = await self._http_client.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=self._timeout_seconds,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt == 2:
                    raise ImageGenerationError(
                        "Image generation timed out. Try again."
                    ) from exc
                await asyncio.sleep(0.5 * (attempt + 1))
                continue

            if response.status_code < 400:
                return await _extract_generated_images(
                    response,
                    http_client=self._http_client,
                    timeout_seconds=self._timeout_seconds,
                )

            if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue

            if response.status_code in {401, 403}:
                raise ImageGenerationError(
                    "Image service authorization failed.",
                    status_code=response.status_code,
                )

            detail = _extract_response_detail(response)
            raise ImageGenerationError(
                f"Image generation failed: {detail}",
                status_code=response.status_code,
            )

        raise ImageGenerationError("Image generation failed unexpectedly.")


def _extract_reply_text(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError as exc:
        raise ChatReplyError("Chat service returned invalid JSON.") from exc

    if not isinstance(payload, dict):
        raise ChatReplyError("Chat service returned an invalid response format.")

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ChatReplyError("Chat service returned an empty reply.")

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise ChatReplyError("Chat service returned an invalid reply payload.")

    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise ChatReplyError("Chat service returned an invalid message payload.")

    content = _extract_content_text(message.get("content"))
    if not content:
        raise ChatReplyError("Chat service returned an empty reply.")

    return content


def _extract_content_text(content: Any) -> str:
    if isinstance(content, str):
        return " ".join(content.split())

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        return " ".join(parts)

    return ""


def _extract_response_detail(response: httpx.Response) -> str:
    detail = ""
    try:
        payload = response.json()
        if isinstance(payload, dict):
            detail = str(
                payload.get("error")
                or payload.get("message")
                or payload.get("detail")
                or payload
            )
        else:
            detail = str(payload)
    except ValueError:
        detail = response.text

    detail = " ".join(detail.strip().split())
    if not detail:
        return "No error detail"
    if len(detail) > 240:
        return f"{detail[:240]}..."
    return detail


def _build_headers(
    *, api_key: str, http_referer: str | None, app_title: str | None
) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if http_referer:
        headers["HTTP-Referer"] = http_referer
    if app_title:
        headers["X-Title"] = app_title
    return headers


async def _extract_generated_images(
    response: httpx.Response,
    *,
    http_client: httpx.AsyncClient,
    timeout_seconds: float,
) -> list[tuple[bytes, str]]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise ImageGenerationError("Image service returned invalid JSON.") from exc

    if not isinstance(payload, dict):
        raise ImageGenerationError("Image service returned an invalid response format.")

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ImageGenerationError("Image service returned an empty image payload.")

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise ImageGenerationError("Image service returned an invalid image payload.")

    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise ImageGenerationError("Image service returned an invalid image payload.")

    images = message.get("images")
    if not isinstance(images, list) or not images:
        raise ImageGenerationError("Image service returned an empty image payload.")

    results: list[tuple[bytes, str]] = []
    last_error: ImageGenerationError | None = None
    for image_item in images:
        image_ref = _extract_image_reference(image_item)
        if image_ref is None:
            continue
        try:
            generated = await _resolve_generated_image(
                image_ref,
                http_client=http_client,
                timeout_seconds=timeout_seconds,
            )
        except ImageGenerationError as exc:
            last_error = exc
            continue

        results.append(generated)

    if results:
        return results

    if last_error is not None:
        raise last_error

    raise ImageGenerationError("Image service returned an invalid image payload.")


def _extract_image_reference(image_item: Any) -> str | None:
    if not isinstance(image_item, dict):
        return None

    image_url = image_item.get("image_url")
    if isinstance(image_url, dict):
        for key in ("url", "image_url"):
            value = image_url.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    elif isinstance(image_url, str) and image_url.strip():
        return image_url.strip()

    for key in ("url", "image"):
        value = image_item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return None


async def _resolve_generated_image(
    image_ref: str,
    *,
    http_client: httpx.AsyncClient,
    timeout_seconds: float,
) -> tuple[bytes, str]:
    if image_ref.startswith("data:"):
        return _decode_data_image_url(image_ref)

    if image_ref.startswith("https://") or image_ref.startswith("http://"):
        try:
            image_response = await http_client.get(image_ref, timeout=timeout_seconds)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ImageGenerationError(
                "Image generation timed out. Try again."
            ) from exc

        if image_response.status_code >= 400:
            detail = _extract_response_detail(image_response)
            raise ImageGenerationError(
                f"Image generation failed: {detail}",
                status_code=image_response.status_code,
            )

        if not image_response.content:
            raise ImageGenerationError("Image service returned an empty image.")

        content_type = (
            image_response.headers.get("content-type", "image/png")
            .split(";")[0]
            .strip()
        )
        return image_response.content, content_type or "image/png"

    raise ImageGenerationError("Image service returned an invalid image payload.")


def _decode_data_image_url(image_ref: str) -> tuple[bytes, str]:
    prefix, separator, data = image_ref.partition(",")
    if not separator or not data.strip():
        raise ImageGenerationError("Image service returned an invalid image payload.")

    if ";base64" not in prefix.lower():
        raise ImageGenerationError("Image service returned invalid base64 image data.")

    metadata = prefix[len("data:") :]
    content_type = "image/png"
    if metadata:
        media_type = metadata.split(";", maxsplit=1)[0].strip()
        if media_type:
            content_type = media_type

    try:
        image_bytes = base64.b64decode(data.strip())
    except (ValueError, binascii.Error) as exc:
        raise ImageGenerationError(
            "Image service returned invalid base64 image data."
        ) from exc

    if not image_bytes:
        raise ImageGenerationError("Image service returned an empty image.")

    return image_bytes, content_type
