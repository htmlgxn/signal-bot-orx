from __future__ import annotations

import logging
import re
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Header

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
from signal_bot_orx.search_client import SearchError, SearchMode
from signal_bot_orx.search_service import (
    SearchRouteDecision,
    SearchService,
    build_followup_template_prompt,
)
from signal_bot_orx.signal_client import SignalClient, SignalSendError
from signal_bot_orx.telegram_client import TelegramClient, TelegramSendError
from signal_bot_orx.types import (
    IncomingMessage,
    Target,
    dedupe_key,
    metadata_mentions_bot,
    parse_incoming_webhook,
    strip_mention_spans,
)
from signal_bot_orx.weather_client import (
    OpenWeatherClient,
    _format_current,
    _format_forecast,
)
from signal_bot_orx.whatsapp_client import WhatsAppClient, WhatsAppSendError

logger = logging.getLogger(__name__)

COMMAND_PREFIX = "/imagine"
CHAT_MAX_REPLY_CHARS = 2000
SEARCH_COMMANDS: dict[str, SearchMode] = {
    "/search": "search",
    "/news": "news",
    "/wiki": "wiki",
    "/images": "images",
    "/videos": "videos",
    "/jmail": "jmail",
    "/lc_cyraxx": "lolcow_cyraxx",
    "/lc_larson": "lolcow_larson",
}


