from __future__ import annotations

import inspect
import json
from typing import Any, Literal, cast

import httpx
import pytest
from fastapi import BackgroundTasks

from signal_bot_orx.chat_context import ChatTurn
from signal_bot_orx.config import Settings
from signal_bot_orx.dedupe import DedupeCache
from signal_bot_orx.group_resolver import ResolvedGroupRecipients
from signal_bot_orx.signal_client import GroupResolverLike, SignalClient
from signal_bot_orx.types import (
    IncomingMessage,
    MentionSpan,
    Target,
    parse_signal_webhook,
)
from signal_bot_orx.webhook import (
    WebhookHandler,
    normalize_chat_prompt,
    parse_imagine_prompt,
    resolve_reply_target,
    should_handle_chat_mention,
)


def test_parse_imagine_prompt_valid() -> None:
    assert parse_imagine_prompt("/imagine cat astronaut") == "cat astronaut"


def test_parse_imagine_prompt_empty() -> None:
    assert parse_imagine_prompt("/imagine") == ""
    assert parse_imagine_prompt("/imagine    ") == ""


def test_parse_imagine_prompt_non_command() -> None:
    assert parse_imagine_prompt("hello world") is None


def test_parse_signal_webhook_common_shape() -> None:
    payload = {
        "envelope": {
            "sourceNumber": "+15551234567",
            "timestamp": 1730000000000,
            "dataMessage": {
                "message": "/imagine fox",
                "timestamp": 1730000000001,
            },
        }
    }

    parsed = parse_signal_webhook(payload)

    assert parsed is not None
    assert parsed.sender == "+15551234567"
    assert parsed.text == "/imagine fox"
    assert parsed.timestamp == 1730000000001
    assert parsed.target.recipient == "+15551234567"


def test_parse_signal_webhook_mentions() -> None:
    payload = {
        "envelope": {
            "sourceNumber": "+15557654321",
            "timestamp": 1730000000100,
            "dataMessage": {
                "message": "@bot hello",
                "timestamp": 1730000000200,
                "mentions": [
                    {
                        "start": 0,
                        "length": 4,
                        "recipientNumber": "+15550001111",
                    }
                ],
            },
        }
    }

    parsed = parse_signal_webhook(payload)

    assert parsed is not None
    assert parsed.mentions
    assert parsed.mentions[0].number == "+15550001111"


def test_parse_signal_webhook_json_rpc_missing_message() -> None:
    payload = {
        "jsonrpc": "2.0",
        "method": "receive",
        "params": {
            "envelope": {
                "sourceNumber": "+15557654321",
                "timestamp": 1730000000100,
                "dataMessage": {},
            }
        },
    }

    assert parse_signal_webhook(payload) is None


def _settings(
    *,
    mode: Literal["group", "dm_fallback"],
    sender_uuid: str | None = None,
    system_prompt: str | None = None,
    force_plain_text: bool = True,
    image_api_key: str | None = None,
    image_model: str | None = None,
) -> Settings:
    return Settings(
        signal_api_base_url="http://localhost:8080",
        signal_sender_number="+15550001111",
        signal_sender_uuid=sender_uuid,
        signal_allowed_numbers=frozenset({"+15550002222"}),
        signal_allowed_group_ids=frozenset({"group-1"}),
        openrouter_chat_api_key="or-key-chat",
        openrouter_model="openai/gpt-4o-mini",
        openrouter_image_api_key=image_api_key,
        openrouter_image_model=image_model,
        bot_group_reply_mode=mode,
        bot_chat_system_prompt=system_prompt or "default system prompt",
        bot_chat_force_plain_text=force_plain_text,
        bot_mention_aliases=("@bot",),
    )


def test_resolve_reply_target_group_dm_fallback_mode() -> None:
    message = IncomingMessage(
        sender="+15550002222",
        text="@bot hi",
        timestamp=1,
        target=Target(recipient="+15550002222", group_id="group-1"),
    )

    target = resolve_reply_target(message, _settings(mode="dm_fallback"))

    assert target == Target(recipient="+15550002222", group_id=None)


