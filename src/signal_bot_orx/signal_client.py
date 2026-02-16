from __future__ import annotations

import asyncio
import base64
import logging
from typing import Protocol

import httpx

from signal_bot_orx.group_resolver import GroupResolver, ResolvedGroupRecipients
from signal_bot_orx.messaging import MessageSendError
from signal_bot_orx.types import Target

logger = logging.getLogger(__name__)


class SignalSendError(MessageSendError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        recipient: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.recipient = recipient


class GroupResolverLike(Protocol):
    async def resolve(self, group_id: str) -> ResolvedGroupRecipients: ...


class SignalClient:
    def __init__(
        self,
        *,
        base_url: str,
        sender_number: str,
        http_client: httpx.AsyncClient,
        group_resolver: GroupResolverLike | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._sender_number = sender_number
        self._http_client = http_client
        self._group_resolver = group_resolver or GroupResolver(
            base_url=base_url,
            sender_number=sender_number,
            http_client=http_client,
        )

    async def send_text(
        self,
        *,
        target: Target,
        message: str,
        fallback_recipient: str | None = None,
    ) -> None:
        payload = {"message": message}
        await self._post_with_retry(
            target=target,
            payload=payload,
            fallback_recipient=fallback_recipient,
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
        payload: dict[str, object] = {}
        if caption:
            payload["message"] = caption

        ext = _suffix_for_content_type(content_type)
        payload["base64_attachments"] = [
            f"data:{content_type};filename=image.{ext};base64,"
            f"{base64.b64encode(image_bytes).decode('ascii')}"
        ]
        await self._post_with_retry(
            target=target,
            payload=payload,
            fallback_recipient=fallback_recipient,
        )

    async def _post_with_retry(
        self,
        *,
        target: Target,
        payload: dict[str, object],
        fallback_recipient: str | None = None,
    ) -> None:
        if target.group_id:
            resolved = await self._group_resolver.resolve(target.group_id)
            last_error: SignalSendError | None = None
            for recipient in resolved.recipients:
                try:
                    await self._post_to_recipient(
                        recipient=recipient,
                        payload=payload,
                    )
                    return
                except SignalSendError as exc:
                    last_error = exc
                    if exc.status_code == 400:
                        continue
                    raise

            if last_error is not None:
                if fallback_recipient and last_error.status_code == 400:
                    logger.warning(
                        "group_send_failed_dm_fallback sender=%s group_id=%s "
                        "fallback_recipient=%s candidate_count=%d final_candidate=%s",
                        self._sender_number,
                        target.group_id,
                        fallback_recipient,
                        len(resolved.recipients),
                        last_error.recipient,
                    )
                    try:
                        await self._post_to_recipient(
                            recipient=fallback_recipient,
                            payload=payload,
                        )
                        logger.info(
                            "group_send_dm_fallback_succeeded sender=%s group_id=%s "
                            "fallback_recipient=%s",
                            self._sender_number,
                            target.group_id,
                            fallback_recipient,
                        )
                        return
                    except SignalSendError:
                        logger.warning(
                            "group_send_dm_fallback_failed sender=%s group_id=%s "
                            "fallback_recipient=%s",
                            self._sender_number,
                            target.group_id,
                            fallback_recipient,
                        )

                raise SignalSendError(
                    f"{last_error} (resolver_cache_refreshed={resolved.cache_refreshed}, "
                    f"candidate_count={len(resolved.recipients)}, "
                    f"final_candidate={last_error.recipient})",
                    status_code=last_error.status_code,
                    recipient=last_error.recipient,
                ) from last_error
            raise SignalSendError("Signal send failed unexpectedly")

        if target.recipient:
            await self._post_to_recipient(
                recipient=target.recipient,
                payload=payload,
            )
            return

        raise SignalSendError("Missing target recipient")

    async def _post_to_recipient(
        self, *, recipient: str, payload: dict[str, object]
    ) -> None:
        url = f"{self._base_url}/v2/send"
        body = {
            "number": self._sender_number,
            "recipients": [recipient],
            **payload,
        }

        for attempt in range(2):
            try:
                response = await self._http_client.post(url, json=body, timeout=30)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt == 1:
                    raise SignalSendError(
                        f"Signal send failed due to network error (recipient={recipient})",
                        recipient=recipient,
                    ) from exc
                await asyncio.sleep(0.5)
                continue

            if response.status_code < 400:
                return

            if 500 <= response.status_code < 600 and attempt == 0:
                await asyncio.sleep(0.5)
                continue

            detail = _extract_response_detail(response)
            raise SignalSendError(
                f"Signal send failed with status {response.status_code} "
                f"(recipient={recipient}): {detail}",
                status_code=response.status_code,
                recipient=recipient,
            )


def _suffix_for_content_type(content_type: str) -> str:
    if "png" in content_type:
        return "png"
    if "jpeg" in content_type or "jpg" in content_type:
        return "jpg"
    if "webp" in content_type:
        return "webp"
    return "bin"


def _extract_response_detail(response: httpx.Response) -> str:
    detail = ""
    try:
        payload = response.json()
        if isinstance(payload, dict):
            detail = str(
                payload.get("error")
                or payload.get("message")
                or payload.get("msg")
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
