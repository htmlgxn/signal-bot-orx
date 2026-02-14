from __future__ import annotations

import re
from itertools import pairwise
from pathlib import Path

from signal_bot_orx.chat_context import ChatTurn

_LOCAL_CHAT_PROMPT_PATH = Path(__file__).with_name("chat_system_prompt.md")
_DEFAULT_CHAT_PROMPT_PATH = Path(__file__).with_name("default_chat_system_prompt.md")


def _load_default_chat_system_prompt() -> str:
    for candidate in (_LOCAL_CHAT_PROMPT_PATH, _DEFAULT_CHAT_PROMPT_PATH):
        try:
            content = candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if content:
            return content
    return 'You are "@sigbot". Reply helpfully in plain text.'


DEFAULT_CHAT_SYSTEM_PROMPT = _load_default_chat_system_prompt()

_FENCE_RE = re.compile(r"```[a-zA-Z0-9_-]*\s*\n?(.*?)```", re.DOTALL)
_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_HEADER_RE = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_BULLET_RE = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
_BLOCKQUOTE_RE = re.compile(r"^\s*>\s?", re.MULTILINE)
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)|_(.+?)_")
_TRAILING_STAR_RE = re.compile(r"(?<=\w)\*(?=\s|$)")
_NUMBERED_ITEM_RE = re.compile(r"(?<!\d)(\d{1,2})\.\s+")


def build_chat_messages(
    *,
    system_prompt: str,
    history: tuple[ChatTurn, ...],
    prompt: str,
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for turn in history:
        role = getattr(turn, "role", None)
        content = getattr(turn, "content", None)
        if role in {"user", "assistant"} and isinstance(content, str):
            messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": prompt})
    return messages


def coerce_plain_text_reply(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        return ""

    cleaned = _FENCE_RE.sub(lambda match: match.group(1).strip(), cleaned)
    cleaned = _LINK_RE.sub(r"\1 (\2)", cleaned)
    cleaned = _INLINE_CODE_RE.sub(r"\1", cleaned)
    cleaned = _HEADER_RE.sub("", cleaned)
    cleaned = _BULLET_RE.sub("", cleaned)
    cleaned = _BLOCKQUOTE_RE.sub("", cleaned)
    cleaned = _BOLD_RE.sub(
        lambda match: match.group(1) or match.group(2) or "", cleaned
    )
    cleaned = _ITALIC_RE.sub(
        lambda match: match.group(1) or match.group(2) or "",
        cleaned,
    )
    cleaned = _TRAILING_STAR_RE.sub("", cleaned)
    cleaned = cleaned.replace("`", "")
    cleaned = _split_inline_numbered_list(cleaned)

    collapsed_lines: list[str] = []
    previous_blank = False
    for line in cleaned.splitlines():
        compact_line = " ".join(line.strip().split())
        if not compact_line:
            if not previous_blank:
                collapsed_lines.append("")
            previous_blank = True
            continue
        collapsed_lines.append(compact_line)
        previous_blank = False

    return "\n".join(collapsed_lines).strip()


def _split_inline_numbered_list(text: str) -> str:
    matches = list(_NUMBERED_ITEM_RE.finditer(text))
    if len(matches) < 2:
        return text

    numbers = [int(match.group(1)) for match in matches]
    if numbers[0] != 1:
        return text

    sequential_steps = sum(1 for prev, curr in pairwise(numbers) if curr == prev + 1)
    if sequential_steps < len(numbers) - 1:
        return text

    return re.sub(r"\s+((?:\d{1,2})\.\s+)", r"\n\1", text)
