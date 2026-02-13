from __future__ import annotations

import logging
import re

from fastapi import APIRouter, BackgroundTasks

from signal_bot_orx.chat_context import ChatContextStore
from signal_bot_orx.chat_prompt import build_chat_messages, coerce_plain_text_reply
from signal_bot_orx.config import Settings
from signal_bot_orx.dedupe import DedupeCache
from signal_bot_orx.openrouter_client import (
    ChatReplyError,
    ImageGenerationError,
    OpenRouterClient,
    OpenRouterImageClient,
)
from signal_bot_orx.signal_client import SignalClient, SignalSendError
from signal_bot_orx.types import (
    IncomingMessage,
    Target,
    dedupe_key,
    metadata_mentions_bot,
    parse_signal_webhook,
    strip_mention_spans,
)

logger = logging.getLogger(__name__)

COMMAND_PREFIX = "/imagine"
CHAT_MAX_REPLY_CHARS = 2000


class WebhookHandler:
    def __init__(
        self,
        *,
        settings: Settings,
        signal_client: SignalClient,
        openrouter_client: OpenRouterClient,
        openrouter_image_client: OpenRouterImageClient | None,
        chat_context: ChatContextStore,
        dedupe: DedupeCache,
    ) -> None:
        self._settings = settings
        self._signal_client = signal_client
        self._openrouter_client = openrouter_client
        self._openrouter_image_client = openrouter_image_client
        self._chat_context = chat_context
        self._dedupe = dedupe

    async def handle_webhook(
        self, payload: dict[str, object], background_tasks: BackgroundTasks
    ) -> dict[str, str]:
        parsed = parse_signal_webhook(payload)
        if parsed is None:
            logger.debug(
                "unsupported_event method_present=%s top_level_key_count=%d",
                "method" in payload,
                len(payload),
            )
            return {"status": "ignored", "reason": "unsupported_event"}

        if not is_authorized_message(parsed, self._settings):
            logger.info(
                "ignoring_unauthorized_sender sender=%s group_id=%s",
                parsed.sender,
                parsed.target.group_id,
            )
            return {"status": "ignored", "reason": "unauthorized"}

        key = dedupe_key(parsed)
        if not self._dedupe.mark_once(key):
            return {"status": "ignored", "reason": "duplicate"}

        imagine_prompt = parse_imagine_prompt(parsed.text)
        if imagine_prompt is not None:
            return self.handle_imagine_command(parsed, imagine_prompt, background_tasks)

        if not should_handle_chat_mention(parsed, self._settings):
            return {"status": "ignored", "reason": "non_mention"}

        chat_prompt = normalize_chat_prompt(parsed, self._settings)
        if not chat_prompt:
            reply_target = resolve_reply_target(parsed, self._settings)
            background_tasks.add_task(
                self._safe_send_text,
                parsed,
                "Tag me with a prompt, for example: @bot summarize today's discussion.",
                reply_target,
            )
            return {"status": "accepted", "reason": "chat_usage_sent"}

        if len(chat_prompt) > self._settings.bot_max_prompt_chars:
            reply_target = resolve_reply_target(parsed, self._settings)
            background_tasks.add_task(
                self._safe_send_text,
                parsed,
                (
                    "Prompt too long. Maximum is "
                    f"{self._settings.bot_max_prompt_chars} characters."
                ),
                reply_target,
            )
            return {"status": "accepted", "reason": "chat_prompt_too_long"}

        background_tasks.add_task(self.handle_chat_mention, parsed, chat_prompt)
        return {"status": "accepted", "reason": "chat_queued"}

    def handle_imagine_command(
        self,
        message: IncomingMessage,
        prompt: str,
        background_tasks: BackgroundTasks,
    ) -> dict[str, str]:
        if not prompt:
            reply_target = resolve_reply_target(message, self._settings)
            background_tasks.add_task(
                self._safe_send_text,
                message,
                "Usage: /imagine <prompt>",
                reply_target,
            )
            return {"status": "accepted", "reason": "usage_sent"}

        if len(prompt) > self._settings.bot_max_prompt_chars:
            reply_target = resolve_reply_target(message, self._settings)
            background_tasks.add_task(
                self._safe_send_text,
                message,
                (
                    "Prompt too long. Maximum is "
                    f"{self._settings.bot_max_prompt_chars} characters."
                ),
                reply_target,
            )
            return {"status": "accepted", "reason": "prompt_too_long"}

        if (
            self._openrouter_image_client is None
            or self._settings.openrouter_image_model is None
        ):
            reply_target = resolve_reply_target(message, self._settings)
            background_tasks.add_task(
                self._safe_send_text,
                message,
                "Image mode is not configured on this bot.",
                reply_target,
            )
            return {"status": "accepted", "reason": "image_unavailable"}

        background_tasks.add_task(self._process_imagine, message, prompt)
        return {"status": "accepted", "reason": "queued"}

    async def handle_chat_mention(self, message: IncomingMessage, prompt: str) -> None:
        reply_target = resolve_reply_target(message, self._settings)
        fallback_recipient = (
            message.sender if reply_target.group_id is not None else None
        )
        conversation_key = conversation_key_for_message(message)
        history = self._chat_context.get_history(conversation_key)
        chat_messages = build_chat_messages(
            system_prompt=self._settings.bot_chat_system_prompt,
            history=history,
            prompt=prompt,
        )

        try:
            reply = await self._openrouter_client.generate_reply(chat_messages)
            if self._settings.bot_chat_force_plain_text:
                reply = coerce_plain_text_reply(reply)
            if not reply:
                reply = "I could not generate a usable plain-text reply. Try again."

            normalized_reply = _truncate_reply(reply)
            await self._signal_client.send_text(
                target=reply_target,
                message=normalized_reply,
                fallback_recipient=fallback_recipient,
            )
            self._chat_context.append_turn(
                conversation_key,
                user_text=prompt,
                assistant_text=normalized_reply,
            )
        except ChatReplyError as exc:
            logger.warning(
                "chat_generation_error sender=%s group_id=%s detail=%s",
                message.sender,
                message.target.group_id,
                exc,
            )
            await self._safe_send_text(message, exc.user_message, reply_target)
        except SignalSendError:
            logger.exception(
                "signal_send_error sender=%s group_id=%s",
                message.sender,
                message.target.group_id,
            )
        except Exception:
            logger.exception("unexpected_chat_error sender=%s", message.sender)
            await self._safe_send_text(
                message,
                "Unexpected error while generating chat reply.",
                reply_target,
            )

    async def _process_imagine(self, message: IncomingMessage, prompt: str) -> None:
        reply_target = resolve_reply_target(message, self._settings)
        await self._safe_send_text(
            message,
            "Generating image, please wait...",
            reply_target,
        )

        try:
            if (
                self._openrouter_image_client is None
                or self._settings.openrouter_image_model is None
            ):
                await self._safe_send_text(
                    message,
                    "Image mode is not configured on this bot.",
                    reply_target,
                )
                return

            images = await self._openrouter_image_client.generate_images(
                prompt=prompt,
                model=self._settings.openrouter_image_model,
            )
            for index, (image_bytes, content_type) in enumerate(images):
                await self._signal_client.send_image(
                    target=reply_target,
                    image_bytes=image_bytes,
                    content_type=content_type,
                    caption=f"/imagine {prompt}"[:200] if index == 0 else None,
                )
        except ImageGenerationError as exc:
            logger.warning(
                "image_generation_error sender=%s detail=%s", message.sender, exc
            )
            await self._safe_send_text(message, exc.user_message, reply_target)
        except SignalSendError:
            logger.exception(
                "signal_send_error sender=%s group_id=%s",
                message.sender,
                message.target.group_id,
            )
        except Exception:
            logger.exception("unexpected_processing_error sender=%s", message.sender)
            await self._safe_send_text(
                message,
                "Unexpected error while generating image.",
                reply_target,
            )

    async def _safe_send_text(
        self,
        message: IncomingMessage,
        text: str,
        reply_target: Target,
    ) -> None:
        try:
            await self._signal_client.send_text(target=reply_target, message=text)
        except SignalSendError:
            logger.exception(
                "signal_send_text_failed sender=%s group_id=%s",
                message.sender,
                message.target.group_id,
            )


