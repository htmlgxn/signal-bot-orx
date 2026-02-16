from __future__ import annotations

import json
import logging
from dataclasses import replace

import httpx
import pytest

from signal_bot_orx.config import Settings
from signal_bot_orx.search_client import SearchError, SearchMode, SearchResult
from signal_bot_orx.search_context import PendingFollowupState, SearchContextStore
from signal_bot_orx.search_service import (
    FollowupResolutionDecision,
    SearchRouteDecision,
    SearchService,
)


def _settings() -> Settings:
    return Settings(
        signal_api_base_url="http://localhost:8080",
        signal_sender_number="+15550001111",
        signal_sender_uuid=None,
        signal_allowed_numbers=frozenset({"+15550002222"}),
        signal_allowed_group_ids=frozenset({"group-1"}),
        openrouter_chat_api_key="or-key-chat",
        openrouter_model="openai/gpt-4o-mini",
        bot_chat_system_prompt="CORE_PROMPT_FOR_TEST",
    )


class _FakeSearchClient:
    def __init__(self, results: list[SearchResult]) -> None:
        self._results = results
        self.calls: list[tuple[SearchMode, str]] = []

    async def search(
        self,
        mode: SearchMode,
        query: str,
        settings: Settings,
    ) -> list[SearchResult]:
        del settings
        self.calls.append((mode, query))
        return self._results


class _FakeOpenRouterClient:
    def __init__(self, replies: list[str]) -> None:
        self._replies = replies
        self.seen_messages: list[list[dict[str, str]]] = []

    async def generate_reply(self, messages: list[dict[str, str]]) -> str:
        self.seen_messages.append(messages)
        if self._replies:
            return self._replies.pop(0)
        return ""


@pytest.mark.anyio
async def test_decide_auto_search_parses_json() -> None:
    service = SearchService(
        settings=_settings(),
        search_client=_FakeSearchClient([]),
        search_context=SearchContextStore(ttl_seconds=60),
        openrouter_client=_FakeOpenRouterClient(
            [
                json.dumps(
                    {
                        "should_search": True,
                        "mode": "news",
                        "query": "openrouter",
                        "reason": "current",
                    }
                )
            ]
        ),
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200))
        ),
    )

    decision = await service.decide_auto_search("what happened this week?")

    assert decision == SearchRouteDecision(
        should_search=True,
        mode="news",
        query="openrouter",
        reason="current",
    )


@pytest.mark.anyio
async def test_decide_auto_search_router_prompt_includes_person_lookup_examples() -> (
    None
):
    fake_openrouter = _FakeOpenRouterClient(
        [
            json.dumps(
                {
                    "should_search": True,
                    "mode": "search",
                    "query": "jayleno89 tiktok",
                    "reason": "person_lookup",
                }
            )
        ]
    )
    service = SearchService(
        settings=_settings(),
        search_client=_FakeSearchClient([]),
        search_context=SearchContextStore(ttl_seconds=60),
        openrouter_client=fake_openrouter,
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200))
        ),
    )

    await service.decide_auto_search("who is jayleno89 on tiktok?")

    router_prompt = fake_openrouter.seen_messages[0][0]["content"]
    assert "Person/entity identification prompts should usually search" in router_prompt
    assert 'JSON: {"should_search": true, "mode": "search"' in router_prompt
    assert 'JSON: {"should_search": true, "mode": "news"' in router_prompt
    assert 'JSON: {"should_search": true, "mode": "wiki"' in router_prompt
    assert "who are the councillors of" in router_prompt.lower()
    assert "civic_lookup" in router_prompt


@pytest.mark.anyio
async def test_decide_auto_search_forces_search_for_creator_lookup() -> None:
    service = SearchService(
        settings=_settings(),
        search_client=_FakeSearchClient([]),
        search_context=SearchContextStore(ttl_seconds=60),
        openrouter_client=_FakeOpenRouterClient(
            [
                json.dumps(
                    {
                        "should_search": True,
                        "mode": "wiki",
                        "query": "jayleno89 tiktok",
                        "reason": "bio_lookup",
                    }
                )
            ]
        ),
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200))
        ),
    )

    decision = await service.decide_auto_search("who is jayleno89 on tiktok?")

    assert decision.mode == "search"


