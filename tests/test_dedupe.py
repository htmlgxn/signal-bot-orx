from __future__ import annotations

from signal_box_orx.dedupe import DedupeCache


def test_dedupe_accepts_first_and_rejects_duplicate() -> None:
    cache = DedupeCache(ttl_seconds=60)

    assert cache.mark_once("key-1") is True
    assert cache.mark_once("key-1") is False
    assert cache.mark_once("key-2") is True
