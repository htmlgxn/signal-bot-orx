from __future__ import annotations

import httpx
import pytest

from signal_box_orx.group_resolver import GroupResolver


@pytest.mark.anyio
async def test_group_resolver_maps_internal_id_to_canonical_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.startswith("/v1/groups/")
        return httpx.Response(
            200,
            json=[
                {
                    "id": "group.YWJjK2RlZi9naGk9",
                    "internal_id": "abc+def/ghi=",
                }
            ],
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        resolver = GroupResolver(
            base_url="http://signal.local",
            sender_number="+1999",
            http_client=client,
        )
        resolved = await resolver.resolve("abc+def/ghi=")

    assert resolved.cache_refreshed is True
    assert resolved.recipients[0] == "group.YWJjK2RlZi9naGk9"
    assert "group.abc+def/ghi=" in resolved.recipients
    assert "abc+def/ghi=" in resolved.recipients


@pytest.mark.anyio
async def test_group_resolver_accepts_alternate_key_styles() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/v1/groups/"):
            return httpx.Response(404)
        return httpx.Response(
            200,
            json={
                "groups": [
                    {
                        "groupIdHex": "group.YWJjK3h5ei8xMjM9",
                        "internalId": "abc+xyz/123=",
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        resolver = GroupResolver(
            base_url="http://signal.local",
            sender_number="+1999",
            http_client=client,
        )
        resolved = await resolver.resolve("abc+xyz/123=")

    assert resolved.recipients[0] == "group.YWJjK3h5ei8xMjM9"


@pytest.mark.anyio
async def test_group_resolver_returns_deduped_ordered_candidates() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "id": "group.YWJjK2RlZi9naGk9",
                    "internal_id": "abc+def/ghi=",
                }
            ],
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        resolver = GroupResolver(
            base_url="http://signal.local",
            sender_number="+1999",
            http_client=client,
        )
        resolved = await resolver.resolve("group.YWJjK2RlZi9naGk9")

    assert resolved.recipients[0] == "group.YWJjK2RlZi9naGk9"
    assert resolved.recipients.count("group.YWJjK2RlZi9naGk9") == 1


@pytest.mark.anyio
async def test_group_resolver_miss_does_not_refresh_again_while_ttl_is_fresh() -> None:
    request_count = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(503)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        resolver = GroupResolver(
            base_url="http://signal.local",
            sender_number="+1999",
            http_client=client,
            refresh_ttl_seconds=60,
        )
        first = await resolver.resolve("unknown-group")
        second = await resolver.resolve("unknown-group")

    assert request_count == 2
    assert first.cache_refreshed is False
    assert second.cache_refreshed is False
    assert first.recipients == second.recipients


@pytest.mark.anyio
async def test_group_resolver_miss_refreshes_again_when_ttl_is_expired() -> None:
    request_count = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(503)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        resolver = GroupResolver(
            base_url="http://signal.local",
            sender_number="+1999",
            http_client=client,
            refresh_ttl_seconds=0,
        )
        await resolver.resolve("unknown-group")
        await resolver.resolve("unknown-group")

    assert request_count == 4