@pytest.mark.anyio
async def test_decide_auto_search_keeps_wiki_for_explicit_wikipedia_intent() -> None:
    service = SearchService(
        settings=_settings(),
        search_client=_FakeSearchClient([]),
        search_context=SearchContextStore(ttl_seconds=60),
        openrouter_client=_FakeOpenRouterClient(
            [
                json.dumps(
                    {
                        "should_search": True,
                        "mode": "wiki",
                        "query": "Ada Lovelace",
                        "reason": "encyclopedic",
                    }
                )
            ]
        ),
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200))
        ),
    )

    decision = await service.decide_auto_search(
        "Use Wikipedia and summarize Ada Lovelace."
    )

    assert decision.mode == "wiki"


@pytest.mark.anyio
async def test_decide_auto_search_logs_parse_failure_when_debug_enabled(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = SearchService(
        settings=replace(_settings(), bot_search_debug_logging=True),
        search_client=_FakeSearchClient([]),
        search_context=SearchContextStore(ttl_seconds=60),
        openrouter_client=_FakeOpenRouterClient(["not json"]),
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200))
        ),
    )
    caplog.set_level(logging.INFO, logger="signal_bot_orx.search_service")

    decision = await service.decide_auto_search("who is brogan woodman?")

    assert decision == SearchRouteDecision(False, "search", "")
    assert any(
        "search_debug event=router_fallback" in record.getMessage()
        and "reason_code=json_parse_failed" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.anyio
async def test_decide_auto_search_logs_router_decision_when_debug_enabled(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = SearchService(
        settings=replace(_settings(), bot_search_debug_logging=True),
        search_client=_FakeSearchClient([]),
        search_context=SearchContextStore(ttl_seconds=60),
        openrouter_client=_FakeOpenRouterClient(
            [
                json.dumps(
                    {
                        "should_search": True,
                        "mode": "news",
                        "query": "openrouter this week",
                        "reason": "current_events",
                    }
                )
            ]
        ),
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200))
        ),
    )
    caplog.set_level(logging.INFO, logger="signal_bot_orx.search_service")

    decision = await service.decide_auto_search(
        "what happened with openrouter this week?"
    )

    assert decision.mode == "news"
    assert any(
        "search_debug event=router_decision" in record.getMessage()
        and "mode=news" in record.getMessage()
        and "query_len=20" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.anyio
async def test_decide_auto_search_logs_no_search_decision_when_debug_enabled(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = SearchService(
        settings=replace(_settings(), bot_search_debug_logging=True),
        search_client=_FakeSearchClient([]),
        search_context=SearchContextStore(ttl_seconds=60),
        openrouter_client=_FakeOpenRouterClient(
            [
                json.dumps(
                    {
                        "should_search": False,
                        "mode": "search",
                        "query": "",
                        "reason": "small_talk",
                    }
                )
            ]
        ),
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200))
        ),
    )
    caplog.set_level(logging.INFO, logger="signal_bot_orx.search_service")

    decision = await service.decide_auto_search("lol nice one")

    assert decision == SearchRouteDecision(
        should_search=False,
        mode="search",
        query="",
        reason="small_talk",
    )
    assert any(
        "search_debug event=router_decision" in record.getMessage()
        and "reason_code=router_no_search" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.anyio
async def test_resolve_followup_prompt_resolves_ambiguous_pronoun() -> None:
    fake_openrouter = _FakeOpenRouterClient(
        [
            json.dumps(
                {
                    "can_resolve": True,
                    "resolved_prompt": "what is nick land up to now",
                    "entity": "Nick Land",
                    "confidence": 0.92,
                    "reason": "entity_match_recent_turns",
                }
            )
        ]
    )
    service = SearchService(
        settings=_settings(),
        search_client=_FakeSearchClient([]),
        search_context=SearchContextStore(ttl_seconds=60),
        openrouter_client=fake_openrouter,
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200))
        ),
    )

    decision = await service.resolve_followup_prompt(
        prompt="what's he up to now",
        history_context=[
            {"role": "user", "content": "tell me bout nick land"},
            {"role": "assistant", "content": "nick land is a british philosopher"},
        ],
        source_context=[
            {
                "mode": "search",
                "title": "Nick Land - profile",
                "snippet": "British philosopher and writer",
            }
        ],
    )

    assert decision == FollowupResolutionDecision(
        resolved_prompt="what's Nick Land up to now",
        needs_clarification=False,
        clarification_text=None,
        reason="deterministic_subject",
        used_context=True,
        confidence=1.0,
        subject_hint="Nick Land",
    )
    assert fake_openrouter.seen_messages == []


