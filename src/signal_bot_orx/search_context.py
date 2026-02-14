from __future__ import annotations

import time
from dataclasses import dataclass

from signal_bot_orx.search_client import SearchMode, SearchResult


@dataclass(frozen=True)
class SourceRecord:
    claim_key: str
    title: str
    url: str
    snippet: str
    mode: SearchMode
    created_at: float


@dataclass(frozen=True)
class PendingFollowupState:
    original_prompt: str
    template_prompt: str
    reason: str
    created_at: float
    attempts: int


class SearchContextStore:
    def __init__(
        self, *, ttl_seconds: int, max_records_per_conversation: int = 40
    ) -> None:
        self._ttl_seconds = max(1, ttl_seconds)
        self._max_records_per_conversation = max(1, max_records_per_conversation)
        self._records: dict[str, list[SourceRecord]] = {}
        self._pending_followups: dict[str, PendingFollowupState] = {}

    def remember_results(
        self,
        conversation_key: str,
        *,
        mode: SearchMode,
        results: list[SearchResult],
    ) -> None:
        now = time.monotonic()
        self._purge(now)

        if not results:
            return

        bucket = self._records.setdefault(conversation_key, [])
        for result in results:
            claim_key = _claim_key(result)
            bucket.append(
                SourceRecord(
                    claim_key=claim_key,
                    title=result.title,
                    url=result.url,
                    snippet=result.snippet,
                    mode=mode,
                    created_at=now,
                )
            )

        if len(bucket) > self._max_records_per_conversation:
            self._records[conversation_key] = bucket[
                -self._max_records_per_conversation :
            ]

    def find_sources(
        self,
        conversation_key: str,
        claim: str,
        *,
        limit: int = 3,
    ) -> list[SourceRecord]:
        now = time.monotonic()
        self._purge(now)

        records = self._records.get(conversation_key, [])
        if not records:
            return []

        normalized_claim = _normalize(claim)
        if not normalized_claim:
            # Return most recent unique URLs.
            return _dedupe_urls(reversed(records), limit)

        scored: list[tuple[int, SourceRecord]] = []
        claim_tokens = set(normalized_claim.split())
        for record in records:
            text = _normalize(f"{record.title} {record.snippet} {record.claim_key}")
            score = 0
            if normalized_claim in text:
                score += 100
            overlap = len(claim_tokens & set(text.split()))
            score += overlap
            if score > 0:
                scored.append((score, record))

        scored.sort(key=lambda pair: (pair[0], pair[1].created_at), reverse=True)
        return _dedupe_urls((record for _, record in scored), limit)

    def recent_records(
        self,
        conversation_key: str,
        *,
        limit: int = 6,
    ) -> list[SourceRecord]:
        now = time.monotonic()
        self._purge(now)

        records = self._records.get(conversation_key, [])
        if not records:
            return []

        bounded_limit = max(1, limit)
        return list(reversed(records[-bounded_limit:]))

    def set_pending_followup(
        self,
        conversation_key: str,
        *,
        original_prompt: str,
        template_prompt: str,
        reason: str,
    ) -> None:
        now = time.monotonic()
        self._purge(now)
        self._pending_followups[conversation_key] = PendingFollowupState(
            original_prompt=original_prompt,
            template_prompt=template_prompt,
            reason=reason,
            created_at=now,
            attempts=0,
        )

    def get_pending_followup(
        self,
        conversation_key: str,
    ) -> PendingFollowupState | None:
        now = time.monotonic()
        self._purge(now)
        return self._pending_followups.get(conversation_key)

    def clear_pending_followup(self, conversation_key: str) -> None:
        self._pending_followups.pop(conversation_key, None)

    def bump_pending_attempt(self, conversation_key: str) -> int:
        now = time.monotonic()
        self._purge(now)
        existing = self._pending_followups.get(conversation_key)
        if existing is None:
            return 0
        updated = PendingFollowupState(
            original_prompt=existing.original_prompt,
            template_prompt=existing.template_prompt,
            reason=existing.reason,
            created_at=existing.created_at,
            attempts=existing.attempts + 1,
        )
        self._pending_followups[conversation_key] = updated
        return updated.attempts

    def _purge(self, now: float) -> None:
        expired_keys: list[str] = []
        for conversation_key, records in self._records.items():
            kept = [
                record
                for record in records
                if record.created_at + self._ttl_seconds > now
            ]
            if kept:
                self._records[conversation_key] = kept
            else:
                expired_keys.append(conversation_key)

        for conversation_key in expired_keys:
            del self._records[conversation_key]

        pending_expired = [
            key
            for key, pending in self._pending_followups.items()
            if pending.created_at + self._ttl_seconds <= now
        ]
        for key in pending_expired:
            del self._pending_followups[key]


def _claim_key(result: SearchResult) -> str:
    snippet = result.snippet.strip()
    if snippet:
        return snippet[:160]
    return result.title[:160]


def _normalize(text: str) -> str:
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in text).split())


def _dedupe_urls(records: object, limit: int) -> list[SourceRecord]:
    deduped: list[SourceRecord] = []
    seen_urls: set[str] = set()
    for record in records:  # type: ignore[assignment]
        if not isinstance(record, SourceRecord):
            continue
        if record.url in seen_urls:
            continue
        seen_urls.add(record.url)
        deduped.append(record)
        if len(deduped) >= limit:
            break
    return deduped
