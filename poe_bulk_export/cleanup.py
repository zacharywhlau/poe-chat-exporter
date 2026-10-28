"""Light, exact post-processing of raw Poe message text.

Raw message text is already the markdown Poe stores, so nothing here guesses
at formatting. The only rewrite, and only when asked (``--strip-thinking``), is
removing the reasoning block that some bots put in front of their answer, and
only in its exact form::

    *Thinking...*

    > reasoning, quoted
    >
    > more reasoning

    The actual answer…
"""

from __future__ import annotations

import re
from dataclasses import replace

from poe_bulk_export.models import Message

_THINKING_HEADER = re.compile(r"^\s*(\*{1,2})Thinking(?:\.\.\.|…)\1\s*$")
_LEADING_BLANK_LINES = re.compile(r"\A(?:[ \t]*\r?\n)+")


def strip_thinking_block(text: str) -> str:
    """Drop a leading ``*Thinking...*`` header and the ``>`` quote block after it.

    Text is returned unchanged unless that exact shape is present and an answer
    follows it.
    """
    if not text:
        return text or ""
    lines = text.split("\n")
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines) or not _THINKING_HEADER.match(lines[i]):
        return text
    i += 1

    quoted = 0
    while i < len(lines):
        stripped = lines[i].lstrip()
        if stripped.startswith(">"):
            quoted += 1
            i += 1
            continue
        if not stripped:
            j = i
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines) and lines[j].lstrip().startswith(">"):
                i = j
                continue
        break

    answer = "\n".join(lines[i:])
    if not quoted or not answer.strip():
        return text
    return _LEADING_BLANK_LINES.sub("", answer)


def tidy_text(text: str) -> str:
    """Remove leading blank lines and trailing whitespace; keep everything else."""
    return _LEADING_BLANK_LINES.sub("", text or "").rstrip()


def cleanup_messages(
    messages: list[Message],
    *,
    strip_thinking: bool = False,
) -> list[Message]:
    """Trim the edges of each turn, drop empty turns and optionally strip thinking.

    Stripping applies to every turn that is not known to be human, so a message
    whose author could not be recognised is still stripped.
    """
    out: list[Message] = []
    for message in messages:
        text = message.text or ""
        if strip_thinking and message.author != "human":
            text = strip_thinking_block(text)
        text = tidy_text(text)
        if not text and not message.attachments and message.author != "chat_break":
            continue
        out.append(message if text == message.text else replace(message, text=text))
    return out
