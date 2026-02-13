from __future__ import annotations

import time


class DedupeCache:
    def __init__(self, ttl_seconds: int = 300) -> None:
        self._ttl_seconds = ttl_seconds
        self._seen: dict[str, float] = {}

    def mark_once(self, key: str) -> bool:
        now = time.monotonic()
        self._purge(now)

        expires_at = self._seen.get(key)
        if expires_at and expires_at > now:
            return False

        self._seen[key] = now + self._ttl_seconds
        return True

    def _purge(self, now: float) -> None:
        expired = [key for key, expires_at in self._seen.items() if expires_at <= now]
        for key in expired:
            del self._seen[key]
