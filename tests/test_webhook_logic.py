from __future__ import annotations

import inspect
import json
import logging
from typing import Any, Literal, cast

import httpx
import pytest
from fastapi import BackgroundTasks

from signal_bot_orx.chat_context import ChatTurn
from signal_bot_orx.config import Settings
from signal_bot_orx.dedupe import DedupeCache
from signal_bot_orx.group_resolver import ResolvedGroupRecipients
from signal_bot_orx.search_service import (
    FollowupResolutionDecision,
    SearchRouteDecision,
)
from signal_bot_orx.signal_client import GroupResolverLike, SignalClient
from signal_bot_orx.types import (
    IncomingMessage,
    MentionSpan,
    Target,
    parse_incoming_webhook,
    parse_signal_webhook,
)
from signal_bot_orx.webhook import (
    WebhookHandler,
    normalize_chat_prompt,
    parse_imagine_prompt,
    parse_numeric_selection,
    parse_search_command,
    parse_source_command,
    parse_source_request_text,
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


def test_parse_search_command() -> None:
    assert parse_search_command("/search openrouter") == ("search", "openrouter")
    assert parse_search_command("/wiki Ada Lovelace") == ("wiki", "Ada Lovelace")
    assert parse_search_command("/images cats") == ("images", "cats")
    assert parse_search_command("/videos nick land interview") == (
        "videos",
        "nick land interview",
    )
    assert parse_search_command("hello world") is None


def test_parse_numeric_selection() -> None:
    assert parse_numeric_selection("1") == 1
    assert parse_numeric_selection(" 12 ") == 12
    assert parse_numeric_selection("0") is None
    assert parse_numeric_selection("abc") is None
    assert parse_numeric_selection("/pick 1") is None


def test_parse_source_command() -> None:
    assert parse_source_command("/source") == ""
    assert parse_source_command("/source claim text") == "claim text"
    assert parse_source_command("hello world") is None


def test_parse_source_request_text() -> None:
    assert parse_source_request_text("source for that claim") == "that claim"
    assert parse_source_request_text("where did you get that") == ""
    assert parse_source_request_text("no source request") is None


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


def test_parse_signal_webhook_accepts_whatsapp_shape() -> None:
    payload = {
        "from": "user@c.us",
        "chatId": "user@c.us",
        "text": "hello from whatsapp",
        "timestamp": 1730000000100,
    }

    parsed = parse_incoming_webhook(payload)

    assert parsed is not None
    assert parsed.transport == "whatsapp"
    assert parsed.sender == "user@c.us"
    assert parsed.text == "hello from whatsapp"


def _settings(
    *,
    mode: Literal["group", "dm_fallback"],
    search_context_mode: Literal["no_context", "context"] = "no_context",
    search_mode_search_enabled: bool = True,
    search_mode_news_enabled: bool = True,
    search_mode_wiki_enabled: bool = True,
    search_mode_images_enabled: bool = True,
    search_mode_videos_enabled: bool = True,
    search_debug_logging: bool = False,
    search_persona_enabled: bool = False,
    search_use_history_for_summary: bool = False,
    sender_uuid: str | None = None,
    system_prompt: str | None = None,
    force_plain_text: bool = True,
    image_api_key: str | None = None,
    image_model: str | None = None,
    whatsapp_enabled: bool = False,
    whatsapp_disable_auth: bool = False,
    signal_enabled: bool = True,
    telegram_enabled: bool = False,
    telegram_disable_auth: bool = False,
    telegram_secret: str | None = None,
) -> Settings:
    return Settings(
        signal_api_base_url="http://localhost:8080",
        signal_sender_number="+15550001111",
        signal_sender_uuid=sender_uuid,
        signal_allowed_numbers=frozenset({"+15550002222"}),
        signal_allowed_group_ids=frozenset({"group-1"}),
        openrouter_chat_api_key="or-key-chat",
        openrouter_model="openai/gpt-4o-mini",
        signal_enabled=signal_enabled,
        openrouter_image_api_key=image_api_key,
        openrouter_image_model=image_model,
        bot_search_context_mode=search_context_mode,
        bot_search_mode_search_enabled=search_mode_search_enabled,
        bot_search_mode_news_enabled=search_mode_news_enabled,
        bot_search_mode_wiki_enabled=search_mode_wiki_enabled,
        bot_search_mode_images_enabled=search_mode_images_enabled,
        bot_search_mode_videos_enabled=search_mode_videos_enabled,
        bot_search_debug_logging=search_debug_logging,
        bot_search_persona_enabled=search_persona_enabled,
        bot_search_use_history_for_summary=search_use_history_for_summary,
        bot_group_reply_mode=mode,
        bot_chat_system_prompt=system_prompt or "default system prompt",
        bot_chat_force_plain_text=force_plain_text,
        bot_mention_aliases=("@bot",),
        whatsapp_enabled=whatsapp_enabled,
        whatsapp_bridge_base_url="http://localhost:3001" if whatsapp_enabled else None,
        whatsapp_allowed_numbers=frozenset({"user@c.us"}),
        whatsapp_disable_auth=whatsapp_disable_auth,
        telegram_enabled=telegram_enabled,
        telegram_bot_token="telegram-token" if telegram_enabled else None,
        telegram_webhook_secret=telegram_secret,
        telegram_allowed_user_ids=frozenset({"12345"}),
        telegram_allowed_chat_ids=frozenset({"-10099"}),
        telegram_disable_auth=telegram_disable_auth,
        telegram_bot_username="sigbot",
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


class _FakeWhatsAppClient:
    def __init__(self) -> None:
        self.text_messages: list[str] = []
        self.image_captions: list[str | None] = []

    async def send_text(
        self,
        *,
        target: Target,
        message: str,
        fallback_recipient: str | None = None,
    ) -> None:
        del target, fallback_recipient
        self.text_messages.append(message)

    async def send_image(
        self,
        *,
        target: Target,
        image_bytes: bytes,
        content_type: str,
        caption: str | None = None,
        fallback_recipient: str | None = None,
    ) -> None:
        del target, fallback_recipient
        assert image_bytes
        assert content_type == "image/png"
        self.image_captions.append(caption)


class _FakeTelegramClient:
    def __init__(self) -> None:
        self.text_messages: list[str] = []
        self.image_captions: list[str | None] = []

    async def send_text(
        self,
        *,
        target: Target,
        message: str,
        fallback_recipient: str | None = None,
    ) -> None:
        del target, fallback_recipient
        self.text_messages.append(message)

    async def send_image(
        self,
        *,
        target: Target,
        image_bytes: bytes,
        content_type: str,
        caption: str | None = None,
        fallback_recipient: str | None = None,
    ) -> None:
        del target, fallback_recipient
        assert image_bytes
        assert content_type == "image/png"
        self.image_captions.append(caption)


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
            ChatTurn(role="user", content="older question"),
            ChatTurn(role="assistant", content="older answer"),
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


class _FakeSearchService:
    def __init__(
        self,
        *,
        decision: SearchRouteDecision | None = None,
        followup_resolution: FollowupResolutionDecision | None = None,
        pending_reply_resolution: FollowupResolutionDecision | None = None,
        source_context: list[dict[str, str]] | None = None,
        summary: str = "search-summary",
        source_text: str = "Sources:\n1. Example - https://example.com",
    ) -> None:
        self._decision = decision or SearchRouteDecision(False, "search", "")
        self._followup_resolution = followup_resolution
        self._pending_reply_resolution = pending_reply_resolution
        self._source_context = source_context or []
        self._summary = summary
        self._source_text = source_text
        self._pending_state: dict[str, dict[str, object]] = {}
        self.decide_prompts: list[str] = []
        self.followup_calls: list[dict[str, object]] = []
        self.pending_reply_calls: list[dict[str, object]] = []
        self.search_calls: list[tuple[str, str]] = []
        self.search_user_requests: list[str | None] = []
        self.search_history_contexts: list[list[dict[str, str]] | None] = []
        self.image_calls: list[str] = []
        self.video_list_calls: list[str] = []
        self.video_selection_calls: list[int] = []
        self.pending_video: dict[str, bool] = {}
        self.pending_jmail: dict[str, bool] = {}
        self.source_calls: list[str] = []

    async def decide_auto_search(self, prompt: str) -> SearchRouteDecision:
        self.decide_prompts.append(prompt)
        return self._decision

    async def resolve_followup_prompt(
        self,
        *,
        prompt: str,
        history_context: list[dict[str, str]] | None,
        source_context: list[dict[str, str]] | None,
    ) -> FollowupResolutionDecision:
        self.followup_calls.append(
            {
                "prompt": prompt,
                "history_context": history_context,
                "source_context": source_context,
            }
        )
        if self._followup_resolution is not None:
            return self._followup_resolution
        return FollowupResolutionDecision(
            resolved_prompt=prompt,
            needs_clarification=False,
            clarification_text=None,
            reason="not_followup",
            used_context=False,
            confidence=1.0,
            subject_hint=None,
        )

    async def resolve_pending_followup_reply(
        self,
        *,
        reply_prompt: str,
        pending_state: object,
        history_context: list[dict[str, str]] | None,
        source_context: list[dict[str, str]] | None,
    ) -> FollowupResolutionDecision:
        self.pending_reply_calls.append(
            {
                "reply_prompt": reply_prompt,
                "pending_state": pending_state,
                "history_context": history_context,
                "source_context": source_context,
            }
        )
        if self._pending_reply_resolution is not None:
            return self._pending_reply_resolution
        if self._followup_resolution is not None:
            return self._followup_resolution
        return FollowupResolutionDecision(
            resolved_prompt=reply_prompt,
            needs_clarification=False,
            clarification_text=None,
            reason="pending_reply_deterministic",
            used_context=False,
            confidence=1.0,
            subject_hint=reply_prompt,
        )

    def recent_source_context(
        self,
        *,
        conversation_key: str,
        limit: int = 6,
    ) -> list[dict[str, str]]:
        del conversation_key, limit
        return list(self._source_context)

    def get_pending_followup_state(self, *, conversation_key: str) -> object | None:
        return self._pending_state.get(conversation_key)

    def set_pending_followup_state(
        self,
        *,
        conversation_key: str,
        original_prompt: str,
        template_prompt: str,
        reason: str,
    ) -> None:
        self._pending_state[conversation_key] = {
            "original_prompt": original_prompt,
            "template_prompt": template_prompt,
            "reason": reason,
            "attempts": 0,
        }

    def clear_pending_followup_state(self, *, conversation_key: str) -> None:
        self._pending_state.pop(conversation_key, None)

    def bump_pending_followup_attempt(self, *, conversation_key: str) -> int:
        pending = self._pending_state.get(conversation_key)
        if pending is None:
            return 0
        current_attempts = pending.get("attempts", 0)
        attempts = current_attempts + 1 if isinstance(current_attempts, int) else 1
        pending["attempts"] = attempts
        return attempts

    async def summarize_search(
        self,
        *,
        conversation_key: str,
        mode: str,
        query: str,
        user_request: str | None = None,
        history_context: list[dict[str, str]] | None = None,
    ) -> str:
        del conversation_key
        self.search_calls.append((mode, query))
        self.search_user_requests.append(user_request)
        self.search_history_contexts.append(history_context)
        return self._summary

    async def search_image(
        self,
        *,
        conversation_key: str,
        query: str,
    ) -> tuple[bytes, str]:
        del conversation_key
        self.image_calls.append(query)
        return b"image", "image/png"

    async def video_list_reply(
        self,
        *,
        conversation_key: str,
        query: str,
    ) -> str:
        self.video_list_calls.append(query)
        self.pending_video[conversation_key] = True
        return "Videos:\n1. First video\n2. Second video\nReply with a number to send the thumbnail and URL."

    async def resolve_video_selection(
        self,
        *,
        conversation_key: str,
        selection_number: int,
    ) -> tuple[bytes | None, str | None, str, str]:
        self.video_selection_calls.append(selection_number)
        if not self.pending_video.get(conversation_key):
            raise RuntimeError("missing pending video state")
        return (
            b"thumb",
            "image/png",
            "https://youtube.com/watch?v=abc123",
            "First video",
        )

    def get_pending_video_selection_state(
        self,
        *,
        conversation_key: str,
    ) -> object | None:
        if self.pending_video.get(conversation_key):
            return {"conversation_key": conversation_key}
        return None

    def clear_pending_video_selection_state(self, *, conversation_key: str) -> None:
        self.pending_video.pop(conversation_key, None)

    def get_pending_jmail_selection_state(
        self,
        *,
        conversation_key: str,
    ) -> object | None:
        if self.pending_jmail.get(conversation_key):
            return {"conversation_key": conversation_key}
        return None

    def clear_pending_jmail_selection_state(self, *, conversation_key: str) -> None:
        self.pending_jmail.pop(conversation_key, None)

    def source_reply(self, *, conversation_key: str, claim: str) -> str:
        del conversation_key
        self.source_calls.append(claim)
        return self._source_text


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
async def test_handle_webhook_search_command_queues_summary() -> None:
    payload = {
        "envelope": {
            "sourceNumber": "+15550002222",
            "timestamp": 1730000000001,
            "dataMessage": {
                "message": "/search latest openrouter news",
                "timestamp": 1730000000001,
            },
        }
    }
    fake_signal = _FakeSignalClient()
    fake_search = _FakeSearchService(summary="summary-only")
    handler = WebhookHandler(
        settings=_settings(mode="group"),
        signal_client=cast(Any, fake_signal),
        openrouter_client=cast(Any, _FakeOpenRouterClient()),
        chat_context=cast(Any, _FakeChatContextStore()),
        openrouter_image_client=None,
        dedupe=DedupeCache(ttl_seconds=60),
        search_service=cast(Any, fake_search),
    )

    background_tasks = BackgroundTasks()
    response = await handler.handle_webhook(payload, background_tasks)
    await _run_background_tasks(background_tasks)

    assert response == {"status": "accepted", "reason": "search_queued"}
    assert fake_search.followup_calls == []
    assert fake_search.search_calls == [("search", "latest openrouter news")]
    assert fake_search.search_user_requests == [None]
    assert fake_search.search_history_contexts == [None]
    assert fake_signal.text_messages == ["summary-only"]


@pytest.mark.anyio
async def test_handle_webhook_whatsapp_search_command_queues_summary() -> None:
    payload = {
        "from": "user@c.us",
        "chatId": "user@c.us",
        "text": "/search latest openrouter news",
        "timestamp": 1730000000001,
    }
    fake_signal = _FakeSignalClient()
    fake_whatsapp = _FakeWhatsAppClient()
    fake_search = _FakeSearchService(summary="summary-only")
    handler = WebhookHandler(
        settings=_settings(
            mode="group",
            whatsapp_enabled=True,
            whatsapp_disable_auth=True,
        ),
        signal_client=cast(Any, fake_signal),
        whatsapp_client=cast(Any, fake_whatsapp),
        openrouter_client=cast(Any, _FakeOpenRouterClient()),
        chat_context=cast(Any, _FakeChatContextStore()),
        openrouter_image_client=None,
        dedupe=DedupeCache(ttl_seconds=60),
        search_service=cast(Any, fake_search),
    )

    background_tasks = BackgroundTasks()
    response = await handler.handle_webhook(payload, background_tasks)
    await _run_background_tasks(background_tasks)

    assert response == {"status": "accepted", "reason": "search_queued"}
    assert fake_search.search_calls == [("search", "latest openrouter news")]


@pytest.mark.anyio
async def test_handle_webhook_telegram_dm_search_command_queues_summary() -> None:
    payload = {
        "update_id": 1,
        "message": {
            "message_id": 12,
            "date": 1730000000,
            "text": "/search latest openrouter news",
            "from": {"id": 12345, "is_bot": False},
            "chat": {"id": 12345, "type": "private"},
        },
    }
    fake_signal = _FakeSignalClient()
    fake_telegram = _FakeTelegramClient()
    fake_search = _FakeSearchService(summary="summary-only")
    handler = WebhookHandler(
        settings=_settings(
            mode="group",
            telegram_enabled=True,
            telegram_disable_auth=False,
            telegram_secret="s3cr3t",
        ),
        signal_client=cast(Any, fake_signal),
        telegram_client=cast(Any, fake_telegram),
        openrouter_client=cast(Any, _FakeOpenRouterClient()),
        chat_context=cast(Any, _FakeChatContextStore()),
        openrouter_image_client=None,
        dedupe=DedupeCache(ttl_seconds=60),
        search_service=cast(Any, fake_search),
    )

    background_tasks = BackgroundTasks()
    response = await handler.handle_webhook(
        payload,
        background_tasks,
        transport_hint="telegram",
        telegram_secret="s3cr3t",
    )
    await _run_background_tasks(background_tasks)

    assert response == {"status": "accepted", "reason": "search_queued"}
    assert fake_search.search_calls == [("search", "latest openrouter news")]
    assert fake_telegram.text_messages == ["summary-only"]


@pytest.mark.anyio
async def test_handle_webhook_telegram_group_requires_direction() -> None:
    payload = {
        "update_id": 1,
        "message": {
            "message_id": 12,
            "date": 1730000000,
            "text": "hello there",
            "from": {"id": 12345, "is_bot": False},
            "chat": {"id": -10099, "type": "supergroup"},
        },
    }
    handler = WebhookHandler(
        settings=_settings(
            mode="group",
            telegram_enabled=True,
            telegram_disable_auth=False,
            telegram_secret="s3cr3t",
        ),
        signal_client=cast(Any, _FakeSignalClient()),
        telegram_client=cast(Any, _FakeTelegramClient()),
        openrouter_client=cast(Any, _FakeOpenRouterClient()),
        chat_context=cast(Any, _FakeChatContextStore()),
        openrouter_image_client=None,
        dedupe=DedupeCache(ttl_seconds=60),
    )

    response = await handler.handle_webhook(
        payload,
        BackgroundTasks(),
        transport_hint="telegram",
        telegram_secret="s3cr3t",
    )

    assert response == {"status": "ignored", "reason": "non_mention"}


@pytest.mark.anyio
async def test_handle_webhook_telegram_group_mention_triggers_chat() -> None:
    payload = {
        "update_id": 1,
        "message": {
            "message_id": 12,
            "date": 1730000000,
            "text": "@sigbot summarize this",
            "entities": [{"type": "mention", "offset": 0, "length": 7}],
            "from": {"id": 12345, "is_bot": False},
            "chat": {"id": -10099, "type": "supergroup"},
        },
    }
    fake_telegram = _FakeTelegramClient()
    handler = WebhookHandler(
        settings=_settings(
            mode="group",
            telegram_enabled=True,
            telegram_disable_auth=False,
            telegram_secret="s3cr3t",
        ),
        signal_client=cast(Any, _FakeSignalClient()),
        telegram_client=cast(Any, fake_telegram),
        openrouter_client=cast(Any, _FakeOpenRouterClient()),
        chat_context=cast(Any, _FakeChatContextStore()),
        openrouter_image_client=None,
        dedupe=DedupeCache(ttl_seconds=60),
    )

    background_tasks = BackgroundTasks()
    response = await handler.handle_webhook(
        payload,
        background_tasks,
        transport_hint="telegram",
        telegram_secret="s3cr3t",
    )
    await _run_background_tasks(background_tasks)

    assert response == {"status": "accepted", "reason": "chat_queued"}
    assert fake_telegram.text_messages == ["chat-response"]


@pytest.mark.anyio
async def test_handle_webhook_telegram_secret_mismatch_is_ignored() -> None:
    payload = {
        "update_id": 1,
        "message": {
            "message_id": 12,
            "date": 1730000000,
            "text": "/search test",
            "from": {"id": 12345, "is_bot": False},
            "chat": {"id": 12345, "type": "private"},
        },
    }
    handler = WebhookHandler(
        settings=_settings(
            mode="group",
            telegram_enabled=True,
            telegram_disable_auth=False,
            telegram_secret="s3cr3t",
        ),
        signal_client=cast(Any, _FakeSignalClient()),
        telegram_client=cast(Any, _FakeTelegramClient()),
        openrouter_client=cast(Any, _FakeOpenRouterClient()),
        chat_context=cast(Any, _FakeChatContextStore()),
        openrouter_image_client=None,
        dedupe=DedupeCache(ttl_seconds=60),
    )

    response = await handler.handle_webhook(
        payload,
        BackgroundTasks(),
        transport_hint="telegram",
        telegram_secret="wrong",
    )

    assert response == {"status": "ignored", "reason": "invalid_telegram_secret"}


@pytest.mark.anyio
async def test_handle_webhook_explicit_search_command_clears_pending_followup() -> None:
    payload = {
        "envelope": {
            "sourceNumber": "+15550002222",
            "timestamp": 1730000000001,
            "dataMessage": {
                "message": "/search latest openrouter news",
                "timestamp": 1730000000001,
            },
        }
    }
    fake_signal = _FakeSignalClient()
    fake_search = _FakeSearchService(summary="summary-only")
    fake_search.set_pending_followup_state(
        conversation_key="dm:+15550002222",
        original_prompt="who is he in islam",
        template_prompt="who is {subject} in islam",
        reason="low_confidence",
    )
    handler = WebhookHandler(
        settings=_settings(mode="group"),
        signal_client=cast(Any, fake_signal),
        openrouter_client=cast(Any, _FakeOpenRouterClient()),
        chat_context=cast(Any, _FakeChatContextStore()),
        openrouter_image_client=None,
        dedupe=DedupeCache(ttl_seconds=60),
        search_service=cast(Any, fake_search),
    )

    background_tasks = BackgroundTasks()
    await handler.handle_webhook(payload, background_tasks)
    await _run_background_tasks(background_tasks)

    assert (
        fake_search.get_pending_followup_state(conversation_key="dm:+15550002222")
        is None
    )


@pytest.mark.anyio
async def test_handle_webhook_search_command_logs_route_debug(
    caplog: pytest.LogCaptureFixture,
) -> None:
    payload = {
        "envelope": {
            "sourceNumber": "+15550002222",
            "timestamp": 1730000000001,
            "dataMessage": {
                "message": "/search latest openrouter news",
                "timestamp": 1730000000001,
            },
        }
    }
    fake_signal = _FakeSignalClient()
    fake_search = _FakeSearchService(summary="summary-only")
    handler = WebhookHandler(
        settings=_settings(mode="group", search_debug_logging=True),
        signal_client=cast(Any, fake_signal),
        openrouter_client=cast(Any, _FakeOpenRouterClient()),
        chat_context=cast(Any, _FakeChatContextStore()),
        openrouter_image_client=None,
        dedupe=DedupeCache(ttl_seconds=60),
        search_service=cast(Any, fake_search),
    )
    caplog.set_level(logging.INFO, logger="signal_bot_orx.webhook")

    background_tasks = BackgroundTasks()
    await handler.handle_webhook(payload, background_tasks)
    await _run_background_tasks(background_tasks)

    assert any(
        "search_route_debug" in record.getMessage()
        and "slash_command=/search" in record.getMessage()
        and "final_path=search_summary" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.anyio
async def test_handle_webhook_search_command_mode_disabled() -> None:
    payload = {
        "envelope": {
            "sourceNumber": "+15550002222",
            "timestamp": 1730000000001,
            "dataMessage": {
                "message": "/search latest openrouter news",
                "timestamp": 1730000000001,
            },
        }
    }
    fake_signal = _FakeSignalClient()
    fake_search = _FakeSearchService(summary="summary-only")
    handler = WebhookHandler(
        settings=_settings(mode="group", search_mode_search_enabled=False),
        signal_client=cast(Any, fake_signal),
        openrouter_client=cast(Any, _FakeOpenRouterClient()),
        chat_context=cast(Any, _FakeChatContextStore()),
        openrouter_image_client=None,
        dedupe=DedupeCache(ttl_seconds=60),
        search_service=cast(Any, fake_search),
    )

    background_tasks = BackgroundTasks()
    response = await handler.handle_webhook(payload, background_tasks)
    await _run_background_tasks(background_tasks)

    assert response == {"status": "accepted", "reason": "search_mode_disabled"}
    assert fake_search.search_calls == []
    assert fake_signal.text_messages == ["/search is disabled on this bot."]


@pytest.mark.anyio
async def test_handle_webhook_search_command_passes_history_context_when_enabled() -> (
    None
):
    payload = {
        "envelope": {
            "sourceNumber": "+15550002222",
            "timestamp": 1730000000001,
            "dataMessage": {
                "message": "/search latest openrouter news",
                "timestamp": 1730000000001,
            },
        }
    }
    fake_signal = _FakeSignalClient()
    fake_search = _FakeSearchService(summary="summary-only")
    handler = WebhookHandler(
        settings=_settings(mode="group", search_use_history_for_summary=True),
        signal_client=cast(Any, fake_signal),
        openrouter_client=cast(Any, _FakeOpenRouterClient()),
        chat_context=cast(Any, _FakeChatContextStore()),
        openrouter_image_client=None,
        dedupe=DedupeCache(ttl_seconds=60),
        search_service=cast(Any, fake_search),
    )

    background_tasks = BackgroundTasks()
    response = await handler.handle_webhook(payload, background_tasks)
    await _run_background_tasks(background_tasks)

    assert response == {"status": "accepted", "reason": "search_queued"}
    assert fake_search.search_calls == [("search", "latest openrouter news")]
    assert fake_search.search_user_requests == [None]
    assert fake_search.search_history_contexts[0] is not None
    assert len(fake_search.search_history_contexts[0] or []) == 4


@pytest.mark.anyio
async def test_handle_webhook_images_command_sends_attachment() -> None:
    payload = {
        "envelope": {
            "sourceNumber": "+15550002222",
            "timestamp": 1730000000001,
            "dataMessage": {
                "message": "/images red fox",
                "timestamp": 1730000000001,
            },
        }
    }
    fake_signal = _FakeSignalClient()
    fake_search = _FakeSearchService()
    handler = WebhookHandler(
        settings=_settings(mode="group"),
        signal_client=cast(Any, fake_signal),
        openrouter_client=cast(Any, _FakeOpenRouterClient()),
        chat_context=cast(Any, _FakeChatContextStore()),
        openrouter_image_client=None,
        dedupe=DedupeCache(ttl_seconds=60),
        search_service=cast(Any, fake_search),
    )

    background_tasks = BackgroundTasks()
    response = await handler.handle_webhook(payload, background_tasks)
    await _run_background_tasks(background_tasks)

    assert response == {"status": "accepted", "reason": "search_image_queued"}
    assert fake_search.image_calls == ["red fox"]
    assert fake_signal.image_targets


@pytest.mark.anyio
async def test_handle_webhook_videos_command_sends_numbered_list() -> None:
    payload = {
        "envelope": {
            "sourceNumber": "+15550002222",
            "timestamp": 1730000000001,
            "dataMessage": {
                "message": "/videos nick land interview",
                "timestamp": 1730000000001,
            },
        }
    }
    fake_signal = _FakeSignalClient()
    fake_search = _FakeSearchService()
    handler = WebhookHandler(
        settings=_settings(mode="group"),
        signal_client=cast(Any, fake_signal),
        openrouter_client=cast(Any, _FakeOpenRouterClient()),
        chat_context=cast(Any, _FakeChatContextStore()),
        openrouter_image_client=None,
        dedupe=DedupeCache(ttl_seconds=60),
        search_service=cast(Any, fake_search),
    )

    background_tasks = BackgroundTasks()
    response = await handler.handle_webhook(payload, background_tasks)
    await _run_background_tasks(background_tasks)

    assert response == {"status": "accepted", "reason": "search_videos_queued"}
    assert fake_search.video_list_calls == ["nick land interview"]
    assert fake_signal.text_messages
    assert fake_signal.text_messages[0].startswith("Videos:")


@pytest.mark.anyio
async def test_handle_webhook_numeric_video_selection_sends_image_and_url() -> None:
    first_payload = {
        "envelope": {
            "sourceNumber": "+15550002222",
            "timestamp": 1730000000001,
            "dataMessage": {
                "message": "/videos nick land interview",
                "timestamp": 1730000000001,
            },
        }
    }
    second_payload = {
        "envelope": {
            "sourceNumber": "+15550002222",
            "timestamp": 1730000000002,
            "dataMessage": {
                "message": "1",
                "timestamp": 1730000000002,
            },
        }
    }
    fake_signal = _FakeSignalClient()
    fake_search = _FakeSearchService()
    handler = WebhookHandler(
        settings=_settings(mode="group"),
        signal_client=cast(Any, fake_signal),
        openrouter_client=cast(Any, _FakeOpenRouterClient()),
        chat_context=cast(Any, _FakeChatContextStore()),
        openrouter_image_client=None,
        dedupe=DedupeCache(ttl_seconds=60),
        search_service=cast(Any, fake_search),
    )

    first_tasks = BackgroundTasks()
    await handler.handle_webhook(first_payload, first_tasks)
    await _run_background_tasks(first_tasks)

    second_tasks = BackgroundTasks()
    response = await handler.handle_webhook(second_payload, second_tasks)
    await _run_background_tasks(second_tasks)

    assert response == {
        "status": "accepted",
        "reason": "search_video_selection_queued",
    }
    assert fake_search.video_selection_calls == [1]
    assert len(fake_signal.image_targets) == 1
    assert fake_signal.image_captions[-1] is not None
    assert "https://youtube.com/watch?v=abc123" in (
        fake_signal.image_captions[-1] or ""
    )
    assert not any(
        "https://youtube.com/watch?v=abc123" in msg for msg in fake_signal.text_messages
    )


@pytest.mark.anyio
async def test_handle_webhook_numeric_message_without_pending_video_is_not_hijacked() -> (
    None
):
    payload = {
        "envelope": {
            "sourceNumber": "+15550002222",
            "timestamp": 1730000000001,
            "dataMessage": {
                "message": "1",
                "timestamp": 1730000000001,
            },
        }
    }
    fake_signal = _FakeSignalClient()
    fake_context = _FakeChatContextStore()
    fake_openrouter = _FakeOpenRouterClient(reply="chat-response")
    fake_search = _FakeSearchService()
    handler = WebhookHandler(
        settings=_settings(mode="group"),
        signal_client=cast(Any, fake_signal),
        openrouter_client=cast(Any, fake_openrouter),
        chat_context=cast(Any, fake_context),
        openrouter_image_client=None,
        dedupe=DedupeCache(ttl_seconds=60),
        search_service=cast(Any, fake_search),
    )

    background_tasks = BackgroundTasks()
    response = await handler.handle_webhook(payload, background_tasks)
    await _run_background_tasks(background_tasks)

    assert response == {"status": "accepted", "reason": "chat_queued"}
    assert fake_search.video_selection_calls == []
    assert fake_signal.text_messages == ["chat-response"]


@pytest.mark.anyio
async def test_handle_webhook_source_command_returns_sources() -> None:
    payload = {
        "envelope": {
            "sourceNumber": "+15550002222",
            "timestamp": 1730000000001,
            "dataMessage": {
                "message": "/source openrouter claim",
                "timestamp": 1730000000001,
            },
        }
    }
    fake_signal = _FakeSignalClient()
    fake_search = _FakeSearchService(
        source_text="Sources:\n1. Title - https://example.com"
    )
    handler = WebhookHandler(
        settings=_settings(mode="group"),
        signal_client=cast(Any, fake_signal),
        openrouter_client=cast(Any, _FakeOpenRouterClient()),
        chat_context=cast(Any, _FakeChatContextStore()),
        openrouter_image_client=None,
        dedupe=DedupeCache(ttl_seconds=60),
        search_service=cast(Any, fake_search),
    )

    background_tasks = BackgroundTasks()
    response = await handler.handle_webhook(payload, background_tasks)
    await _run_background_tasks(background_tasks)

    assert response == {"status": "accepted", "reason": "source_queued"}
    assert fake_search.source_calls == ["openrouter claim"]
    assert fake_signal.text_messages == ["Sources:\n1. Title - https://example.com"]


@pytest.mark.anyio
async def test_handle_webhook_auto_search_from_dm() -> None:
    payload = {
        "envelope": {
            "sourceNumber": "+15550002222",
            "timestamp": 1730000000001,
            "dataMessage": {
                "message": "what happened with openrouter this week?",
                "timestamp": 1730000000001,
            },
        }
    }
    fake_signal = _FakeSignalClient()
    fake_context = _FakeChatContextStore()
    fake_search = _FakeSearchService(
        decision=SearchRouteDecision(
            should_search=True,
            mode="news",
            query="openrouter this week",
            reason="current_events",
        ),
        summary="news summary",
    )
    handler = WebhookHandler(
        settings=_settings(mode="group", search_context_mode="context"),
        signal_client=cast(Any, fake_signal),
        openrouter_client=cast(Any, _FakeOpenRouterClient()),
        chat_context=cast(Any, fake_context),
        openrouter_image_client=None,
        dedupe=DedupeCache(ttl_seconds=60),
        search_service=cast(Any, fake_search),
    )

    background_tasks = BackgroundTasks()
    response = await handler.handle_webhook(payload, background_tasks)
    await _run_background_tasks(background_tasks)

    assert response == {"status": "accepted", "reason": "search_queued"}
    assert fake_search.decide_prompts == ["what happened with openrouter this week?"]
    assert fake_search.search_calls == [("news", "openrouter this week")]
    assert fake_search.search_user_requests == [
        "what happened with openrouter this week?"
    ]
    assert fake_search.search_history_contexts == [None]
    assert fake_signal.text_messages == ["news summary"]
    assert fake_context.appended
    assert fake_context.appended[0][1] == "what happened with openrouter this week?"


@pytest.mark.anyio
async def test_handle_webhook_auto_search_resolves_followup_prompt_before_routing() -> (
    None
):
    payload = {
        "envelope": {
            "sourceNumber": "+15550002222",
            "timestamp": 1730000000001,
            "dataMessage": {
                "message": "what's he up to now",
                "timestamp": 1730000000001,
            },
        }
    }
    fake_signal = _FakeSignalClient()
    fake_search = _FakeSearchService(
        decision=SearchRouteDecision(
            should_search=True,
            mode="search",
            query="nick land current projects",
            reason="person_lookup",
        ),
        followup_resolution=FollowupResolutionDecision(
            resolved_prompt="what is nick land up to now",
            needs_clarification=False,
            clarification_text=None,
            reason="entity_match_recent_turns",
            used_context=True,
            confidence=0.92,
            subject_hint="nick land",
        ),
        source_context=[
            {"mode": "search", "title": "Nick Land", "snippet": "British philosopher"}
        ],
        summary="summary",
    )
    handler = WebhookHandler(
        settings=_settings(mode="group", search_context_mode="context"),
        signal_client=cast(Any, fake_signal),
        openrouter_client=cast(Any, _FakeOpenRouterClient()),
        chat_context=cast(Any, _FakeChatContextStore()),
        openrouter_image_client=None,
        dedupe=DedupeCache(ttl_seconds=60),
        search_service=cast(Any, fake_search),
    )

    background_tasks = BackgroundTasks()
    response = await handler.handle_webhook(payload, background_tasks)
    await _run_background_tasks(background_tasks)

    assert response == {"status": "accepted", "reason": "search_queued"}
    assert fake_search.decide_prompts == ["what is nick land up to now"]
    assert fake_search.search_calls == [("search", "nick land current projects")]
    assert fake_search.search_user_requests == ["what's he up to now"]
    assert fake_signal.text_messages == ["summary"]


@pytest.mark.anyio
async def test_handle_webhook_auto_search_clarifies_unresolved_followup() -> None:
    payload = {
        "envelope": {
            "sourceNumber": "+15550002222",
            "timestamp": 1730000000001,
            "dataMessage": {
                "message": "what's he up to now",
                "timestamp": 1730000000001,
            },
        }
    }
    fake_signal = _FakeSignalClient()
    fake_search = _FakeSearchService(
        decision=SearchRouteDecision(
            should_search=True,
            mode="search",
            query="should not be used",
            reason="unused",
        ),
        followup_resolution=FollowupResolutionDecision(
            resolved_prompt="what's he up to now",
            needs_clarification=True,
            clarification_text="Who are you referring to?",
            reason="low_confidence",
            used_context=True,
            confidence=0.4,
            subject_hint=None,
        ),
    )
    handler = WebhookHandler(
        settings=_settings(mode="group", search_context_mode="context"),
        signal_client=cast(Any, fake_signal),
        openrouter_client=cast(Any, _FakeOpenRouterClient()),
        chat_context=cast(Any, _FakeChatContextStore()),
        openrouter_image_client=None,
        dedupe=DedupeCache(ttl_seconds=60),
        search_service=cast(Any, fake_search),
    )

    background_tasks = BackgroundTasks()
    response = await handler.handle_webhook(payload, background_tasks)
    await _run_background_tasks(background_tasks)

    assert response == {
        "status": "accepted",
        "reason": "search_followup_clarification",
    }
    assert fake_search.decide_prompts == []
    assert fake_search.search_calls == []
    assert fake_signal.text_messages == ["Who are you referring to?"]


@pytest.mark.anyio
async def test_handle_webhook_pending_followup_reply_autofills_and_routes() -> None:
    first_payload = {
        "envelope": {
            "sourceNumber": "+15550002222",
            "timestamp": 1730000000001,
            "dataMessage": {
                "message": "who is he in islam",
                "timestamp": 1730000000001,
            },
        }
    }
    second_payload = {
        "envelope": {
            "sourceNumber": "+15550002222",
            "timestamp": 1730000000002,
            "dataMessage": {
                "message": "god",
                "timestamp": 1730000000002,
            },
        }
    }
    fake_signal = _FakeSignalClient()
    fake_search = _FakeSearchService(
        decision=SearchRouteDecision(
            should_search=True,
            mode="search",
            query="god islam",
            reason="person_lookup",
        ),
        followup_resolution=FollowupResolutionDecision(
            resolved_prompt="who is he in islam",
            needs_clarification=True,
            clarification_text="Who are you referring to?",
            reason="low_confidence",
            used_context=True,
            confidence=0.4,
            subject_hint=None,
        ),
        pending_reply_resolution=FollowupResolutionDecision(
            resolved_prompt="who is god in islam",
            needs_clarification=False,
            clarification_text=None,
            reason="pending_reply_deterministic",
            used_context=False,
            confidence=1.0,
            subject_hint="god",
        ),
        summary="answer",
    )
    handler = WebhookHandler(
        settings=_settings(mode="group", search_context_mode="context"),
        signal_client=cast(Any, fake_signal),
        openrouter_client=cast(Any, _FakeOpenRouterClient()),
        chat_context=cast(Any, _FakeChatContextStore()),
        openrouter_image_client=None,
        dedupe=DedupeCache(ttl_seconds=60),
        search_service=cast(Any, fake_search),
    )

    first_tasks = BackgroundTasks()
    first_response = await handler.handle_webhook(first_payload, first_tasks)
    await _run_background_tasks(first_tasks)
    assert first_response == {
        "status": "accepted",
        "reason": "search_followup_clarification",
    }

    second_tasks = BackgroundTasks()
    second_response = await handler.handle_webhook(second_payload, second_tasks)
    await _run_background_tasks(second_tasks)

    assert second_response == {"status": "accepted", "reason": "search_queued"}
    assert fake_search.pending_reply_calls
    assert fake_search.decide_prompts == ["who is god in islam"]
    assert fake_search.search_user_requests[-1] == "who is god in islam"
    assert fake_signal.text_messages == ["Who are you referring to?", "answer"]


@pytest.mark.anyio
async def test_handle_webhook_pending_followup_second_failure_requests_rephrase() -> (
    None
):
    first_payload = {
        "envelope": {
            "sourceNumber": "+15550002222",
            "timestamp": 1730000000001,
            "dataMessage": {
                "message": "who is he in islam",
                "timestamp": 1730000000001,
            },
        }
    }
    second_payload = {
        "envelope": {
            "sourceNumber": "+15550002222",
            "timestamp": 1730000000002,
            "dataMessage": {
                "message": "not sure",
                "timestamp": 1730000000002,
            },
        }
    }
    fake_signal = _FakeSignalClient()
    fake_search = _FakeSearchService(
        followup_resolution=FollowupResolutionDecision(
            resolved_prompt="who is he in islam",
            needs_clarification=True,
            clarification_text="Who are you referring to?",
            reason="low_confidence",
            used_context=True,
            confidence=0.4,
            subject_hint=None,
        ),
        pending_reply_resolution=FollowupResolutionDecision(
            resolved_prompt="who is he in islam",
            needs_clarification=True,
            clarification_text="Who are you referring to?",
            reason="still_ambiguous",
            used_context=True,
            confidence=0.3,
            subject_hint=None,
        ),
    )
    handler = WebhookHandler(
        settings=_settings(mode="group", search_context_mode="context"),
        signal_client=cast(Any, fake_signal),
        openrouter_client=cast(Any, _FakeOpenRouterClient()),
        chat_context=cast(Any, _FakeChatContextStore()),
        openrouter_image_client=None,
        dedupe=DedupeCache(ttl_seconds=60),
        search_service=cast(Any, fake_search),
    )

    first_tasks = BackgroundTasks()
    await handler.handle_webhook(first_payload, first_tasks)
    await _run_background_tasks(first_tasks)

    second_tasks = BackgroundTasks()
    second_response = await handler.handle_webhook(second_payload, second_tasks)
    await _run_background_tasks(second_tasks)

    assert second_response == {
        "status": "accepted",
        "reason": "search_followup_rephrase_requested",
    }
    assert fake_search.decide_prompts == []
    assert "Please restate your full question" in fake_signal.text_messages[-1]


@pytest.mark.anyio
async def test_handle_webhook_auto_search_logs_route_debug(
    caplog: pytest.LogCaptureFixture,
) -> None:
    payload = {
        "envelope": {
            "sourceNumber": "+15550002222",
            "timestamp": 1730000000001,
            "dataMessage": {
                "message": "what happened with openrouter this week?",
                "timestamp": 1730000000001,
            },
        }
    }
    fake_signal = _FakeSignalClient()
    fake_search = _FakeSearchService(
        decision=SearchRouteDecision(
            should_search=True,
            mode="news",
            query="openrouter this week",
            reason="current_events",
        ),
        summary="news summary",
    )
    handler = WebhookHandler(
        settings=_settings(
            mode="group",
            search_context_mode="context",
            search_debug_logging=True,
        ),
        signal_client=cast(Any, fake_signal),
        openrouter_client=cast(Any, _FakeOpenRouterClient()),
        chat_context=cast(Any, _FakeChatContextStore()),
        openrouter_image_client=None,
        dedupe=DedupeCache(ttl_seconds=60),
        search_service=cast(Any, fake_search),
    )
    caplog.set_level(logging.INFO, logger="signal_bot_orx.webhook")

    background_tasks = BackgroundTasks()
    await handler.handle_webhook(payload, background_tasks)
    await _run_background_tasks(background_tasks)

    assert any(
        "search_route_debug" in record.getMessage()
        and "auto_should_search=True" in record.getMessage()
        and "auto_mode=news" in record.getMessage()
        and "final_path=search_summary" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.anyio
async def test_handle_webhook_auto_search_passes_history_context_when_enabled() -> None:
    payload = {
        "envelope": {
            "sourceNumber": "+15550002222",
            "timestamp": 1730000000001,
            "dataMessage": {
                "message": "what happened with openrouter this week?",
                "timestamp": 1730000000001,
            },
        }
    }
    fake_signal = _FakeSignalClient()
    fake_search = _FakeSearchService(
        decision=SearchRouteDecision(
            should_search=True,
            mode="news",
            query="openrouter this week",
            reason="current_events",
        ),
        summary="news summary",
    )
    handler = WebhookHandler(
        settings=_settings(
            mode="group",
            search_context_mode="context",
            search_use_history_for_summary=True,
        ),
        signal_client=cast(Any, fake_signal),
        openrouter_client=cast(Any, _FakeOpenRouterClient()),
        chat_context=cast(Any, _FakeChatContextStore()),
        openrouter_image_client=None,
        dedupe=DedupeCache(ttl_seconds=60),
        search_service=cast(Any, fake_search),
    )

    background_tasks = BackgroundTasks()
    response = await handler.handle_webhook(payload, background_tasks)
    await _run_background_tasks(background_tasks)

    assert response == {"status": "accepted", "reason": "search_queued"}
    assert fake_search.search_calls == [("news", "openrouter this week")]
    assert fake_search.search_history_contexts[0] is not None
    assert len(fake_search.search_history_contexts[0] or []) == 4


@pytest.mark.anyio
async def test_handle_webhook_no_context_mode_skips_auto_search() -> None:
    payload = {
        "envelope": {
            "sourceNumber": "+15550002222",
            "timestamp": 1730000000001,
            "dataMessage": {
                "message": "what happened with openrouter this week?",
                "timestamp": 1730000000001,
            },
        }
    }
    fake_signal = _FakeSignalClient()
    fake_search = _FakeSearchService(
        decision=SearchRouteDecision(
            should_search=True,
            mode="news",
            query="openrouter this week",
            reason="current_events",
        ),
    )
    handler = WebhookHandler(
        settings=_settings(mode="group", search_context_mode="no_context"),
        signal_client=cast(Any, fake_signal),
        openrouter_client=cast(Any, _FakeOpenRouterClient(reply="chat-response")),
        chat_context=cast(Any, _FakeChatContextStore()),
        openrouter_image_client=None,
        dedupe=DedupeCache(ttl_seconds=60),
        search_service=cast(Any, fake_search),
    )

    background_tasks = BackgroundTasks()
    response = await handler.handle_webhook(payload, background_tasks)
    await _run_background_tasks(background_tasks)

    assert response == {"status": "accepted", "reason": "chat_queued"}
    assert fake_search.search_calls == []
    assert fake_signal.text_messages == ["chat-response"]


@pytest.mark.anyio
async def test_handle_webhook_context_mode_skips_disabled_auto_search_mode() -> None:
    payload = {
        "envelope": {
            "sourceNumber": "+15550002222",
            "timestamp": 1730000000001,
            "dataMessage": {
                "message": "what happened with openrouter this week?",
                "timestamp": 1730000000001,
            },
        }
    }
    fake_signal = _FakeSignalClient()
    fake_search = _FakeSearchService(
        decision=SearchRouteDecision(
            should_search=True,
            mode="news",
            query="openrouter this week",
            reason="current_events",
        ),
    )
    handler = WebhookHandler(
        settings=_settings(
            mode="group",
            search_context_mode="context",
            search_mode_news_enabled=False,
        ),
        signal_client=cast(Any, fake_signal),
        openrouter_client=cast(Any, _FakeOpenRouterClient(reply="chat-response")),
        chat_context=cast(Any, _FakeChatContextStore()),
        openrouter_image_client=None,
        dedupe=DedupeCache(ttl_seconds=60),
        search_service=cast(Any, fake_search),
    )

    background_tasks = BackgroundTasks()
    response = await handler.handle_webhook(payload, background_tasks)
    await _run_background_tasks(background_tasks)

    assert response == {"status": "accepted", "reason": "chat_queued"}
    assert fake_search.search_calls == []
    assert fake_signal.text_messages == ["chat-response"]


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