@pytest.mark.anyio
async def test_resolve_followup_prompt_clarifies_without_context() -> None:
    fake_openrouter = _FakeOpenRouterClient(["unused"])
    service = SearchService(
        settings=_settings(),
        search_client=_FakeSearchClient([]),
        search_context=SearchContextStore(ttl_seconds=60),
        openrouter_client=fake_openrouter,
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200))
        ),
    )

    decision = await service.resolve_followup_prompt(
        prompt="what's he up to now",
        history_context=[],
        source_context=[],
    )

    assert decision.needs_clarification is True
    assert decision.clarification_text == "Who are you referring to?"
    assert decision.reason == "no_context"
    assert fake_openrouter.seen_messages == []


@pytest.mark.anyio
async def test_resolve_followup_prompt_passthrough_for_non_followup() -> None:
    fake_openrouter = _FakeOpenRouterClient(["unused"])
    service = SearchService(
        settings=_settings(),
        search_client=_FakeSearchClient([]),
        search_context=SearchContextStore(ttl_seconds=60),
        openrouter_client=fake_openrouter,
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200))
        ),
    )

    decision = await service.resolve_followup_prompt(
        prompt="what happened with openrouter this week?",
        history_context=[
            {"role": "user", "content": "older"},
            {"role": "assistant", "content": "answer"},
        ],
        source_context=[
            {"mode": "search", "title": "OpenRouter", "snippet": "updates"},
        ],
    )

    assert decision.needs_clarification is False
    assert decision.resolved_prompt == "what happened with openrouter this week?"
    assert decision.reason == "not_followup"
    assert decision.confidence == 1.0
    assert decision.subject_hint is None
    assert fake_openrouter.seen_messages == []


@pytest.mark.anyio
async def test_resolve_followup_prompt_clarifies_on_malformed_json() -> None:
    service = SearchService(
        settings=_settings(),
        search_client=_FakeSearchClient([]),
        search_context=SearchContextStore(ttl_seconds=60),
        openrouter_client=_FakeOpenRouterClient(["bad json"]),
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200))
        ),
    )

    decision = await service.resolve_followup_prompt(
        prompt="what's he up to now",
        history_context=[
            {"role": "user", "content": "who is nick land"},
            {"role": "assistant", "content": "nick land is a philosopher"},
            {"role": "user", "content": "who is deleuze"},
            {"role": "assistant", "content": "deleuze is a philosopher"},
        ],
        source_context=[],
    )

    assert decision.needs_clarification is True
    assert decision.reason == "resolver_json_parse_failed"


@pytest.mark.anyio
async def test_resolve_followup_prompt_deterministic_subject_preserves_qualifier() -> (
    None
):
    fake_openrouter = _FakeOpenRouterClient(["unused"])
    service = SearchService(
        settings=_settings(),
        search_client=_FakeSearchClient([]),
        search_context=SearchContextStore(ttl_seconds=60),
        openrouter_client=fake_openrouter,
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200))
        ),
    )

    decision = await service.resolve_followup_prompt(
        prompt="who is he in islam",
        history_context=[
            {"role": "user", "content": "who is god"},
            {"role": "assistant", "content": "god is the supreme being"},
        ],
        source_context=[],
    )

    assert decision.needs_clarification is False
    assert decision.resolved_prompt == "who is god in islam"
    assert decision.reason == "deterministic_subject"
    assert decision.subject_hint == "god"
    assert fake_openrouter.seen_messages == []