def parse_imagine_prompt(text: str) -> str | None:
    stripped = text.strip()
    if not stripped.startswith(COMMAND_PREFIX):
        return None

    tail = stripped[len(COMMAND_PREFIX) :]
    return tail.strip()


def should_handle_chat_mention(message: IncomingMessage, settings: Settings) -> bool:
    if message.target.group_id is None:
        return False

    if metadata_mentions_bot(
        message,
        settings.signal_sender_number,
        settings.signal_sender_uuid,
    ):
        return True

    return text_contains_alias(message.text, settings.bot_mention_aliases)


def normalize_chat_prompt(message: IncomingMessage, settings: Settings) -> str:
    text = message.text
    if metadata_mentions_bot(
        message,
        settings.signal_sender_number,
        settings.signal_sender_uuid,
    ):
        text = strip_mention_spans(text, message.mentions)

    text = strip_aliases(text, settings.bot_mention_aliases)
    text = " ".join(text.split())
    return text.lstrip(" ,:;-\n\t")


def text_contains_alias(text: str, aliases: tuple[str, ...]) -> bool:
    return any(_alias_pattern(alias).search(text) for alias in aliases)


def strip_aliases(text: str, aliases: tuple[str, ...]) -> str:
    cleaned = text
    for alias in aliases:
        cleaned = _alias_pattern(alias).sub(" ", cleaned)
    return cleaned


def _alias_pattern(alias: str) -> re.Pattern[str]:
    escaped = re.escape(alias)
    return re.compile(rf"(^|\s){escaped}(?=$|\s|[,:;.!?])", re.IGNORECASE)


def is_authorized_message(message: IncomingMessage, settings: Settings) -> bool:
    if settings.signal_disable_auth:
        return True

    if message.sender in settings.signal_allowed_numbers:
        return True

    group_id = message.target.group_id
    return group_id is not None and group_id in settings.signal_allowed_group_ids


def resolve_reply_target(message: IncomingMessage, settings: Settings) -> Target:
    if (
        settings.bot_group_reply_mode == "dm_fallback"
        and message.target.group_id is not None
    ):
        return Target(recipient=message.sender, group_id=None)
    return message.target


def conversation_key_for_message(message: IncomingMessage) -> str:
    if message.target.group_id is not None:
        return f"group:{message.target.group_id}"
    return f"dm:{message.sender}"


def _truncate_reply(text: str) -> str:
    if len(text) <= CHAT_MAX_REPLY_CHARS:
        return text
    return f"{text[:CHAT_MAX_REPLY_CHARS].rstrip()}..."


def build_router(handler: WebhookHandler) -> APIRouter:
    router = APIRouter()

    @router.post("/webhook/signal")
    async def signal_webhook(
        payload: dict[str, object],
        background_tasks: BackgroundTasks,
    ) -> dict[str, str]:
        return await handler.handle_webhook(payload, background_tasks)

    return router
