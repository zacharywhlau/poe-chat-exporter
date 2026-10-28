from __future__ import annotations

from pathlib import Path

from poe_bulk_export.models import Chat, Message
from poe_bulk_export.util import (
    epoch_us_to_iso,
    now_iso,
    sanitize_filename,
    unique_path,
    yaml_escape,
)


def display_author(author: str, bot_name: str) -> str:
    if author in ("human", "user", "User"):
        return "You"
    if author in ("chat_break", "ChatBreak"):
        return "— break —"
    # Prefer the chat's bot display name when author is a handle-ish id
    if bot_name and author.lower().replace("-", "_") == bot_name.lower().replace(
        "-", "_"
    ).replace(" ", "_"):
        return bot_name
    if author and author not in ("unknown",):
        # Keep readable bot handles; fall back to chat bot for generic "bot"
        if author.lower() == "bot":
            return bot_name or "Bot"
        return author
    return bot_name or "Bot"


def render_message_body(message: Message) -> str:
    text = (message.text or "").rstrip()

    # Prefer durable local paths after --download-attachments
    for att in message.attachments:
        if att.local_path and att.url and att.url in text:
            text = text.replace(att.url, att.local_path)

    parts: list[str] = []
    if text:
        parts.append(text)

    body_for_dup = text.lower()
    for att in message.attachments:
        target = att.local_path or att.url
        if not target:
            continue
        # Skip if already referenced (original URL or rewritten local path)
        if target.lower() in body_for_dup:
            continue
        if att.url and att.url.lower() in body_for_dup:
            continue
        label = att.name or "attachment"
        if att.kind == "image":
            parts.append(f"![{label}]({target})")
        else:
            parts.append(f"[{label}]({target})")

    return "\n\n".join(parts).rstrip()


def render_archive_markdown(chat: Chat, *, exported_at: str | None = None) -> str:
    exported = exported_at or now_iso()
    lines: list[str] = [
        "---",
        f"title: {yaml_escape(chat.title)}",
        f"bot: {yaml_escape(chat.bot)}",
        f"chat_id: {chat.chat_id}",
        f"chat_code: {yaml_escape(chat.chat_code)}",
        f"exported_at: {exported}",
        f"message_count: {len(chat.messages)}",
        "---",
        "",
        f"# {chat.title}",
        "",
    ]

    for message in chat.messages:
        author = display_author(message.author, chat.bot)
        ts = epoch_us_to_iso(message.creation_time_us)
        heading = f"## {author}"
        if ts:
            heading += f" · {ts}"
        lines.append(heading)
        lines.append("")
        body = render_message_body(message)
        if body:
            lines.append(body)
            lines.append("")
        else:
            lines.append("_(empty message)_")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_markdown(chat: Chat, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = sanitize_filename(chat.title)
    if chat.chat_code:
        # Avoid collisions when titles repeat
        stem = f"{stem}__{sanitize_filename(chat.chat_code, max_len=40)}"
    path = unique_path(output_dir, stem, ".md")
    path.write_text(render_archive_markdown(chat), encoding="utf-8")
    return path