@pytest.mark.anyio
async def test_resolve_followup_prompt_clarifies_with_multiple_subject_candidates() -> (
    None
):
    service = SearchService(
        settings=_settings(),
        search_client=_FakeSearchClient([]),
        search_context=SearchContextStore(ttl_seconds=60),
        openrouter_client=_FakeOpenRouterClient(
            [
                json.dumps(
                    {
                        "can_resolve": False,
                        "resolved_prompt": "",
                        "entity": "",
                        "confidence": 0.2,
                        "reason": "ambiguous_subject",
                    }
                )
            ]
        ),
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200))
        ),
    )

    decision = await service.resolve_followup_prompt(
        prompt="what is he up to now",
        history_context=[
            {"role": "user", "content": "who is nick land"},
            {"role": "assistant", "content": "nick land is a philosopher"},
            {"role": "user", "content": "who is deleuze"},
            {"role": "assistant", "content": "deleuze is a philosopher"},
        ],
        source_context=[],
    )

    assert decision.needs_clarification is True
    assert decision.reason == "ambiguous_subject"


@pytest.mark.anyio
async def test_resolve_pending_followup_reply_applies_subject_to_template() -> None:
    service = SearchService(
        settings=_settings(),
        search_client=_FakeSearchClient([]),
        search_context=SearchContextStore(ttl_seconds=60),
        openrouter_client=_FakeOpenRouterClient(["unused"]),
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200))
        ),
    )

    decision = await service.resolve_pending_followup_reply(
        reply_prompt="god",
        pending_state=PendingFollowupState(
            original_prompt="who is he in islam",
            template_prompt="who is {subject} in islam",
            reason="no_context",
            created_at=0.0,
            attempts=0,
        ),
        history_context=[],
        source_context=[],
    )

    assert decision.needs_clarification is False
    assert decision.resolved_prompt == "who is god in islam"
    assert decision.reason == "pending_reply_deterministic"
    assert decision.subject_hint == "god"


@pytest.mark.anyio
async def test_resolve_followup_prompt_logs_debug_reason_codes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_openrouter = _FakeOpenRouterClient(
        [
            json.dumps(
                {
                    "can_resolve": True,
                    "resolved_prompt": "what is nick land up to now",
                    "entity": "Nick Land",
                    "confidence": 0.92,
                    "reason": "entity_match_recent_turns",
                }
            )
        ]
    )
    service = SearchService(
        settings=replace(_settings(), bot_search_debug_logging=True),
        search_client=_FakeSearchClient([]),
        search_context=SearchContextStore(ttl_seconds=60),
        openrouter_client=fake_openrouter,
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200))
        ),
    )
    caplog.set_level(logging.INFO, logger="signal_bot_orx.search_service")

    await service.resolve_followup_prompt(
        prompt="what's he up to now",
        history_context=[
            {"role": "user", "content": "tell me bout nick land"},
            {"role": "assistant", "content": "nick land is a british philosopher"},
        ],
        source_context=[{"mode": "search", "title": "Nick Land", "snippet": ""}],
    )

    assert any(
        "search_debug event=followup_resolution_detected" in record.getMessage()
        for record in caplog.records
    )
    assert any(
        "search_debug event=followup_resolution_resolved" in record.getMessage()
        and "reason_code=deterministic_subject" in record.getMessage()
        and "confidence_bucket=high" in record.getMessage()
        for record in caplog.records
    )
    assert fake_openrouter.seen_messages == []


