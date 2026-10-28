"""Markdown rendering.

Both styles share one transcript body, the layout Poe's ``@export-chat`` bot
produces: a speaker line, a blank line, the raw message markdown, and a
``---`` rule between turns::

    User:

    How do I rebase?

    ---

    Claude-Fable-5:

    ## Rebasing
    …

``export-chat`` is exactly that body (no header, no trailing newline).
``archive`` adds YAML front matter and an invisible HTML comment with the time
and message id in front of each turn.
"""

from __future__ import annotations

from pathlib import Path

from poe_bulk_export import __version__
from poe_bulk_export.models import Chat, Message
from poe_bulk_export.util import epoch_us_to_iso_z, now_iso_z, yaml_escape
from poe_bulk_export.writer import chat_output_path, write_text_file

STYLES = ("archive", "export-chat")
TURN_SEPARATOR = "\n\n---\n\n"
CHAT_BREAK = "*— Context cleared —*"


def speaker_label(message: Message, chat: Chat) -> str:
    if message.author == "human":
        return "User"
    if message.author == "system":
        return "Poe"
    return message.author_name or chat.bot or "Bot"


def render_message_body(message: Message) -> str:
    """Message markdown plus any attachment not already linked in the text."""
    text = (message.text or "").rstrip()
    for att in message.attachments:
        if att.local_path and att.url and att.url in text:
            text = text.replace(att.url, att.local_path)

    parts = [text] if text else []
    haystack = text.lower()
    for att in message.attachments:
        target = att.local_path or att.url
        if not target:
            continue
        if target.lower() in haystack or (att.url and att.url.lower() in haystack):
            continue
        label = att.name or "attachment"
        parts.append(f"![{label}]({target})" if att.kind == "image" else f"[{label}]({target})")
    return "\n\n".join(parts)


def _turn_comment(message: Message) -> str | None:
    details = []
    when = epoch_us_to_iso_z(message.creation_time_us)
    if when:
        details.append(when)
    if message.message_id is not None:
        details.append(f"message {message.message_id}")
    return f"<!-- {' · '.join(details)} -->" if details else None


def render_turn(message: Message, chat: Chat, *, annotate: bool = False) -> str:
    if message.author == "chat_break":
        turn = CHAT_BREAK
    else:
        body = render_message_body(message)
        turn = f"{speaker_label(message, chat)}:"
        if body:
            turn += f"\n\n{body}"
    if annotate:
        comment = _turn_comment(message)
        if comment:
            turn = f"{comment}\n{turn}"
    return turn


def render_transcript(chat: Chat, *, annotate: bool = False) -> str:
    return TURN_SEPARATOR.join(render_turn(m, chat, annotate=annotate) for m in chat.messages)


def render_export_chat(chat: Chat) -> str:
    """Byte-for-byte the layout of ``@export-chat``."""
    return render_transcript(chat)


def _yaml_value(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return yaml_escape(str(value))


def front_matter(chat: Chat, *, exported_at: str | None = None) -> str:
    times = [m.creation_time_us for m in chat.messages if m.creation_time_us is not None]
    fields: list[tuple[str, object]] = [
        ("title", chat.title),
        ("bot", chat.bot),
        ("chat_code", chat.chat_code),
        ("chat_id", chat.chat_id),
        ("url", chat.url),
        ("created", epoch_us_to_iso_z(min(times)) if times else None),
        ("updated", epoch_us_to_iso_z(max(times)) if times else None),
        ("message_count", len(chat.messages)),
        ("complete", chat.complete),
        ("source", chat.source or "raw"),
        ("exported_at", exported_at or now_iso_z()),
        ("exporter", f"poe-bulk-export {__version__}"),
    ]
    lines = ["---", *(f"{key}: {_yaml_value(value)}" for key, value in fields), "---"]
    return "\n".join(lines) + "\n"


def render_archive(chat: Chat, *, exported_at: str | None = None) -> str:
    return f"{front_matter(chat, exported_at=exported_at)}\n{render_transcript(chat, annotate=True)}\n"


def render_markdown(chat: Chat, style: str = "archive", *, exported_at: str | None = None) -> str:
    if style == "export-chat":
        return render_export_chat(chat)
    if style == "archive":
        return render_archive(chat, exported_at=exported_at)
    raise ValueError(f"Unknown style {style!r}; expected one of {', '.join(STYLES)}")


def write_markdown(
    chat: Chat,
    output_dir: Path,
    *,
    style: str = "archive",
    exported_at: str | None = None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = chat_output_path(output_dir, chat, ".md")
    return write_text_file(path, render_markdown(chat, style, exported_at=exported_at))
