from __future__ import annotations

import base64
import json

import httpx
import pytest

from signal_box_orx.openrouter_client import (
    ChatReplyError,
    ImageGenerationError,
    OpenRouterClient,
    OpenRouterImageClient,
)


def _chat_client(transport: httpx.MockTransport) -> OpenRouterClient:
    http_client = httpx.AsyncClient(transport=transport)
    return OpenRouterClient(
        api_key="chat-key",
        model="openai/gpt-4o-mini",
        http_client=http_client,
        base_url="https://openrouter.ai/api/v1",
        timeout_seconds=1,
        max_output_tokens=100,
        temperature=0.6,
    )


def _image_client(transport: httpx.MockTransport) -> OpenRouterImageClient:
    http_client = httpx.AsyncClient(transport=transport)
    return OpenRouterImageClient(
        api_key="image-key",
        http_client=http_client,
        base_url="https://openrouter.ai/api/v1",
        timeout_seconds=1,
    )


@pytest.mark.anyio
async def test_openrouter_chat_client_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer chat-key"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "hello from model",
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    client = _chat_client(transport)
    response = await client.generate_reply([{"role": "user", "content": "hi"}])

    assert response == "hello from model"
    await client._http_client.aclose()


@pytest.mark.anyio
async def test_openrouter_chat_client_retries_transient_error() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, json={"error": "temporary"})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "recovered",
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    client = _chat_client(transport)
    response = await client.generate_reply([{"role": "user", "content": "hi"}])

    assert response == "recovered"
    assert attempts == 2
    await client._http_client.aclose()


@pytest.mark.anyio
async def test_openrouter_chat_client_maps_auth_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    transport = httpx.MockTransport(handler)
    client = _chat_client(transport)

    with pytest.raises(ChatReplyError) as exc:
        await client.generate_reply([{"role": "user", "content": "hi"}])

    assert exc.value.user_message == "Chat service authorization failed."
    await client._http_client.aclose()


@pytest.mark.anyio
async def test_openrouter_chat_client_maps_timeout_error() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("timed out")

    transport = httpx.MockTransport(handler)
    client = _chat_client(transport)

    with pytest.raises(ChatReplyError) as exc:
        await client.generate_reply([{"role": "user", "content": "hi"}])

    assert exc.value.user_message == "Chat service timed out. Try again."
    assert attempts == 3
    await client._http_client.aclose()


@pytest.mark.anyio
async def test_openrouter_chat_client_trims_detail_from_error_body() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            content=json.dumps({"message": "bad request"}).encode("utf-8"),
            headers={"content-type": "application/json"},
        )

    transport = httpx.MockTransport(handler)
    client = _chat_client(transport)

    with pytest.raises(ChatReplyError) as exc:
        await client.generate_reply([{"role": "user", "content": "hi"}])

    assert "Chat reply failed" in exc.value.user_message
    assert "bad request" in exc.value.user_message
    await client._http_client.aclose()


@pytest.mark.anyio
async def test_openrouter_image_client_success_data_url() -> None:
    image_bytes = b"image-data"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer image-key"
        assert request.url.path == "/api/v1/chat/completions"
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["model"] == "openai/gpt-image-1"
        assert payload["messages"] == [{"role": "user", "content": "a fox"}]
        assert payload["modalities"] == ["image"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "images": [
                                {
                                    "image_url": {
                                        "url": (
                                            "data:image/png;base64,"
                                            f"{base64.b64encode(image_bytes).decode('ascii')}"
                                        )
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    client = _image_client(transport)
    images = await client.generate_images(prompt="a fox", model="openai/gpt-image-1")

    assert images == [(image_bytes, "image/png")]
    await client._http_client.aclose()


@pytest.mark.anyio
async def test_openrouter_image_client_success_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/chat/completions":
            assert request.headers["Authorization"] == "Bearer image-key"
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "images": [
                                    {
                                        "image_url": {
                                            "url": "https://image.local/generated.png"
                                        }
                                    }
                                ]
                            }
                        }
                    ]
                },
            )
        assert str(request.url) == "https://image.local/generated.png"
        return httpx.Response(
            200,
            content=b"png-bytes",
            headers={"content-type": "image/png"},
        )

    transport = httpx.MockTransport(handler)
    client = _image_client(transport)
    images = await client.generate_images(prompt="a fox", model="openai/gpt-image-1")

    assert images == [(b"png-bytes", "image/png")]
    await client._http_client.aclose()


@pytest.mark.anyio
async def test_openrouter_image_client_returns_all_valid_images() -> None:
    first_image = b"image-1"
    second_image = b"image-2"

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "images": [
                                {
                                    "image_url": {
                                        "url": (
                                            "data:image/png;base64,"
                                            f"{base64.b64encode(first_image).decode('ascii')}"
                                        )
                                    }
                                },
                                {"image_url": {"url": "not-a-valid-url"}},
                                {
                                    "image_url": {
                                        "url": (
                                            "data:image/jpeg;base64,"
                                            f"{base64.b64encode(second_image).decode('ascii')}"
                                        )
                                    }
                                },
                            ]
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    client = _image_client(transport)
    images = await client.generate_images(prompt="a fox", model="openai/gpt-image-1")

    assert images == [
        (first_image, "image/png"),
        (second_image, "image/jpeg"),
    ]
    await client._http_client.aclose()


@pytest.mark.anyio
async def test_openrouter_image_client_errors_on_missing_images() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "nope"}}]})

    transport = httpx.MockTransport(handler)
    client = _image_client(transport)

    with pytest.raises(ImageGenerationError) as exc:
        await client.generate_images(prompt="a fox", model="openai/gpt-image-1")

    assert exc.value.user_message == "Image service returned an empty image payload."
    await client._http_client.aclose()


@pytest.mark.anyio
async def test_openrouter_image_client_retries_transient_error() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, json={"error": "temporary"})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "images": [
                                {
                                    "image_url": {
                                        "url": (
                                            "data:image/png;base64,"
                                            f"{base64.b64encode(b'x').decode('ascii')}"
                                        )
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    client = _image_client(transport)
    images = await client.generate_images(prompt="a fox", model="openai/gpt-image-1")

    assert images == [(b"x", "image/png")]
    assert attempts == 2
    await client._http_client.aclose()


@pytest.mark.anyio
async def test_openrouter_image_client_maps_auth_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    transport = httpx.MockTransport(handler)
    client = _image_client(transport)

    with pytest.raises(ImageGenerationError) as exc:
        await client.generate_images(prompt="a fox", model="openai/gpt-image-1")

    assert exc.value.user_message == "Image service authorization failed."
    await client._http_client.aclose()


@pytest.mark.anyio
async def test_openrouter_image_client_maps_timeout_error() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("timed out")

    transport = httpx.MockTransport(handler)
    client = _image_client(transport)

    with pytest.raises(ImageGenerationError) as exc:
        await client.generate_images(prompt="a fox", model="openai/gpt-image-1")

    assert exc.value.user_message == "Image generation timed out. Try again."
    assert attempts == 3
    await client._http_client.aclose()