def test_resolve_reply_target_group_group_mode() -> None:
    message = IncomingMessage(
        sender="+15550002222",
        text="@bot hi",
        timestamp=1,
        target=Target(recipient="+15550002222", group_id="group-1"),
    )

    target = resolve_reply_target(message, _settings(mode="group"))

    assert target == message.target


def test_resolve_reply_target_dm_message_unchanged() -> None:
    message = IncomingMessage(
        sender="+15550002222",
        text="@bot hi",
        timestamp=1,
        target=Target(recipient="+15550002222", group_id=None),
    )

    target = resolve_reply_target(message, _settings(mode="dm_fallback"))

    assert target == message.target


def test_should_handle_chat_mention_true_for_dm() -> None:
    message = IncomingMessage(
        sender="+15550002222",
        text="@bot hi",
        timestamp=1,
        target=Target(recipient="+15550002222", group_id=None),
    )

    assert should_handle_chat_mention(message, _settings(mode="group")) is True


def test_should_handle_chat_mention_true_for_alias_fallback() -> None:
    message = IncomingMessage(
        sender="+15550002222",
        text="@bot summarize that",
        timestamp=1,
        target=Target(recipient="+15550002222", group_id="group-1"),
    )

    assert should_handle_chat_mention(message, _settings(mode="group")) is True


def test_should_handle_chat_mention_true_for_metadata_uuid_match() -> None:
    message = IncomingMessage(
        sender="+15550002222",
        text="ping",
        timestamp=1,
        target=Target(recipient="+15550002222", group_id="group-1"),
        mentions=(MentionSpan(start=0, length=4, uuid="bot-uuid"),),
    )

    assert (
        should_handle_chat_mention(
            message,
            _settings(mode="group", sender_uuid="bot-uuid"),
        )
        is True
    )


def test_normalize_chat_prompt_removes_alias() -> None:
    message = IncomingMessage(
        sender="+15550002222",
        text="@bot, summarize this please",
        timestamp=1,
        target=Target(recipient="+15550002222", group_id="group-1"),
    )

    prompt = normalize_chat_prompt(message, _settings(mode="group"))

    assert prompt == "summarize this please"


class _FakeSignalClient:
    def __init__(self) -> None:
        self.text_targets: list[Target] = []
        self.text_messages: list[str] = []
        self.text_fallback_recipients: list[str | None] = []
        self.image_targets: list[Target] = []
        self.image_captions: list[str | None] = []

    async def send_text(
        self,
        *,
        target: Target,
        message: str,
        fallback_recipient: str | None = None,
    ) -> None:
        self.text_targets.append(target)
        self.text_messages.append(message)
        self.text_fallback_recipients.append(fallback_recipient)

    async def send_image(
        self,
        *,
        target: Target,
        image_bytes: bytes,
        content_type: str,
        caption: str | None = None,
    ) -> None:
        self.image_targets.append(target)
        self.image_captions.append(caption)
        assert image_bytes
        assert content_type == "image/png"


class _FakeOpenRouterImageClient:
    async def generate_images(
        self, *, prompt: str, model: str
    ) -> list[tuple[bytes, str]]:
        assert prompt
        assert model
        return [
            (b"image-1", "image/png"),
            (b"image-2", "image/png"),
        ]


class _FakeOpenRouterClient:
    def __init__(self, *, reply: str = "chat-response") -> None:
        self._reply = reply
        self.seen_messages: list[list[dict[str, str]]] = []

    async def generate_reply(self, messages: list[dict[str, str]]) -> str:
        assert messages
        self.seen_messages.append(messages)
        return self._reply


class _FakeChatContextStore:
    def __init__(self) -> None:
        self.appended: list[tuple[str, str, str]] = []

    def get_history(self, _: str) -> tuple[ChatTurn, ...]:
        return (
            ChatTurn(role="user", content="previous question"),
            ChatTurn(role="assistant", content="previous answer"),
        )

    def append_turn(
        self,
        conversation_key: str,
        *,
        user_text: str,
        assistant_text: str,
    ) -> None:
        self.appended.append((conversation_key, user_text, assistant_text))


class _StaticGroupResolver:
    def __init__(self, recipients: tuple[str, ...], cache_refreshed: bool) -> None:
        self._resolved = ResolvedGroupRecipients(
            recipients=recipients,
            cache_refreshed=cache_refreshed,
        )

    async def resolve(self, _: str) -> ResolvedGroupRecipients:
        return self._resolved