@pytest.mark.anyio
async def test_summarize_search_stores_sources() -> None:
    results = [
        SearchResult(
            mode="search",
            title="OpenRouter docs",
            url="https://openrouter.ai/docs",
            snippet="docs",
        )
    ]
    service = SearchService(
        settings=_settings(),
        search_client=_FakeSearchClient(results),
        search_context=SearchContextStore(ttl_seconds=60),
        openrouter_client=_FakeOpenRouterClient(["OpenRouter released updates."]),
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200))
        ),
    )

    summary = await service.summarize_search(
        conversation_key="dm:+15550002222",
        mode="search",
        query="openrouter updates",
    )
    source_text = service.source_reply(
        conversation_key="dm:+15550002222",
        claim="openrouter",
    )

    assert "OpenRouter released updates." in summary
    assert "https://openrouter.ai/docs" in source_text


@pytest.mark.anyio
async def test_summarize_search_includes_response_style_instruction() -> None:
    results = [
        SearchResult(
            mode="search",
            title="Brogan profile",
            url="https://example.com/brogan",
            snippet="creator profile",
        )
    ]
    fake_openrouter = _FakeOpenRouterClient(["One short sentence."])
    service = SearchService(
        settings=_settings(),
        search_client=_FakeSearchClient(results),
        search_context=SearchContextStore(ttl_seconds=60),
        openrouter_client=fake_openrouter,
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200))
        ),
    )

    await service.summarize_search(
        conversation_key="dm:+15550002222",
        mode="search",
        query="brogan woodman",
        user_request="Who is Brogan Woodman in one short sentence?",
    )

    payload = fake_openrouter.seen_messages[0][1]["content"]
    assert "response_style_instruction: Reply in one short sentence." in payload


@pytest.mark.anyio
async def test_summarize_search_persona_enabled_includes_core_prompt() -> None:
    results = [
        SearchResult(
            mode="search",
            title="Result title",
            url="https://example.com",
            snippet="snippet",
        )
    ]
    settings = replace(_settings(), bot_search_persona_enabled=True)
    fake_openrouter = _FakeOpenRouterClient(["summary"])
    service = SearchService(
        settings=settings,
        search_client=_FakeSearchClient(results),
        search_context=SearchContextStore(ttl_seconds=60),
        openrouter_client=fake_openrouter,
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200))
        ),
    )

    await service.summarize_search(
        conversation_key="dm:+15550002222",
        mode="search",
        query="test query",
    )

    system_prompt = fake_openrouter.seen_messages[0][0]["content"]
    assert "CORE_PROMPT_FOR_TEST" in system_prompt
    assert "Search-response constraints:" in system_prompt
    assert "Do not invent facts or citations." in system_prompt


@pytest.mark.anyio
async def test_summarize_search_persona_enabled_matches_auto_and_command_paths() -> (
    None
):
    results = [
        SearchResult(
            mode="search",
            title="Result title",
            url="https://example.com",
            snippet="snippet",
        )
    ]
    fake_openrouter = _FakeOpenRouterClient(["summary-one", "summary-two"])
    service = SearchService(
        settings=replace(_settings(), bot_search_persona_enabled=True),
        search_client=_FakeSearchClient(results),
        search_context=SearchContextStore(ttl_seconds=60),
        openrouter_client=fake_openrouter,
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200))
        ),
    )

    await service.summarize_search(
        conversation_key="dm:+15550002222",
        mode="search",
        query="brogan woodman",
        user_request=None,
    )
    await service.summarize_search(
        conversation_key="dm:+15550002222",
        mode="search",
        query="brogan woodman",
        user_request="who is brogan woodman?",
    )

    first_system_prompt = fake_openrouter.seen_messages[0][0]["content"]
    second_system_prompt = fake_openrouter.seen_messages[1][0]["content"]
    assert first_system_prompt == second_system_prompt
    assert "CORE_PROMPT_FOR_TEST" in first_system_prompt


@pytest.mark.anyio
async def test_summarize_search_persona_disabled_uses_overlay_only() -> None:
    results = [
        SearchResult(
            mode="search",
            title="Result title",
            url="https://example.com",
            snippet="snippet",
        )
    ]
    fake_openrouter = _FakeOpenRouterClient(["summary"])
    service = SearchService(
        settings=_settings(),
        search_client=_FakeSearchClient(results),
        search_context=SearchContextStore(ttl_seconds=60),
        openrouter_client=fake_openrouter,
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200))
        ),
    )

    await service.summarize_search(
        conversation_key="dm:+15550002222",
        mode="search",
        query="test query",
    )

    system_prompt = fake_openrouter.seen_messages[0][0]["content"]
    assert "CORE_PROMPT_FOR_TEST" not in system_prompt
    assert "Do not invent facts or citations." in system_prompt


