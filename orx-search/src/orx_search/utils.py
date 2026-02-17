"""Utility functions ported from ddgs."""

from __future__ import annotations

import re
import unicodedata
from contextlib import suppress
from datetime import UTC, datetime
from html import unescape
from urllib.parse import unquote

_REGEX_STRIP_TAGS = re.compile("<.*?>")


def extract_vqd(html_bytes: bytes, query: str) -> str:
    """Extract vqd token from DuckDuckGo HTML response bytes."""
    for c1, c1_len, c2 in (
        (b'vqd="', 5, b'"'),
        (b"vqd=", 4, b"&"),
        (b"vqd='", 5, b"'"),
    ):
        with suppress(ValueError):
            start = html_bytes.index(c1) + c1_len
            end = html_bytes.index(c2, start)
            return html_bytes[start:end].decode()

    msg = f"extract_vqd() {query=} Could not extract vqd."
    raise RuntimeError(msg)


def normalize_url(url: str) -> str:
    """Unquote URL and replace spaces with '+'."""
    return unquote(url).replace(" ", "+") if url else ""


def normalize_text(raw: str) -> str:
    """Strip HTML tags, unescape entities, normalize Unicode, collapse whitespace."""
    if not raw:
        return ""

    text = _REGEX_STRIP_TAGS.sub("", raw)
    text = unescape(text)
    text = unicodedata.normalize("NFC", text)

    c_to_none = {
        ord(ch): None for ch in set(text) if unicodedata.category(ch)[0] == "C"
    }
    if c_to_none:
        text = text.translate(c_to_none)

    return " ".join(text.split())


def normalize_date(date: int | str) -> str:
    """Normalize date from integer timestamp to ISO format if applicable."""
    return (
        datetime.fromtimestamp(date, UTC).isoformat() if isinstance(date, int) else date
    )
