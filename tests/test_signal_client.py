from __future__ import annotations

import json
from typing import cast

import httpx
import pytest

from signal_box_orx.group_resolver import ResolvedGroupRecipients
from signal_box_orx.signal_client import (
    GroupResolverLike,
    SignalClient,
    SignalSendError,
)
from signal_box_orx.types import Target


class StaticGroupResolver:
    def __init__(
        self,
        *,
        recipients: tuple[str, ...],
        cache_refreshed: bool = False,
    ) -> None:
        self._resolved = ResolvedGroupRecipients(
            recipients=recipients,
            cache_refreshed=cache_refreshed,
        )

    async def resolve(self, _: str) -> ResolvedGroupRecipients:
        return self._resolved


def _resolver(
    *, recipients: tuple[str, ...], cache_refreshed: bool = False
) -> GroupResolverLike:
    return cast(
        GroupResolverLike,
        StaticGroupResolver(
            recipients=recipients,
            cache_refreshed=cache_refreshed,
        ),
    )


@pytest.mark.anyio
async def test_signal_client_send_text_payload() -> None:
    captured: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(201, json={"timestamp": 1})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        signal = SignalClient(
            base_url="http://signal.local",
            sender_number="+1999",
            http_client=client,
            group_resolver=_resolver(recipients=("group.x",)),
        )
        await signal.send_text(target=Target(recipient="+1222"), message="hello")

    assert captured
    payload = captured[0]
    assert payload["number"] == "+1999"
    assert payload["recipients"] == ["+1222"]
    assert payload["message"] == "hello"


@pytest.mark.anyio
async def test_signal_client_send_image_payload() -> None:
    captured: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(201, json={"timestamp": 1})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        signal = SignalClient(
            base_url="http://signal.local",
            sender_number="+1999",
            http_client=client,
            group_resolver=_resolver(recipients=("group.x",)),
        )
        await signal.send_image(
            target=Target(recipient="+1222"),
            image_bytes=b"raw",
            content_type="image/png",
            caption="done",
        )

    payload = captured[0]
    assert payload["number"] == "+1999"
    assert payload["message"] == "done"
    attachments = payload["base64_attachments"]
    assert isinstance(attachments, list)
    assert attachments[0].startswith("data:image/png;filename=image.png;base64,")


@pytest.mark.anyio
async def test_signal_client_group_uses_resolver_primary_candidate() -> None:
    captured: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(201, json={"timestamp": 1})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        signal = SignalClient(
            base_url="http://signal.local",
            sender_number="+1999",
            http_client=client,
            group_resolver=_resolver(
                recipients=("group.canonical", "group.raw", "raw"),
            ),
        )
        await signal.send_text(target=Target(group_id="group-abc"), message="hello")

    payload = captured[0]
    assert payload["number"] == "+1999"
    assert payload["recipients"] == ["group.canonical"]


@pytest.mark.anyio
async def test_signal_client_group_falls_back_to_next_resolver_candidate_on_400() -> (
    None
):
    captured: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        captured.append(payload)
        if len(captured) == 1:
            return httpx.Response(400, json={"error": "Failed to send message"})
        return httpx.Response(201, json={"timestamp": 2})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        signal = SignalClient(
            base_url="http://signal.local",
            sender_number="+1999",
            http_client=client,
            group_resolver=_resolver(
                recipients=("group.canonical", "group.raw", "raw"),
            ),
        )
        await signal.send_text(target=Target(group_id="group-abc"), message="hello")

    assert len(captured) == 2
    assert captured[0]["recipients"] == ["group.canonical"]
    assert captured[1]["recipients"] == ["group.raw"]


@pytest.mark.anyio
async def test_signal_client_group_terminal_error_includes_refresh_flag() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "Failed to send message"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        signal = SignalClient(
            base_url="http://signal.local",
            sender_number="+1999",
            http_client=client,
            group_resolver=_resolver(
                recipients=("group.canonical", "group.raw"),
                cache_refreshed=True,
            ),
        )
        with pytest.raises(SignalSendError) as exc:
            await signal.send_text(target=Target(group_id="group-abc"), message="hello")

    assert "status 400" in str(exc.value)
    assert "recipient=group.raw" in str(exc.value)
    assert "resolver_cache_refreshed=True" in str(exc.value)
    assert "candidate_count=2" in str(exc.value)


@pytest.mark.anyio
async def test_signal_client_includes_4xx_detail() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "recipient required"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        signal = SignalClient(
            base_url="http://signal.local",
            sender_number="+1999",
            http_client=client,
            group_resolver=_resolver(recipients=("group.x",)),
        )
        with pytest.raises(SignalSendError) as exc:
            await signal.send_text(target=Target(recipient="+1222"), message="hello")

    assert "status 400" in str(exc.value)
    assert "recipient=+1222" in str(exc.value)
    assert "recipient required" in str(exc.value)


@pytest.mark.anyio
async def test_signal_client_group_uses_dm_fallback_after_all_400s() -> None:
    captured: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        captured.append(payload)
        recipient = payload["recipients"][0]
        if recipient == "+1222":
            return httpx.Response(201, json={"timestamp": 3})
        return httpx.Response(400, json={"error": "Failed to send message"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        signal = SignalClient(
            base_url="http://signal.local",
            sender_number="+1999",
            http_client=client,
            group_resolver=_resolver(
                recipients=("group.canonical", "group.raw"),
                cache_refreshed=True,
            ),
        )
        await signal.send_text(
            target=Target(group_id="group-abc"),
            message="hello",
            fallback_recipient="+1222",
        )

    assert len(captured) == 3
    assert captured[0]["recipients"] == ["group.canonical"]
    assert captured[1]["recipients"] == ["group.raw"]
    assert captured[2]["recipients"] == ["+1222"]


@pytest.mark.anyio
async def test_signal_client_group_dm_fallback_failure_raises_original_group_error() -> (
    None
):
    captured: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        captured.append(payload)
        return httpx.Response(400, json={"error": "Failed to send message"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        signal = SignalClient(
            base_url="http://signal.local",
            sender_number="+1999",
            http_client=client,
            group_resolver=_resolver(
                recipients=("group.canonical", "group.raw"),
                cache_refreshed=False,
            ),
        )
        with pytest.raises(SignalSendError) as exc:
            await signal.send_text(
                target=Target(group_id="group-abc"),
                message="hello",
                fallback_recipient="+1222",
            )

    assert len(captured) == 3
    assert captured[2]["recipients"] == ["+1222"]
    assert "recipient=group.raw" in str(exc.value)
    assert "candidate_count=2" in str(exc.value)
