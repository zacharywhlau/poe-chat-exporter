from __future__ import annotations

import re

from poe_bulk_export.models import Message

_THINKING_HEADER = re.compile(
    r"(?is)^\s*(?:\*{0,2}Thinking\.{0,3}\*{0,2})\s*$"
)


def strip_thinking(text: str) -> str:
    """Remove leading thinking / chain-of-thought sections from bot text."""
    if not text:
        return ""
    lines = text.splitlines()
    i = 0
    # Skip blank lines
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines):
        return ""

    # Pattern A: "*Thinking...*" / "Thinking" header, then > quoted notes
    if _THINKING_HEADER.match(lines[i]):
        i += 1
        while i < len(lines) and not lines[i].strip():
            i += 1
        while i < len(lines) and lines[i].lstrip().startswith(">"):
            i += 1
        while i < len(lines) and not lines[i].strip():
            i += 1
        return "\n".join(lines[i:]).lstrip()

    # Pattern B: prose that starts with "I'm thinking about..." until a blank
    # line followed by the real answer (Here's / # / ```).
    if re.match(r"(?is)^I'm thinking about\b", lines[i].strip()):
        for j in range(i + 1, len(lines) - 1):
            if not lines[j].strip():
                nxt = lines[j + 1].lstrip()
                if nxt.startswith(("Here's", "#", "```", "**")):
                    return "\n".join(lines[j + 1 :]).lstrip()
        # No clear answer boundary — keep original
        return text.lstrip()

    return text.lstrip()


def is_thinking_only(text: str) -> bool:
    """True if the message is only a thinking UI fragment / draft."""
    t = (text or "").strip()
    if not t:
        return True
    if _THINKING_HEADER.match(t):
        return True
    # Header + only short blockquotes / no real answer body
    stripped = strip_thinking(t)
    if not stripped and re.match(r"(?is)^\*?Thinking", t):
        return True
    if (
        re.match(r"(?is)^\*?Thinking", t)
        and "```" not in t
        and len(t) < 120
        and t.lower().count("\n") < 3
    ):
        return True
    return False


def normalize_author(author: str, bot_name: str = "", bot_handle: str = "") -> str:
    """Map Poe authors to human | bot (stable for rendering)."""
    a = (author or "").strip()
    low = a.lower()
    if low in {"human", "user", "you"}:
        return "human"
    if low in {"bot", "assistant"}:
        return "bot"
    if low in {"unknown", "", "chat_break", "chatbreak"}:
        return "unknown"

    handles = {
        bot_name.lower().replace(" ", "").replace("-", "_"),
        bot_handle.lower().replace(" ", "").replace("-", "_"),
        bot_name.lower(),
        bot_handle.lower(),
    }
    handles.discard("")
    cand = low.replace(" ", "").replace("-", "_")
    if a in handles or low in handles or cand in handles:
        return "bot"
    # Poe often uses snake_case bot nicknames as author
    if "_" in low or low.replace("-", "").isalnum():
        if low not in {"human", "user"}:
            # Heuristic: non-human authors from API are bots
            return "bot"
    return a


def cleanup_messages(
    messages: list[Message],
    *,
    include_thinking: bool = False,
    bot_name: str = "",
    bot_handle: str = "",
) -> list[Message]:
    """Normalize speakers, optionally strip thinking, drop empty leftovers."""
    out: list[Message] = []
    for msg in messages:
        author = normalize_author(msg.author, bot_name, bot_handle)
        text = msg.text or ""
        if not include_thinking:
            if is_thinking_only(text) and author != "human":
                continue
            if author != "human":
                text = strip_thinking(text)
        text = text.strip()
        if not text:
            continue
        out.append(
            Message(
                author=author,
                text=text,
                message_id=msg.message_id,
                content_type=msg.content_type,
                creation_time_us=msg.creation_time_us,
                attachments=list(msg.attachments),
                source=msg.source,
            )
        )
    return out
