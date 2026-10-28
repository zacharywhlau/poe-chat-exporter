"""Where exports go on disk.

Each chat has exactly one file per format, named ``…__{chat_code}.md`` /
``.json``. Re-exporting a chat replaces that file (and removes an older one
whose title part differs) instead of piling up ``-2``, ``-3`` copies.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from poe_bulk_export.models import Chat
from poe_bulk_export.util import (
    chat_export_stem,
    sanitize_filename_component,
    unique_path,
)


def chat_stem(chat: Chat) -> str:
    return chat_export_stem(
        title=chat.title,
        bot=chat.bot,
        messages=chat.messages,
        chat_code=chat.chat_code,
        fallback_time_us=chat.created_time_us or chat.activity_time_us,
    )


def chat_output_path(output_dir: Path, chat: Chat, suffix: str) -> Path:
    """Path for this chat's export, removing stale exports of the same chat."""
    stem = chat_stem(chat)
    if not chat.chat_code:
        return unique_path(output_dir, stem, suffix)
    target = output_dir / f"{stem}{suffix}"
    marker = f"__{sanitize_filename_component(chat.chat_code, max_len=24)}{suffix}"
    if output_dir.is_dir():
        for old in output_dir.iterdir():
            if old != target and old.name.endswith(marker) and old.is_file():
                old.unlink()
    return target


def write_text_file(path: Path, content: str) -> Path:
    """Write UTF-8 text exactly as given (no newline translation), atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path
