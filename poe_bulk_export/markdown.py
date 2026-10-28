from __future__ import annotations

from pathlib import Path

from poe_bulk_export.models import Chat, Message
from poe_bulk_export.util import (
    chat_export_stem,
    epoch_us_to_iso,
    now_iso,
    unique_path,
    yaml_escape,
)


def display_author(author: str, bot_name: str, *, style: str = "archive") -> str:
    if author in ("human", "user", "User", "You"):
        return "User" if style == "export-chat" else "You"
    if author in ("chat_break", "ChatBreak"):
        return "— break —"
    if author in ("bot", "Bot", "assistant", "unknown"):
        return bot_name or "Bot"
    if bot_name and author.lower().replace("-", "_") == bot_name.lower().replace(
        "-", "_"
    ).replace(" ", "_"):
        return bot_name
    if author:
        return author
    return bot_name or "Bot"


def render_message_body(message: Message) -> str:
    text = (message.text or "").rstrip()

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


def render_archive_markdown(
    chat: Chat,
    *,
    exported_at: str | None = None,
    style: str = "archive",
) -> str:
    exported = exported_at or now_iso()
    if style == "export-chat":
        return render_export_chat_markdown(chat)

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
        author = display_author(message.author, chat.bot, style=style)
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


def render_export_chat_markdown(chat: Chat) -> str:
    """Markdown shaped like @export-chat (User: / Bot: turns)."""
    lines: list[str] = []
    for message in chat.messages:
        author = display_author(message.author, chat.bot, style="export-chat")
        lines.append(f"{author}:")
        lines.append("")
        body = render_message_body(message)
        lines.append(body if body else "_(empty message)_")
        lines.append("")
        lines.append("---")
        lines.append("")
    lines.append(
        "*Exported with poe-bulk-export · style export-chat "
        "(compatible with [@export-chat](https://poe.com/export-chat))*"
    )
    lines.append("")
    return "\n".join(lines)


def write_markdown(
    chat: Chat,
    output_dir: Path,
    *,
    style: str = "archive",
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = chat_export_stem(
        title=chat.title,
        bot=chat.bot,
        messages=chat.messages,
        chat_code=chat.chat_code,
        fallback_time_us=chat.activity_time_us,
    )
    path = unique_path(output_dir, stem, ".md")
    path.write_text(
        render_archive_markdown(chat, style=style),
        encoding="utf-8",
    )
    return path