async def _run_background_tasks(background_tasks: BackgroundTasks) -> None:
    for task in background_tasks.tasks:
        result = task.func(*task.args, **task.kwargs)
        if inspect.isawaitable(result):
            await result


@pytest.mark.anyio
async def test_handle_webhook_ignores_non_mention_group_message() -> None:
    payload = {
        "envelope": {
            "sourceNumber": "+15550002222",
            "timestamp": 1730000000001,
            "dataMessage": {
                "message": "hello everyone",
                "timestamp": 1730000000001,
                "groupInfo": {"groupId": "group-1"},
            },
        }
    }

    handler = WebhookHandler(
        settings=_settings(mode="group"),
        signal_client=cast(Any, _FakeSignalClient()),
        openrouter_client=cast(Any, _FakeOpenRouterClient()),
        chat_context=cast(Any, _FakeChatContextStore()),
        openrouter_image_client=None,
        dedupe=DedupeCache(ttl_seconds=60),
    )

    response = await handler.handle_webhook(payload, BackgroundTasks())

    assert response == {"status": "ignored", "reason": "non_mention"}


@pytest.mark.anyio
async def test_handle_webhook_alias_mention_triggers_chat_reply() -> None:
    payload = {
        "envelope": {
            "sourceNumber": "+15550002222",
            "timestamp": 1730000000001,
            "dataMessage": {
                "message": "@bot what is the summary?",
                "timestamp": 1730000000001,
                "groupInfo": {"groupId": "group-1"},
            },
        }
    }

    fake_signal = _FakeSignalClient()
    fake_context = _FakeChatContextStore()
    fake_openrouter = _FakeOpenRouterClient()
    handler = WebhookHandler(
        settings=_settings(mode="group", system_prompt="custom system prompt"),
        signal_client=cast(Any, fake_signal),
        openrouter_client=cast(Any, fake_openrouter),
        chat_context=cast(Any, fake_context),
        openrouter_image_client=None,
        dedupe=DedupeCache(ttl_seconds=60),
    )

    background_tasks = BackgroundTasks()
    response = await handler.handle_webhook(payload, background_tasks)
    await _run_background_tasks(background_tasks)

    assert response == {"status": "accepted", "reason": "chat_queued"}
    assert fake_signal.text_messages == ["chat-response"]
    assert fake_signal.text_fallback_recipients == ["+15550002222"]
    assert fake_openrouter.seen_messages
    assert fake_openrouter.seen_messages[0][0]["content"] == "custom system prompt"
    assert fake_context.appended


@pytest.mark.anyio
async def test_handle_webhook_dm_without_mention_triggers_chat_reply() -> None:
    payload = {
        "envelope": {
            "sourceNumber": "+15550002222",
            "timestamp": 1730000000001,
            "dataMessage": {
                "message": "what is the summary?",
                "timestamp": 1730000000001,
            },
        }
    }

    fake_signal = _FakeSignalClient()
    fake_context = _FakeChatContextStore()
    fake_openrouter = _FakeOpenRouterClient()
    handler = WebhookHandler(
        settings=_settings(mode="group", system_prompt="custom system prompt"),
        signal_client=cast(Any, fake_signal),
        openrouter_client=cast(Any, fake_openrouter),
        chat_context=cast(Any, fake_context),
        openrouter_image_client=None,
        dedupe=DedupeCache(ttl_seconds=60),
    )

    background_tasks = BackgroundTasks()
    response = await handler.handle_webhook(payload, background_tasks)
    await _run_background_tasks(background_tasks)

    assert response == {"status": "accepted", "reason": "chat_queued"}
    assert fake_signal.text_messages == ["chat-response"]
    assert fake_signal.text_fallback_recipients == [None]
    assert fake_openrouter.seen_messages
    assert fake_openrouter.seen_messages[0][0]["content"] == "custom system prompt"
    assert fake_context.appended


