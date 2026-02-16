from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from signal_bot_orx.parsing import first_non_empty_str


@dataclass(frozen=True)
class ResolvedGroupRecipients:
    recipients: tuple[str, ...]
    cache_refreshed: bool


class GroupResolver:
    def __init__(
        self,
        *,
        base_url: str,
        sender_number: str,
        http_client: httpx.AsyncClient,
        refresh_ttl_seconds: int = 300,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._sender_number = sender_number
        self._http_client = http_client
        self._refresh_ttl_seconds = refresh_ttl_seconds
        self._alias_to_canonical: dict[str, str] = {}
        self._last_refresh_monotonic: float | None = None

    async def resolve(self, group_id: str) -> ResolvedGroupRecipients:
        resolved = self._lookup(group_id)
        if resolved is not None:
            return ResolvedGroupRecipients(
                recipients=_merge_candidates(
                    resolved,
                    _compat_group_recipients(group_id),
                ),
                cache_refreshed=False,
            )

        refreshed = await self._refresh_alias_cache()
        if refreshed:
            resolved = self._lookup(group_id)
            if resolved is not None:
                return ResolvedGroupRecipients(
                    recipients=_merge_candidates(
                        resolved,
                        _compat_group_recipients(group_id),
                    ),
                    cache_refreshed=True,
                )

        return ResolvedGroupRecipients(
            recipients=_compat_group_recipients(group_id),
            cache_refreshed=refreshed,
        )

    def _lookup(self, group_id: str) -> str | None:
        for alias in _alias_variants(group_id):
            canonical = self._alias_to_canonical.get(alias)
            if canonical:
                return canonical
        return None

    async def _refresh_alias_cache(self) -> bool:
        now = time.monotonic()
        is_fresh = (
            self._last_refresh_monotonic is not None
            and now - self._last_refresh_monotonic < self._refresh_ttl_seconds
        )
        # Prefer fewer network calls: cache misses do not force refresh while TTL is fresh.
        # Tradeoff: newly created aliases may take up to TTL to appear in cache.
        if is_fresh:
            return False

        groups, refreshed = await self._fetch_groups()
        if refreshed:
            updated_aliases: dict[str, str] = {}
            for group in groups:
                canonical = _canonical_recipient_from_group(group)
                if canonical is None:
                    continue
                for alias in _group_aliases(group):
                    updated_aliases[alias] = canonical

            if updated_aliases:
                self._alias_to_canonical = updated_aliases

        self._last_refresh_monotonic = now
        return refreshed

    async def _fetch_groups(self) -> tuple[list[dict[str, Any]], bool]:
        sender_number = quote(self._sender_number, safe="")
        urls = (
            f"{self._base_url}/v1/groups/{sender_number}",
            f"{self._base_url}/v1/groups",
        )

        for url in urls:
            try:
                response = await self._http_client.get(url, timeout=30)
            except (httpx.TimeoutException, httpx.NetworkError):
                continue

            if response.status_code >= 400:
                continue

            try:
                payload = response.json()
            except ValueError:
                continue

            return _extract_group_records(payload), True

        return [], False


def _extract_group_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if not isinstance(payload, dict):
        return []

    for key in ("groups", "data", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    if any(
        isinstance(payload.get(key), str)
        for key in ("id", "groupId", "groupIdHex", "internal_id", "internalId")
    ):
        return [payload]

    return []


def _canonical_recipient_from_group(group: dict[str, Any]) -> str | None:
    explicit_id = first_non_empty_str(group, "id", "groupId", "groupIdHex")
    if explicit_id:
        normalized = explicit_id.strip()
        if normalized.startswith("group."):
            return normalized
        return _group_id_from_internal(normalized)

    internal_id = first_non_empty_str(group, "internal_id", "internalId")
    if internal_id:
        return _group_id_from_internal(internal_id)

    return None


def _group_aliases(group: dict[str, Any]) -> set[str]:
    aliases: set[str] = set()
    for key in ("id", "groupId", "groupIdHex", "internal_id", "internalId"):
        value = group.get(key)
        if isinstance(value, str) and value.strip():
            aliases.update(_alias_variants(value))
    return aliases


def _alias_variants(value: str) -> set[str]:
    normalized = value.strip()
    if not normalized:
        return set()

    variants: set[str] = {normalized}

    if normalized.startswith("group."):
        suffix = normalized.removeprefix("group.")
        variants.add(suffix)
        decoded_internal = _decode_group_suffix(suffix)
        if decoded_internal:
            variants.add(decoded_internal)
            variants.add(f"group.{decoded_internal}")
    else:
        variants.add(f"group.{normalized}")
        encoded = _encode_internal_id(normalized)
        variants.add(encoded)
        variants.add(f"group.{encoded}")

    # Keep lookup tolerant for legacy url-safe/padding-stripped variants,
    # but never use these rewrites as canonical send IDs.
    lookup_tolerant: set[str] = set()
    for candidate in variants:
        lookup_tolerant.update(_lookup_tolerant_forms(candidate))

    return lookup_tolerant


def _compat_group_recipients(group_id: str) -> tuple[str, ...]:
    normalized = group_id.strip()
    if not normalized:
        return ()

    deduped: list[str] = []

    if normalized.startswith("group."):
        suffix = normalized.removeprefix("group.")
        decoded_internal = _decode_group_suffix(suffix)

        for candidate in (
            normalized,
            suffix,
            f"group.{decoded_internal}" if decoded_internal else None,
            decoded_internal,
        ):
            if candidate and candidate not in deduped:
                deduped.append(candidate)

        return tuple(deduped)

    encoded_group_id = _group_id_from_internal(normalized)
    legacy_group_id = _legacy_group_id_from_internal(normalized)

    for candidate in (
        encoded_group_id,
        f"group.{normalized}",
        normalized,
        legacy_group_id,
    ):
        if candidate and candidate not in deduped:
            deduped.append(candidate)

    return tuple(deduped)


def _group_id_from_internal(internal_id: str) -> str:
    normalized = internal_id.strip()
    if normalized.startswith("group."):
        return normalized
    encoded = _encode_internal_id(normalized)
    return f"group.{encoded}"


def _legacy_group_id_from_internal(internal_id: str) -> str:
    normalized = internal_id.strip()
    if not normalized:
        return ""
    suffix = normalized.replace("+", "-").replace("/", "_").rstrip("=")
    return f"group.{suffix}"


def _encode_internal_id(internal_id: str) -> str:
    return base64.b64encode(internal_id.encode("utf-8")).decode("ascii")


def _decode_group_suffix(group_suffix: str) -> str | None:
    normalized = group_suffix.strip().replace("-", "+").replace("_", "/")
    if not normalized:
        return None

    padding = "=" * (-len(normalized) % 4)
    try:
        decoded = base64.b64decode(normalized + padding, validate=False)
        decoded_text = decoded.decode("utf-8").strip()
    except (ValueError, UnicodeDecodeError):
        return None

    if not decoded_text:
        return None
    return decoded_text


def _lookup_tolerant_forms(value: str) -> set[str]:
    value = value.strip()
    if not value:
        return set()

    prefixed = value.startswith("group.")
    core = value.removeprefix("group.") if prefixed else value

    urlsafe = core.replace("+", "-").replace("/", "_")
    unpadded_core = core.rstrip("=")
    unpadded_urlsafe = urlsafe.rstrip("=")

    forms = {
        core,
        urlsafe,
        unpadded_core,
        unpadded_urlsafe,
    }

    with_prefix = {f"group.{item}" for item in forms if item}
    return forms | with_prefix


def _merge_candidates(primary: str, fallbacks: tuple[str, ...]) -> tuple[str, ...]:
    deduped: list[str] = []
    for candidate in (primary, *fallbacks):
        if candidate and candidate not in deduped:
            deduped.append(candidate)
    return tuple(deduped)