class WebhookHandler:
    def __init__(
        self,
        *,
        settings: Settings,
        signal_client: SignalClient | None,
        whatsapp_client: WhatsAppClient | None = None,
        telegram_client: TelegramClient | None = None,
        openrouter_client: OpenRouterClient,
        openrouter_image_client: OpenRouterImageClient | None,
        chat_context: ChatContextStore,
        dedupe: DedupeCache,
        weather_client: OpenWeatherClient | None = None,
        search_service: SearchService | None = None,
    ) -> None:
        self._settings = settings
        self._signal_client = signal_client
        self._whatsapp_client = whatsapp_client
        self._telegram_client = telegram_client
        self._openrouter_client = openrouter_client
        self._openrouter_image_client = openrouter_image_client
        self._chat_context = chat_context
        self._search_service = search_service
        self._dedupe = dedupe

        self._weather_client = weather_client

    async def _process_weather_current(
        self, parsed: IncomingMessage, location: str
    ) -> None:
        try:
            data = await self._weather_client.current(location)  # type: ignore[union-attr]
            reply = _format_current(data, self._settings.weather_units)
        except Exception as exc:
            reply = f"Unable to retrieve weather: {exc}"
        reply_target = resolve_reply_target(parsed, self._settings)
        await self._safe_send_text(parsed, reply, reply_target)

    async def _process_weather_forecast(
        self, parsed: IncomingMessage, location: str
    ) -> None:
        try:
            data = await self._weather_client.forecast(location)  # type: ignore[union-attr]
            reply = _format_forecast(data, self._settings.weather_units)
        except Exception as exc:
            reply = f"Unable to retrieve forecast: {exc}"
        reply_target = resolve_reply_target(parsed, self._settings)
        await self._safe_send_text(parsed, reply, reply_target)

    async def handle_webhook(
        self,
        payload: dict[str, object],
        background_tasks: BackgroundTasks,
        *,
        transport_hint: Literal["signal", "whatsapp", "telegram"] | None = None,
        telegram_secret: str | None = None,
    ) -> dict[str, str]:
        if transport_hint == "telegram":
            if not self._settings.telegram_enabled or self._telegram_client is None:
                return {"status": "ignored", "reason": "telegram_disabled"}
            if not is_valid_telegram_secret(
                provided_secret=telegram_secret,
                expected_secret=self._settings.telegram_webhook_secret,
            ):
                return {"status": "ignored", "reason": "invalid_telegram_secret"}

        parsed = parse_incoming_webhook(
            payload,
            telegram_bot_username=self._settings.telegram_bot_username,
            transport_hint=transport_hint,
        )
        if parsed is None:
            logger.debug(
                "unsupported_event method_present=%s top_level_key_count=%d",
                "method" in payload,
                len(payload),
            )
            self._log_search_route(
                message_scope="unknown",
                mention_eligible=False,
                slash_command=None,
                auto_decision=None,
                final_path="ignored",
                reason="unsupported_event",
            )
            return {"status": "ignored", "reason": "unsupported_event"}

        if parsed.transport == "whatsapp" and (
            not self._settings.whatsapp_enabled or self._whatsapp_client is None
        ):
            return {"status": "ignored", "reason": "whatsapp_disabled"}
        if parsed.transport == "signal" and (
            not self._settings.signal_enabled or self._signal_client is None
        ):
            return {"status": "ignored", "reason": "signal_disabled"}
        if parsed.transport == "telegram" and (
            not self._settings.telegram_enabled or self._telegram_client is None
        ):
            return {"status": "ignored", "reason": "telegram_disabled"}

        message_scope = "group" if parsed.target.group_id is not None else "dm"
        mention_eligible = should_handle_chat_mention(parsed, self._settings)

        if not is_authorized_message(parsed, self._settings):
            logger.info(
                "ignoring_unauthorized_sender sender=%s group_id=%s",
                parsed.sender,
                parsed.target.group_id,
            )
            self._log_search_route(
                message_scope=message_scope,
                mention_eligible=mention_eligible,
                slash_command=None,
                auto_decision=None,
                final_path="ignored",
                reason="unauthorized",
            )
            return {"status": "ignored", "reason": "unauthorized"}

        key = dedupe_key(parsed)
        if not self._dedupe.mark_once(key):
            self._log_search_route(
                message_scope=message_scope,
                mention_eligible=mention_eligible,
                slash_command=None,
                auto_decision=None,
                final_path="ignored",
                reason="duplicate",
            )
            return {"status": "ignored", "reason": "duplicate"}

        command_text = normalized_command_text(parsed, self._settings)

        source_claim = parse_source_command(parsed.text) or parse_source_command(
            command_text
        )
        if source_claim is not None:
            self._clear_pending_followup_state(parsed)
            self._clear_pending_video_selection_state(parsed)
            self._log_search_route(
                message_scope=message_scope,
                mention_eligible=mention_eligible,
                slash_command="/source",
                auto_decision=None,
                final_path="search_source",
                reason="source_command",
            )
            return self.handle_source_command(parsed, source_claim, background_tasks)

        search_command = parse_search_command(parsed.text) or parse_search_command(
            command_text
        )
        if search_command is not None:
            mode, query = search_command
            self._clear_pending_followup_state(parsed)
            self._clear_pending_video_selection_state(parsed)
            if mode == "images":
                final_path = "search_image"
            elif mode == "videos":
                final_path = "search_videos"
            else:
                final_path = "search_summary"
            self._log_search_route(
                message_scope=message_scope,
                mention_eligible=mention_eligible,
                slash_command=f"/{mode}",
                auto_decision=None,
                final_path=final_path,
                reason="search_command",
            )
            return self.handle_search_command(
                parsed,
                mode,
                query,
                background_tasks,
            )

        imagine_prompt = parse_imagine_prompt(parsed.text) or parse_imagine_prompt(
            command_text
        )
        if imagine_prompt is not None:
            self._clear_pending_followup_state(parsed)
            self._clear_pending_video_selection_state(parsed)
            self._log_search_route(
                message_scope=message_scope,
                mention_eligible=mention_eligible,
                slash_command="/imagine",
                auto_decision=None,
                final_path="chat",
                reason="imagine_command",
            )
            return self.handle_imagine_command(parsed, imagine_prompt, background_tasks)

        selection_number = parse_numeric_selection(parsed.text) or (
            parse_numeric_selection(command_text)
            if command_text != parsed.text
            else None
        )
        if (
            selection_number is not None
            and self._search_service is not None
            and self._settings.bot_search_enabled
        ):
            conversation_key = conversation_key_for_message(parsed)
            # Check JMail selection first
            pending_jmail = self._search_service.get_pending_jmail_selection_state(
                conversation_key=conversation_key,
            )
            if pending_jmail is not None:
                self._log_search_route(
                    message_scope=message_scope,
                    mention_eligible=mention_eligible,
                    slash_command=None,
                    auto_decision=None,
                    final_path="search_jmail_selection",
                    reason="jmail_selection",
                )
                background_tasks.add_task(
                    self._process_search_jmail_selection,
                    parsed,
                    selection_number,
                )
                return {"status": "accepted", "reason": "search_jmail_selection_queued"}

            # Then check Video selection
            pending_video = self._search_service.get_pending_video_selection_state(
                conversation_key=conversation_key,
            )
            if pending_video is not None:
                self._log_search_route(
                    message_scope=message_scope,
                    mention_eligible=mention_eligible,
                    slash_command=None,
                    auto_decision=None,
                    final_path="search_video_selection",
                    reason="video_selection",
                )
                background_tasks.add_task(
                    self._process_search_video_selection,
                    parsed,
                    selection_number,
                )
                return {"status": "accepted", "reason": "search_video_selection_queued"}

        if not mention_eligible:
            self._log_search_route(
                message_scope=message_scope,
                mention_eligible=False,
                slash_command=None,
                auto_decision=None,
                final_path="ignored",
                reason="non_mention",
            )
            return {"status": "ignored", "reason": "non_mention"}

        # Weather command handling
        if command_text == "/weather" or command_text.startswith("/weather "):
            location = (
                command_text[len("/weather ") :].strip()
                if command_text.startswith("/weather ")
                else ""
            )
            if not location and self._settings.weather_default_location:
                location = self._settings.weather_default_location
            if not location:
                reply_target = resolve_reply_target(parsed, self._settings)
                background_tasks.add_task(
                    self._safe_send_text,
                    parsed,
                    "Usage: /weather <location>",
                    reply_target,
                )
                return {"status": "accepted", "reason": "weather_usage_sent"}
            if not self._weather_client:
                reply_target = resolve_reply_target(parsed, self._settings)
                background_tasks.add_task(
                    self._safe_send_text,
                    parsed,
                    "Weather is not configured on this bot.",
                    reply_target,
                )
                return {"status": "accepted", "reason": "weather_disabled"}
            background_tasks.add_task(self._process_weather_current, parsed, location)
            return {"status": "accepted", "reason": "weather_queued"}
        if command_text == "/forecast" or command_text.startswith("/forecast "):
            location = (
                command_text[len("/forecast ") :].strip()
                if command_text.startswith("/forecast ")
                else ""
            )
            if not location and self._settings.weather_default_location:
                location = self._settings.weather_default_location
            if not location:
                reply_target = resolve_reply_target(parsed, self._settings)
                background_tasks.add_task(
                    self._safe_send_text,
                    parsed,
                    "Usage: /forecast <location>",
                    reply_target,
                )
                return {"status": "accepted", "reason": "forecast_usage_sent"}
            if not self._weather_client:
                reply_target = resolve_reply_target(parsed, self._settings)
                background_tasks.add_task(
                    self._safe_send_text,
                    parsed,
                    "Weather is not configured on this bot.",
                    reply_target,
                )
                return {"status": "accepted", "reason": "weather_disabled"}
            background_tasks.add_task(self._process_weather_forecast, parsed, location)
            return {"status": "accepted", "reason": "forecast_queued"}

        chat_prompt = normalize_chat_prompt(parsed, self._settings)
        if not chat_prompt:
            reply_target = resolve_reply_target(parsed, self._settings)
            background_tasks.add_task(
                self._safe_send_text,
                parsed,
                _chat_usage_message(parsed),
                reply_target,
            )
            self._log_search_route(
                message_scope=message_scope,
                mention_eligible=True,
                slash_command=None,
                auto_decision=None,
                final_path="chat",
                reason="chat_usage_sent",
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
            self._log_search_route(
                message_scope=message_scope,
                mention_eligible=True,
                slash_command=None,
                auto_decision=None,
                final_path="chat",
                reason="chat_prompt_too_long",
            )
            return {"status": "accepted", "reason": "chat_prompt_too_long"}

        claim_request = parse_source_request_text(chat_prompt)
        if claim_request is not None:
            self._log_search_route(
                message_scope=message_scope,
                mention_eligible=True,
                slash_command=None,
                auto_decision=None,
                final_path="search_source",
                reason="source_request_text",
            )
            return self.handle_source_command(parsed, claim_request, background_tasks)

        if (
            self._settings.bot_search_enabled
            and self._settings.bot_search_context_mode == "context"
            and self._search_service is not None
        ):
            conversation_key = conversation_key_for_message(parsed)
            followup_history_context = build_followup_resolution_history_context(
                chat_context=self._chat_context,
                conversation_key=conversation_key,
            )
            source_context = self._search_service.recent_source_context(
                conversation_key=conversation_key,
                limit=6,
            )
            pending_state = self._search_service.get_pending_followup_state(
                conversation_key=conversation_key,
            )
            resolved_prompt = chat_prompt
            summary_user_request = chat_prompt

            if pending_state is not None:
                if is_pending_followup_reply_candidate(chat_prompt):
                    pending_resolution = (
                        await self._search_service.resolve_pending_followup_reply(
                            reply_prompt=chat_prompt,
                            pending_state=pending_state,
                            history_context=followup_history_context,
                            source_context=source_context,
                        )
                    )
                    if pending_resolution.needs_clarification:
                        attempts = self._search_service.bump_pending_followup_attempt(
                            conversation_key=conversation_key,
                        )
                        self._log_followup_resolution(
                            event="followup_pending_set",
                            history_count=len(followup_history_context),
                            source_count=len(source_context),
                            used_context=pending_resolution.used_context,
                            reason=pending_resolution.reason,
                            prompt_len=len(chat_prompt),
                            resolved_len=len(pending_resolution.resolved_prompt),
                            confidence=pending_resolution.confidence,
                        )
                        reply_target = resolve_reply_target(parsed, self._settings)
                        if attempts >= 1:
                            self._search_service.clear_pending_followup_state(
                                conversation_key=conversation_key,
                            )
                            self._log_followup_resolution(
                                event="followup_pending_cleared",
                                history_count=len(followup_history_context),
                                source_count=len(source_context),
                                used_context=True,
                                reason="max_attempts_reached",
                                prompt_len=len(chat_prompt),
                                resolved_len=0,
                                confidence=0.0,
                            )
                            background_tasks.add_task(
                                self._safe_send_text,
                                parsed,
                                "Please restate your full question, for example: "
                                "who is god in islam?",
                                reply_target,
                            )
                            return {
                                "status": "accepted",
                                "reason": "search_followup_rephrase_requested",
                            }

                        background_tasks.add_task(
                            self._safe_send_text,
                            parsed,
                            pending_resolution.clarification_text
                            or "Who are you referring to?",
                            reply_target,
                        )
                        return {
                            "status": "accepted",
                            "reason": "search_followup_clarification",
                        }

                    self._search_service.clear_pending_followup_state(
                        conversation_key=conversation_key,
                    )
                    resolved_prompt = pending_resolution.resolved_prompt or chat_prompt
                    summary_user_request = resolved_prompt
                    self._log_followup_resolution(
                        event="followup_pending_applied",
                        history_count=len(followup_history_context),
                        source_count=len(source_context),
                        used_context=pending_resolution.used_context,
                        reason=pending_resolution.reason,
                        prompt_len=len(chat_prompt),
                        resolved_len=len(resolved_prompt),
                        confidence=pending_resolution.confidence,
                    )
                else:
                    self._search_service.clear_pending_followup_state(
                        conversation_key=conversation_key,
                    )
                    self._log_followup_resolution(
                        event="followup_pending_cleared",
                        history_count=len(followup_history_context),
                        source_count=len(source_context),
                        used_context=False,
                        reason="non_candidate_new_prompt",
                        prompt_len=len(chat_prompt),
                        resolved_len=0,
                        confidence=0.0,
                    )

            if pending_state is None:
                followup_resolution = (
                    await self._search_service.resolve_followup_prompt(
                        prompt=chat_prompt,
                        history_context=followup_history_context,
                        source_context=source_context,
                    )
                )
                self._log_followup_resolution(
                    event="followup_resolution_detected",
                    history_count=len(followup_history_context),
                    source_count=len(source_context),
                    used_context=followup_resolution.used_context,
                    reason=followup_resolution.reason,
                    prompt_len=len(chat_prompt),
                    resolved_len=len(followup_resolution.resolved_prompt),
                    confidence=followup_resolution.confidence,
                )
                if followup_resolution.needs_clarification:
                    template_prompt = build_followup_template_prompt(chat_prompt)
                    self._search_service.set_pending_followup_state(
                        conversation_key=conversation_key,
                        original_prompt=chat_prompt,
                        template_prompt=template_prompt,
                        reason=followup_resolution.reason,
                    )
                    self._log_followup_resolution(
                        event="followup_pending_set",
                        history_count=len(followup_history_context),
                        source_count=len(source_context),
                        used_context=followup_resolution.used_context,
                        reason=followup_resolution.reason,
                        prompt_len=len(chat_prompt),
                        resolved_len=len(template_prompt),
                        confidence=followup_resolution.confidence,
                    )
                    reply_target = resolve_reply_target(parsed, self._settings)
                    clarification_text = (
                        followup_resolution.clarification_text
                        or "Who are you referring to?"
                    )
                    self._log_followup_resolution(
                        event="followup_resolution_clarify",
                        history_count=len(followup_history_context),
                        source_count=len(source_context),
                        used_context=followup_resolution.used_context,
                        reason=followup_resolution.reason,
                        prompt_len=len(chat_prompt),
                        resolved_len=len(followup_resolution.resolved_prompt),
                        confidence=followup_resolution.confidence,
                    )
                    background_tasks.add_task(
                        self._safe_send_text,
                        parsed,
                        clarification_text,
                        reply_target,
                    )
                    self._log_search_route(
                        message_scope=message_scope,
                        mention_eligible=True,
                        slash_command=None,
                        auto_decision=None,
                        final_path="search_clarify",
                        reason="followup_clarification",
                    )
                    return {
                        "status": "accepted",
                        "reason": "search_followup_clarification",
                    }

                resolved_prompt = followup_resolution.resolved_prompt or chat_prompt
                self._log_followup_resolution(
                    event="followup_resolution_resolved",
                    history_count=len(followup_history_context),
                    source_count=len(source_context),
                    used_context=followup_resolution.used_context,
                    reason=followup_resolution.reason,
                    prompt_len=len(chat_prompt),
                    resolved_len=len(resolved_prompt),
                    confidence=followup_resolution.confidence,
                )

            decision = await self._search_service.decide_auto_search(resolved_prompt)
            if decision.should_search and is_search_mode_enabled(
                decision.mode, self._settings
            ):
                self._search_service.clear_pending_followup_state(
                    conversation_key=conversation_key,
                )
                self._search_service.clear_pending_video_selection_state(
                    conversation_key=conversation_key,
                )
                self._search_service.clear_pending_jmail_selection_state(
                    conversation_key=conversation_key,
                )
                if decision.mode == "images":
                    self._log_search_route(
                        message_scope=message_scope,
                        mention_eligible=True,
                        slash_command=None,
                        auto_decision=decision,
                        final_path="search_image",
                        reason="search_image_queued",
                    )
                    background_tasks.add_task(
                        self._process_search_image,
                        parsed,
                        decision.query,
                    )
                    return {"status": "accepted", "reason": "search_image_queued"}

                self._log_search_route(
                    message_scope=message_scope,
                    mention_eligible=True,
                    slash_command=None,
                    auto_decision=decision,
                    final_path="search_summary",
                    reason="search_queued",
                )
                background_tasks.add_task(
                    self._process_search_summary,
                    parsed,
                    decision.mode,
                    decision.query,
                    summary_user_request,
                )
                return {"status": "accepted", "reason": "search_queued"}

            self._log_search_route(
                message_scope=message_scope,
                mention_eligible=True,
                slash_command=None,
                auto_decision=decision,
                final_path="chat",
                reason="search_not_selected",
            )

        self._log_search_route(
            message_scope=message_scope,
            mention_eligible=True,
            slash_command=None,
            auto_decision=None,
            final_path="chat",
            reason="chat_queued",
        )
        background_tasks.add_task(self.handle_chat_mention, parsed, chat_prompt)
        return {"status": "accepted", "reason": "chat_queued"}

    def handle_search_command(
        self,
        message: IncomingMessage,
        mode: SearchMode,
        query: str,
        background_tasks: BackgroundTasks,
    ) -> dict[str, str]:
        if not self._settings.bot_search_enabled or self._search_service is None:
            reply_target = resolve_reply_target(message, self._settings)
            background_tasks.add_task(
                self._safe_send_text,
                message,
                "Search is disabled on this bot.",
                reply_target,
            )
            return {"status": "accepted", "reason": "search_disabled"}

        if not is_search_mode_enabled(mode, self._settings):
            reply_target = resolve_reply_target(message, self._settings)
            background_tasks.add_task(
                self._safe_send_text,
                message,
                f"/{mode} is disabled on this bot.",
                reply_target,
            )
            return {"status": "accepted", "reason": "search_mode_disabled"}

        if not query:
            reply_target = resolve_reply_target(message, self._settings)
            background_tasks.add_task(
                self._safe_send_text,
                message,
                f"Usage: /{mode} <query>",
                reply_target,
            )
            return {"status": "accepted", "reason": "search_usage_sent"}

        if len(query) > self._settings.bot_max_prompt_chars:
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
            return {"status": "accepted", "reason": "search_prompt_too_long"}

        if mode == "images":
            background_tasks.add_task(self._process_search_image, message, query)
            return {"status": "accepted", "reason": "search_image_queued"}

        if mode == "videos":
            background_tasks.add_task(self._process_search_videos_list, message, query)
            return {"status": "accepted", "reason": "search_videos_queued"}

        if mode == "jmail":
            background_tasks.add_task(self._process_search_jmail_list, message, query)
            return {"status": "accepted", "reason": "search_jmail_queued"}

        background_tasks.add_task(self._process_search_summary, message, mode, query)
        return {"status": "accepted", "reason": "search_queued"}

    def handle_source_command(
        self,
        message: IncomingMessage,
        claim: str,
        background_tasks: BackgroundTasks,
    ) -> dict[str, str]:
        if not self._settings.bot_search_enabled or self._search_service is None:
            reply_target = resolve_reply_target(message, self._settings)
            background_tasks.add_task(
                self._safe_send_text,
                message,
                "Search is disabled on this bot.",
                reply_target,
            )
            return {"status": "accepted", "reason": "search_disabled"}

        background_tasks.add_task(self._process_source_lookup, message, claim)
        return {"status": "accepted", "reason": "source_queued"}

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
            await self._send_text(
                transport=message.transport,
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
        except SignalSendError, WhatsAppSendError, TelegramSendError:
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
                await self._send_image(
                    transport=message.transport,
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
        except SignalSendError, WhatsAppSendError, TelegramSendError:
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

    async def _process_search_summary(
        self,
        message: IncomingMessage,
        mode: SearchMode,
        query: str,
        user_request: str | None = None,
    ) -> None:
        if self._search_service is None:
            return

        reply_target = resolve_reply_target(message, self._settings)
        fallback_recipient = (
            message.sender if reply_target.group_id is not None else None
        )
        conversation_key = conversation_key_for_message(message)
        history_context = build_search_summary_history_context(
            chat_context=self._chat_context,
            conversation_key=conversation_key,
            enabled=self._settings.bot_search_use_history_for_summary,
        )

        try:
            summary = await self._search_service.summarize_search(
                conversation_key=conversation_key,
                mode=mode,
                query=query,
                user_request=user_request,
                history_context=history_context,
            )
            if self._settings.bot_chat_force_plain_text:
                summary = coerce_plain_text_reply(summary)
            summary = _truncate_reply(summary)
            await self._send_text(
                transport=message.transport,
                target=reply_target,
                message=summary,
                fallback_recipient=fallback_recipient,
            )
            self._chat_context.append_turn(
                conversation_key,
                user_text=user_request or query,
                assistant_text=summary,
            )
        except SearchError as exc:
            await self._safe_send_text(message, exc.user_message, reply_target)
        except SignalSendError, WhatsAppSendError, TelegramSendError:
            logger.exception(
                "signal_send_error sender=%s group_id=%s",
                message.sender,
                message.target.group_id,
            )
        except Exception:
            logger.exception("unexpected_search_error sender=%s", message.sender)
            await self._safe_send_text(
                message,
                "Unexpected error while running search.",
                reply_target,
            )

    async def _process_search_image(self, message: IncomingMessage, query: str) -> None:
        if self._search_service is None:
            return

        reply_target = resolve_reply_target(message, self._settings)
        conversation_key = conversation_key_for_message(message)

        try:
            image_bytes, content_type = await self._search_service.search_image(
                conversation_key=conversation_key,
                query=query,
            )
            await self._send_image(
                transport=message.transport,
                target=reply_target,
                image_bytes=image_bytes,
                content_type=content_type,
                caption=f"/images {query}"[:200],
            )
        except SearchError as exc:
            await self._safe_send_text(message, exc.user_message, reply_target)
        except SignalSendError, WhatsAppSendError, TelegramSendError:
            logger.exception(
                "signal_send_error sender=%s group_id=%s",
                message.sender,
                message.target.group_id,
            )
        except Exception:
            logger.exception("unexpected_search_image_error sender=%s", message.sender)
            await self._safe_send_text(
                message,
                "Unexpected error while searching images.",
                reply_target,
            )

    async def _process_search_videos_list(
        self,
        message: IncomingMessage,
        query: str,
    ) -> None:
        if self._search_service is None:
            return

        reply_target = resolve_reply_target(message, self._settings)
        conversation_key = conversation_key_for_message(message)

        try:
            response_text = await self._search_service.video_list_reply(
                conversation_key=conversation_key,
                query=query,
            )
            await self._send_text(
                transport=message.transport,
                target=reply_target,
                message=_truncate_reply(response_text),
            )
        except SearchError as exc:
            await self._safe_send_text(message, exc.user_message, reply_target)
        except SignalSendError, WhatsAppSendError, TelegramSendError:
            logger.exception(
                "signal_send_error sender=%s group_id=%s",
                message.sender,
                message.target.group_id,
            )
        except Exception:
            logger.exception("unexpected_search_videos_error sender=%s", message.sender)
            await self._safe_send_text(
                message,
                "Unexpected error while searching videos.",
                reply_target,
            )

    async def _process_search_jmail_list(
        self,
        message: IncomingMessage,
        query: str,
    ) -> None:
        if self._search_service is None:
            return

        reply_target = resolve_reply_target(message, self._settings)
        conversation_key = conversation_key_for_message(message)

        try:
            response_text = await self._search_service.jmail_list_reply(
                conversation_key=conversation_key,
                query=query,
            )
            await self._send_text(
                transport=message.transport,
                target=reply_target,
                message=_truncate_reply(response_text),
            )
        except SearchError as exc:
            await self._safe_send_text(message, exc.user_message, reply_target)
        except SignalSendError, WhatsAppSendError, TelegramSendError:
            logger.exception(
                "signal_send_error sender=%s group_id=%s",
                message.sender,
                message.target.group_id,
            )

    async def _process_search_video_selection(
        self,
        message: IncomingMessage,
        selection_number: int,
    ) -> None:
        if self._search_service is None:
            return

        reply_target = resolve_reply_target(message, self._settings)
        conversation_key = conversation_key_for_message(message)
        fallback_recipient = (
            message.sender if reply_target.group_id is not None else None
        )

        try:
            (
                image_bytes,
                content_type,
                url,
                title,
            ) = await self._search_service.resolve_video_selection(
                conversation_key=conversation_key,
                selection_number=selection_number,
            )
            self._search_service.clear_pending_video_selection_state(
                conversation_key=conversation_key,
            )
            video_text = _truncate_reply(f"{title}\n{url}")
            if image_bytes is not None and content_type is not None:
                await self._send_image(
                    transport=message.transport,
                    target=reply_target,
                    image_bytes=image_bytes,
                    content_type=content_type,
                    caption=video_text[:200],
                )
                return

            await self._send_text(
                transport=message.transport,
                target=reply_target,
                message=video_text,
                fallback_recipient=fallback_recipient,
            )
        except SearchError as exc:
            await self._safe_send_text(message, exc.user_message, reply_target)
        except SignalSendError, WhatsAppSendError, TelegramSendError:
            logger.exception(
                "signal_send_error sender=%s group_id=%s",
                message.sender,
                message.target.group_id,
            )
        except Exception:
            logger.exception(
                "unexpected_search_video_selection_error sender=%s", message.sender
            )
            await self._safe_send_text(
                message,
                "Unexpected error while selecting video result.",
                reply_target,
            )

    async def _process_search_jmail_selection(
        self,
        message: IncomingMessage,
        selection_number: int,
    ) -> None:
        if self._search_service is None:
            return

        reply_target = resolve_reply_target(message, self._settings)
        conversation_key = conversation_key_for_message(message)

        try:
            history_context = build_search_summary_history_context(
                chat_context=self._chat_context,
                conversation_key=conversation_key,
                enabled=self._settings.bot_search_use_history_for_summary,
            )

            summary = await self._search_service.resolve_jmail_selection(
                conversation_key=conversation_key,
                selection_number=selection_number,
                history_context=history_context,
            )
            self._clear_pending_jmail_selection_state(message)

            await self._send_text(
                transport=message.transport,
                target=reply_target,
                message=_truncate_reply(summary),
            )
        except SearchError as exc:
            await self._safe_send_text(message, exc.user_message, reply_target)
        except SignalSendError, WhatsAppSendError, TelegramSendError:
            logger.exception(
                "signal_send_error sender=%s group_id=%s",
                message.sender,
                message.target.group_id,
            )
        except Exception:
            logger.exception(
                "unexpected_search_jmail_selection_error sender=%s", message.sender
            )
            await self._safe_send_text(
                message,
                "Unexpected error while selecting JMail result.",
                reply_target,
            )

    async def _process_source_lookup(
        self, message: IncomingMessage, claim: str
    ) -> None:
        if self._search_service is None:
            return

        reply_target = resolve_reply_target(message, self._settings)
        conversation_key = conversation_key_for_message(message)

        try:
            response_text = self._search_service.source_reply(
                conversation_key=conversation_key,
                claim=claim,
            )
            await self._send_text(
                transport=message.transport,
                target=reply_target,
                message=response_text,
            )
        except SignalSendError, WhatsAppSendError, TelegramSendError:
            logger.exception(
                "signal_send_error sender=%s group_id=%s",
                message.sender,
                message.target.group_id,
            )
        except Exception:
            logger.exception("unexpected_source_lookup_error sender=%s", message.sender)
            await self._safe_send_text(
                message,
                "Unexpected error while resolving sources.",
                reply_target,
            )

    async def _send_text(
        self,
        *,
        transport: Literal["signal", "whatsapp", "telegram"],
        target: Target,
        message: str,
        fallback_recipient: str | None = None,
    ) -> None:
        if transport == "whatsapp":
            if self._whatsapp_client is None:
                raise WhatsAppSendError("WhatsApp is not configured.")
            await self._whatsapp_client.send_text(target=target, message=message)
            return

        if transport == "telegram":
            if self._telegram_client is None:
                raise TelegramSendError("Telegram is not configured.")
            await self._telegram_client.send_text(target=target, message=message)
            return

        if self._signal_client is None:
            raise SignalSendError("Signal is not configured.")
        await self._signal_client.send_text(
            target=target, message=message, fallback_recipient=fallback_recipient
        )

    async def _send_image(
        self,
        *,
        transport: Literal["signal", "whatsapp", "telegram"],
        target: Target,
        image_bytes: bytes,
        content_type: str,
        caption: str | None = None,
        fallback_recipient: str | None = None,
    ) -> None:
        del fallback_recipient
        if transport == "whatsapp":
            if self._whatsapp_client is None:
                raise WhatsAppSendError("WhatsApp is not configured.")
            await self._whatsapp_client.send_image(
                target=target,
                image_bytes=image_bytes,
                content_type=content_type,
                caption=caption,
            )
            return

        if transport == "telegram":
            if self._telegram_client is None:
                raise TelegramSendError("Telegram is not configured.")
            await self._telegram_client.send_image(
                target=target,
                image_bytes=image_bytes,
                content_type=content_type,
                caption=caption,
            )
            return

        if self._signal_client is None:
            raise SignalSendError("Signal is not configured.")
        await self._signal_client.send_image(
            target=target,
            image_bytes=image_bytes,
            content_type=content_type,
            caption=caption,
        )

    async def _safe_send_text(
        self,
        message: IncomingMessage,
        text: str,
        reply_target: Target,
    ) -> None:
        try:
            await self._send_text(
                transport=message.transport,
                target=reply_target,
                message=text,
            )
        except SignalSendError, WhatsAppSendError, TelegramSendError:
            logger.exception(
                "signal_send_text_failed sender=%s group_id=%s",
                message.sender,
                message.target.group_id,
            )

    def _clear_pending_followup_state(self, message: IncomingMessage) -> None:
        if self._search_service is None:
            return
        self._search_service.clear_pending_followup_state(
            conversation_key=conversation_key_for_message(message),
        )

    def _clear_pending_video_selection_state(self, message: IncomingMessage) -> None:
        if self._search_service is None:
            return
        self._search_service.clear_pending_video_selection_state(
            conversation_key=conversation_key_for_message(message),
        )

    def _clear_pending_jmail_selection_state(self, message: IncomingMessage) -> None:
        if self._search_service is None:
            return
        self._search_service.clear_pending_jmail_selection_state(
            conversation_key=conversation_key_for_message(message),
        )

    def _log_search_route(
        self,
        *,
        message_scope: str,
        mention_eligible: bool,
        slash_command: str | None,
        auto_decision: SearchRouteDecision | None,
        final_path: str,
        reason: str,
    ) -> None:
        if not self._settings.bot_search_debug_logging:
            return

        auto_should_search = auto_decision.should_search if auto_decision else False
        auto_mode = auto_decision.mode if auto_decision else "-"
        auto_query_len = len(auto_decision.query) if auto_decision else 0
        auto_reason = (auto_decision.reason if auto_decision else "").strip() or "-"
        logger.info(
            "search_route_debug scope=%s mention_eligible=%s "
            "search_context_mode=%s slash_command=%s auto_should_search=%s "
            "auto_mode=%s auto_query_len=%d auto_reason=%s final_path=%s reason=%s",
            message_scope,
            mention_eligible,
            self._settings.bot_search_context_mode,
            slash_command or "-",
            auto_should_search,
            auto_mode,
            auto_query_len,
            auto_reason,
            final_path,
            reason,
        )

    def _log_followup_resolution(
        self,
        *,
        event: str,
        history_count: int,
        source_count: int,
        used_context: bool,
        reason: str,
        prompt_len: int,
        resolved_len: int,
        confidence: float | None,
    ) -> None:
        if not self._settings.bot_search_debug_logging:
            return
        logger.info(
            "followup_resolution_debug event=%s history_count=%d source_count=%d "
            "used_context=%s reason=%s prompt_len=%d resolved_len=%d "
            "confidence_bucket=%s",
            event,
            history_count,
            source_count,
            used_context,
            reason or "-",
            prompt_len,
            resolved_len,
            confidence_bucket_for_log(confidence),
        )


def parse_imagine_prompt(text: str) -> str | None:
    stripped = text.strip()
    if not stripped.startswith(COMMAND_PREFIX):
        return None

    tail = stripped[len(COMMAND_PREFIX) :]
    return tail.strip()


def parse_search_command(text: str) -> tuple[SearchMode, str] | None:
    stripped = text.strip()
    for command, mode in SEARCH_COMMANDS.items():
        if stripped == command:
            return mode, ""
        if stripped.startswith(f"{command} "):
            return mode, stripped[len(command) :].strip()
    return None


def parse_source_command(text: str) -> str | None:
    stripped = text.strip()
    if stripped == "/source":
        return ""
    if stripped.startswith("/source "):
        return stripped[len("/source") :].strip()
    return None


def parse_source_request_text(text: str) -> str | None:
    stripped = text.strip()
    if not stripped:
        return None

    patterns = (
        re.compile(
            r"^(?:source|sources|link|links)\s*(?:for|to)?\s*(.*)$", re.IGNORECASE
        ),
        re.compile(
            r"^where did you get (?:that|this|it|those|these)?\s*(.*)$", re.IGNORECASE
        ),
        re.compile(r"^what(?:'s| is) the source(?: for)?\s*(.*)$", re.IGNORECASE),
    )
    for pattern in patterns:
        if match := pattern.match(stripped):
            return match.group(1).strip(" ?.!,:;")
    return None


def normalized_command_text(message: IncomingMessage, settings: Settings) -> str:
    return normalize_chat_prompt(message, settings)


def should_handle_chat_mention(message: IncomingMessage, settings: Settings) -> bool:
    if message.target.group_id is None:
        return True

    if message.transport == "telegram":
        return message.directed_to_bot

    if message.transport == "signal" and metadata_mentions_bot(
        message,
        settings.signal_sender_number,
        settings.signal_sender_uuid,
    ):
        return True

    return text_contains_alias(message.text, settings.bot_mention_aliases)


def normalize_chat_prompt(message: IncomingMessage, settings: Settings) -> str:
    text = message.text
    if (
        message.transport == "signal"
        and settings.signal_enabled
        and metadata_mentions_bot(
            message,
            settings.signal_sender_number,
            settings.signal_sender_uuid,
        )
    ):
        text = strip_mention_spans(text, message.mentions)

    if message.transport == "telegram" and settings.telegram_bot_username:
        text = strip_aliases(text, (f"@{settings.telegram_bot_username}",))

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
    if message.transport == "telegram":
        if settings.telegram_disable_auth:
            return True
        if message.sender in settings.telegram_allowed_user_ids:
            return True
        group_id = message.target.group_id
        return group_id is not None and group_id in settings.telegram_allowed_chat_ids

    if message.transport == "whatsapp":
        if settings.whatsapp_disable_auth:
            return True
        return message.sender in settings.whatsapp_allowed_numbers

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


def build_search_summary_history_context(
    *,
    chat_context: ChatContextStore,
    conversation_key: str,
    enabled: bool,
) -> list[dict[str, str]] | None:
    if not enabled:
        return None

    history = chat_context.get_history(conversation_key)
    recent_messages = history[-4:]
    return [
        {"role": turn.role, "content": turn.content}
        for turn in recent_messages
        if turn.role in {"user", "assistant"} and turn.content.strip()
    ]


def build_followup_resolution_history_context(
    *,
    chat_context: ChatContextStore,
    conversation_key: str,
) -> list[dict[str, str]]:
    history = chat_context.get_history(conversation_key)
    recent_messages = history[-4:]
    return [
        {"role": turn.role, "content": turn.content}
        for turn in recent_messages
        if turn.role in {"user", "assistant"} and turn.content.strip()
    ]


def is_pending_followup_reply_candidate(text: str) -> bool:
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return False
    if normalized.startswith("/"):
        return False
    if len(normalized) > 80:
        return False
    return len(normalized.split()) <= 6


def is_search_mode_enabled(mode: SearchMode, settings: Settings) -> bool:
    if mode == "search":
        return settings.bot_search_mode_search_enabled
    if mode == "news":
        return settings.bot_search_mode_news_enabled
    if mode == "wiki":
        return settings.bot_search_mode_wiki_enabled
    if mode == "images":
        return settings.bot_search_mode_images_enabled
    if mode == "videos":
        return settings.bot_search_mode_videos_enabled
    if mode == "jmail":
        return settings.bot_search_mode_jmail_enabled
    if mode == "lolcow_cyraxx":
        return settings.bot_search_mode_lolcow_cyraxx_enabled
    if mode == "lolcow_larson":
        return settings.bot_search_mode_lolcow_larson_enabled
    return False


def parse_numeric_selection(text: str) -> int | None:
    stripped = text.strip()
    if not re.fullmatch(r"\d+", stripped):
        return None
    try:
        value = int(stripped)
    except ValueError:
        return None
    if value <= 0:
        return None
    return value


def _chat_usage_message(message: IncomingMessage) -> str:
    if message.target.group_id is None:
        return "Send a prompt, for example: summarize today's discussion."
    return "Tag me with a prompt, for example: @bot summarize today's discussion."


def _truncate_reply(text: str) -> str:
    if len(text) <= CHAT_MAX_REPLY_CHARS:
        return text
    return f"{text[:CHAT_MAX_REPLY_CHARS].rstrip()}..."


def confidence_bucket_for_log(confidence: float | None) -> str:
    if confidence is None:
        return "-"
    if confidence >= 0.9:
        return "high"
    if confidence >= 0.7:
        return "medium"
    return "low"


def is_valid_telegram_secret(
    *, provided_secret: str | None, expected_secret: str | None
) -> bool:
    if not expected_secret:
        return True
    if provided_secret is None:
        return False
    return provided_secret == expected_secret


def build_router(handler: WebhookHandler) -> APIRouter:
    router = APIRouter()

    @router.post("/webhook/signal")
    async def signal_webhook(
        payload: dict[str, object],
        background_tasks: BackgroundTasks,
    ) -> dict[str, str]:
        return await handler.handle_webhook(
            payload, background_tasks, transport_hint="signal"
        )

    @router.post("/webhook/whatsapp")
    async def whatsapp_webhook(
        payload: dict[str, object],
        background_tasks: BackgroundTasks,
    ) -> dict[str, str]:
        return await handler.handle_webhook(
            payload, background_tasks, transport_hint="whatsapp"
        )

    @router.post("/webhook/telegram")
    async def telegram_webhook(
        payload: dict[str, object],
        background_tasks: BackgroundTasks,
        telegram_secret: str | None = Header(
            default=None, alias="X-Telegram-Bot-Api-Secret-Token"
        ),
    ) -> dict[str, str]:
        return await handler.handle_webhook(
            payload,
            background_tasks,
            transport_hint="telegram",
            telegram_secret=telegram_secret,
        )

    return router