@pytest.mark.anyio
async def test_handle_webhook_empty_dm_prompt_sends_usage() -> None:
    payload = {
        "envelope": {
            "sourceNumber": "+15550002222",
            "timestamp": 1730000000001,
            "dataMessage": {
                "message": "@bot",
                "timestamp": 1730000000001,
            },
        }
    }

    fake_signal = _FakeSignalClient()
    handler = WebhookHandler(
        settings=_settings(mode="group"),
        signal_client=cast(Any, fake_signal),
        openrouter_client=cast(Any, _FakeOpenRouterClient()),
        chat_context=cast(Any, _FakeChatContextStore()),
        openrouter_image_client=None,
        dedupe=DedupeCache(ttl_seconds=60),
    )

    background_tasks = BackgroundTasks()
    response = await handler.handle_webhook(payload, background_tasks)
    await _run_background_tasks(background_tasks)

    assert response == {"status": "accepted", "reason": "chat_usage_sent"}
    assert fake_signal.text_messages == [
        "Send a prompt, for example: summarize today's discussion."
    ]


@pytest.mark.anyio
async def test_handle_webhook_metadata_mention_triggers_chat_reply() -> None:
    payload = {
        "envelope": {
            "sourceNumber": "+15550002222",
            "timestamp": 1730000000001,
            "dataMessage": {
                "message": "@someone can you help?",
                "mentions": [
                    {
                        "start": 0,
                        "length": 8,
                        "recipientNumber": "+15550001111",
                    }
                ],
                "timestamp": 1730000000001,
                "groupInfo": {"groupId": "group-1"},
            },
        }
    }

    fake_signal = _FakeSignalClient()
    handler = WebhookHandler(
        settings=_settings(mode="group"),
        signal_client=cast(Any, fake_signal),
        openrouter_client=cast(Any, _FakeOpenRouterClient()),
        chat_context=cast(Any, _FakeChatContextStore()),
        openrouter_image_client=None,
        dedupe=DedupeCache(ttl_seconds=60),
    )

    background_tasks = BackgroundTasks()
    response = await handler.handle_webhook(payload, background_tasks)
    await _run_background_tasks(background_tasks)

    assert response == {"status": "accepted", "reason": "chat_queued"}
    assert fake_signal.text_messages == ["chat-response"]