@pytest.mark.anyio
async def test_summarize_search_includes_recent_history_when_passed() -> None:
    results = [
        SearchResult(
            mode="search",
            title="Result title",
            url="https://example.com",
            snippet="snippet",
        )
    ]
    fake_openrouter = _FakeOpenRouterClient(["summary"])
    service = SearchService(
        settings=_settings(),
        search_client=_FakeSearchClient(results),
        search_context=SearchContextStore(ttl_seconds=60),
        openrouter_client=fake_openrouter,
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200))
        ),
    )

    await service.summarize_search(
        conversation_key="dm:+15550002222",
        mode="search",
        query="test query",
        history_context=[
            {"role": "user", "content": "older question"},
            {"role": "assistant", "content": "older answer"},
        ],
    )

    payload = fake_openrouter.seen_messages[0][1]["content"]
    assert "recent_history:" in payload


@pytest.mark.anyio
async def test_summarize_search_omits_recent_history_when_not_passed() -> None:
    results = [
        SearchResult(
            mode="search",
            title="Result title",
            url="https://example.com",
            snippet="snippet",
        )
    ]
    fake_openrouter = _FakeOpenRouterClient(["summary"])
    service = SearchService(
        settings=_settings(),
        search_client=_FakeSearchClient(results),
        search_context=SearchContextStore(ttl_seconds=60),
        openrouter_client=fake_openrouter,
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200))
        ),
    )

    await service.summarize_search(
        conversation_key="dm:+15550002222",
        mode="search",
        query="test query",
    )

    payload = fake_openrouter.seen_messages[0][1]["content"]
    assert "recent_history:" not in payload


@pytest.mark.anyio
async def test_summarize_search_logs_summary_request_when_debug_enabled(
    caplog: pytest.LogCaptureFixture,
) -> None:
    results = [
        SearchResult(
            mode="search",
            title="Result title",
            url="https://example.com",
            snippet="snippet",
        )
    ]
    fake_openrouter = _FakeOpenRouterClient(["summary"])
    service = SearchService(
        settings=replace(
            _settings(),
            bot_search_debug_logging=True,
            bot_search_persona_enabled=True,
        ),
        search_client=_FakeSearchClient(results),
        search_context=SearchContextStore(ttl_seconds=60),
        openrouter_client=fake_openrouter,
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200))
        ),
    )
    caplog.set_level(logging.INFO, logger="signal_bot_orx.search_service")

    await service.summarize_search(
        conversation_key="dm:+15550002222",
        mode="search",
        query="test query",
        history_context=[
            {"role": "user", "content": "older question"},
            {"role": "assistant", "content": "older answer"},
        ],
    )

    assert any(
        "search_debug event=summary_request" in record.getMessage()
        and "mode=search" in record.getMessage()
        and "result_count=1" in record.getMessage()
        and "history_included=True" in record.getMessage()
        and "persona_enabled=True" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.anyio
async def test_search_image_downloads_first_valid_image() -> None:
    results = [
        SearchResult(
            mode="images",
            title="Fox",
            url="https://source.example/fox",
            snippet="",
            image_url="https://img.example/fox.jpg",
        )
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://img.example/fox.jpg"
        return httpx.Response(
            200,
            content=b"image-bytes",
            headers={"content-type": "image/jpeg"},
        )

    service = SearchService(
        settings=_settings(),
        search_client=_FakeSearchClient(results),
        search_context=SearchContextStore(ttl_seconds=60),
        openrouter_client=_FakeOpenRouterClient([]),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    image_bytes, content_type = await service.search_image(
        conversation_key="dm:+15550002222",
        query="fox",
    )

    assert image_bytes == b"image-bytes"
    assert content_type == "image/jpeg"


@pytest.mark.anyio
async def test_video_list_reply_stores_pending_selection() -> None:
    results = [
        SearchResult(
            mode="videos",
            title="Video one",
            url="https://youtube.com/watch?v=one",
            snippet="",
            image_url="https://img.example/one.jpg",
        ),
        SearchResult(
            mode="videos",
            title="Video two",
            url="https://youtube.com/watch?v=two",
            snippet="",
            image_url="https://img.example/two.jpg",
        ),
    ]
    context = SearchContextStore(ttl_seconds=60)
    service = SearchService(
        settings=_settings(),
        search_client=_FakeSearchClient(results),
        search_context=context,
        openrouter_client=_FakeOpenRouterClient([]),
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200))
        ),
    )

    reply = await service.video_list_reply(
        conversation_key="dm:+15550002222",
        query="nick land interview",
    )
    pending = service.get_pending_video_selection_state(
        conversation_key="dm:+15550002222",
    )

    assert "Videos:" in reply
    assert "1. Video one" in reply
    assert pending is not None
    assert len(pending.results) == 2


@pytest.mark.anyio
async def test_resolve_video_selection_downloads_thumbnail() -> None:
    results = [
        SearchResult(
            mode="videos",
            title="Video one",
            url="https://youtube.com/watch?v=one",
            snippet="",
            image_url="https://img.example/one.jpg",
        )
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://img.example/one.jpg"
        return httpx.Response(
            200,
            content=b"thumb-bytes",
            headers={"content-type": "image/jpeg"},
        )

    service = SearchService(
        settings=_settings(),
        search_client=_FakeSearchClient(results),
        search_context=SearchContextStore(ttl_seconds=60),
        openrouter_client=_FakeOpenRouterClient([]),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    await service.video_list_reply(
        conversation_key="dm:+15550002222",
        query="nick land interview",
    )
    image_bytes, content_type, url, title = await service.resolve_video_selection(
        conversation_key="dm:+15550002222",
        selection_number=1,
    )

    assert image_bytes == b"thumb-bytes"
    assert content_type == "image/jpeg"
    assert url == "https://youtube.com/watch?v=one"
    assert title == "Video one"


@pytest.mark.anyio
async def test_resolve_video_selection_rejects_out_of_range() -> None:
    results = [
        SearchResult(
            mode="videos",
            title="Video one",
            url="https://youtube.com/watch?v=one",
            snippet="",
            image_url="https://img.example/one.jpg",
        )
    ]
    service = SearchService(
        settings=_settings(),
        search_client=_FakeSearchClient(results),
        search_context=SearchContextStore(ttl_seconds=60),
        openrouter_client=_FakeOpenRouterClient([]),
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200))
        ),
    )
    await service.video_list_reply(
        conversation_key="dm:+15550002222",
        query="nick land interview",
    )

    with pytest.raises(SearchError) as exc:
        await service.resolve_video_selection(
            conversation_key="dm:+15550002222",
            selection_number=2,
        )

    assert "between 1 and 1" in str(exc.value)


@pytest.mark.anyio
async def test_resolve_video_selection_returns_text_fallback_when_no_thumbnail() -> (
    None
):
    results = [
        SearchResult(
            mode="videos",
            title="Video one",
            url="https://youtube.com/watch?v=one",
            snippet="",
            image_url=None,
        )
    ]
    service = SearchService(
        settings=_settings(),
        search_client=_FakeSearchClient(results),
        search_context=SearchContextStore(ttl_seconds=60),
        openrouter_client=_FakeOpenRouterClient([]),
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200))
        ),
    )
    await service.video_list_reply(
        conversation_key="dm:+15550002222",
        query="nick land interview",
    )

    image_bytes, content_type, url, title = await service.resolve_video_selection(
        conversation_key="dm:+15550002222",
        selection_number=1,
    )

    assert image_bytes is None
    assert content_type is None
    assert url == "https://youtube.com/watch?v=one"
    assert title == "Video one"