@pytest.mark.anyio
async def test_handle_chat_mention_group_400_uses_dm_fallback() -> None:
    captured: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        captured.append(payload)
        recipient = payload["recipients"][0]
        if recipient == "+15550002222":
            return httpx.Response(201, json={"timestamp": 3})
        return httpx.Response(400, json={"error": "Failed to send message"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        signal_client = SignalClient(
            base_url="http://signal.local",
            sender_number="+15550001111",
            http_client=http_client,
            group_resolver=cast(
                GroupResolverLike,
                _StaticGroupResolver(
                    recipients=("group.invalid", "raw"),
                    cache_refreshed=True,
                ),
            ),
        )
        handler_obj = WebhookHandler(
            settings=_settings(mode="group"),
            signal_client=signal_client,
            openrouter_client=cast(Any, _FakeOpenRouterClient()),
            chat_context=cast(Any, _FakeChatContextStore()),
            openrouter_image_client=None,
            dedupe=DedupeCache(ttl_seconds=60),
        )
        message = IncomingMessage(
            sender="+15550002222",
            text="@bot summarize",
            timestamp=1,
            target=Target(recipient="+15550002222", group_id="group-1"),
        )
        await handler_obj.handle_chat_mention(message, "summarize")

    assert [payload["recipients"] for payload in captured] == [
        ["group.invalid"],
        ["raw"],
        ["+15550002222"],
    ]


@pytest.mark.anyio
async def test_handle_chat_mention_enforces_plain_text_reply() -> None:
    markdown_reply = (
        "# Summary\n- **hello** from `sigbot`\n> [ref](https://example.com)"
    )
    fake_signal = _FakeSignalClient()
    fake_context = _FakeChatContextStore()
    handler = WebhookHandler(
        settings=_settings(mode="group"),
        signal_client=cast(Any, fake_signal),
        openrouter_client=cast(Any, _FakeOpenRouterClient(reply=markdown_reply)),
        chat_context=cast(Any, fake_context),
        openrouter_image_client=None,
        dedupe=DedupeCache(ttl_seconds=60),
    )
    message = IncomingMessage(
        sender="+15550002222",
        text="@bot summarize",
        timestamp=1,
        target=Target(recipient="+15550002222", group_id="group-1"),
    )

    await handler.handle_chat_mention(message, "summarize")

    assert fake_signal.text_messages == [
        "Summary\nhello from sigbot\nref (https://example.com)"
    ]
    assert fake_context.appended[0][2] == fake_signal.text_messages[0]


@pytest.mark.anyio
async def test_handle_webhook_empty_mention_sends_usage() -> None:
    payload = {
        "envelope": {
            "sourceNumber": "+15550002222",
            "timestamp": 1730000000001,
            "dataMessage": {
                "message": "@bot",
                "timestamp": 1730000000001,
                "groupInfo": {"groupId": "group-1"},
            },
        }
    }

    fake_signal = _FakeSignalClient()
    handler = WebhookHandler(
        settings=_settings(mode="group"),
        signal_client=cast(Any, fake_signal),
        openrouter_client=cast(Any, _FakeOpenRouterClient()),
        chat_context=cast(Any, _FakeChatContextStore()),
        openrouter_image_client=None,
        dedupe=DedupeCache(ttl_seconds=60),
    )

    background_tasks = BackgroundTasks()
    response = await handler.handle_webhook(payload, background_tasks)
    await _run_background_tasks(background_tasks)

    assert response == {"status": "accepted", "reason": "chat_usage_sent"}
    assert fake_signal.text_messages
    assert "Tag me with a prompt" in fake_signal.text_messages[0]


@pytest.mark.anyio
async def test_handle_webhook_imagine_without_image_config_reports_unavailable() -> (
    None
):
    payload = {
        "envelope": {
            "sourceNumber": "+15550002222",
            "timestamp": 1730000000001,
            "dataMessage": {
                "message": "/imagine test prompt",
                "timestamp": 1730000000001,
                "groupInfo": {"groupId": "group-1"},
            },
        }
    }

    fake_signal = _FakeSignalClient()
    handler = WebhookHandler(
        settings=_settings(mode="group"),
        signal_client=cast(Any, fake_signal),
        openrouter_client=cast(Any, _FakeOpenRouterClient()),
        chat_context=cast(Any, _FakeChatContextStore()),
        openrouter_image_client=None,
        dedupe=DedupeCache(ttl_seconds=60),
    )

    background_tasks = BackgroundTasks()
    response = await handler.handle_webhook(payload, background_tasks)
    await _run_background_tasks(background_tasks)

    assert response == {"status": "accepted", "reason": "image_unavailable"}
    assert fake_signal.text_messages == ["Image mode is not configured on this bot."]


@pytest.mark.anyio
async def test_process_imagine_reuses_single_resolved_reply_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolve_calls = 0

    def _resolve_once(message: IncomingMessage, settings: Settings) -> Target:
        nonlocal resolve_calls
        resolve_calls += 1
        return resolve_reply_target(message, settings)

    monkeypatch.setattr("signal_bot_orx.webhook.resolve_reply_target", _resolve_once)

    message = IncomingMessage(
        sender="+15550002222",
        text="/imagine fox",
        timestamp=1,
        target=Target(recipient="+15550002222", group_id="group-1"),
    )
    fake_signal = _FakeSignalClient()
    handler = WebhookHandler(
        settings=_settings(
            mode="dm_fallback",
            image_api_key="or-key-image",
            image_model="openai/gpt-image-1",
        ),
        signal_client=cast(Any, fake_signal),
        openrouter_client=cast(Any, _FakeOpenRouterClient()),
        chat_context=cast(Any, _FakeChatContextStore()),
        openrouter_image_client=cast(Any, _FakeOpenRouterImageClient()),
        dedupe=DedupeCache(ttl_seconds=60),
    )

    await handler._process_imagine(message, "fox")

    assert resolve_calls == 1
    expected_target = Target(recipient=message.sender, group_id=None)
    assert fake_signal.text_targets == [expected_target]
    assert fake_signal.image_targets == [expected_target, expected_target]
    assert fake_signal.image_captions == ["/imagine fox", None]
