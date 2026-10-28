"""``.poe-export-index.json``: what was exported, so ``--incremental`` can skip it.

A chat is skipped only when its last export was complete, used the same style,
format and thinking choice, its files still exist, and the chat list reports
the same last-activity marker as before. Chats without such a marker are always
re-exported, and so are entries from versions that did not record the thinking
choice.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from poe_bulk_export.models import Chat
from poe_bulk_export.util import now_iso_z
from poe_bulk_export.writer import write_text_file

INDEX_FILE = ".poe-export-index.json"
_VERSION = 1


class ExportIndex:
    def __init__(self, output_dir: Path, chats: dict[str, dict[str, Any]] | None = None) -> None:
        self.output_dir = output_dir
        self.chats: dict[str, dict[str, Any]] = chats or {}

    @property
    def path(self) -> Path:
        return self.output_dir / INDEX_FILE

    @classmethod
    def load(cls, output_dir: Path) -> ExportIndex:
        try:
            data = json.loads((output_dir / INDEX_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        chats = data.get("chats") if isinstance(data, dict) else None
        return cls(output_dir, chats if isinstance(chats, dict) else {})

    def is_current(self, chat: Chat, *, style: str, fmt: str, strip_thinking: bool = False) -> bool:
        entry = self.chats.get(chat.chat_code)
        if not entry or not chat.activity_signature:
            return False
        if entry.get("complete") is not True:
            return False
        if entry.get("activity_signature") != chat.activity_signature:
            return False
        if entry.get("style") != style or entry.get("format") != fmt:
            return False
        if entry.get("strip_thinking") is not strip_thinking:
            return False
        files = entry.get("files") or []
        return bool(files) and all((self.output_dir / name).is_file() for name in files)

    def record(
        self, chat: Chat, files: list[Path], *, style: str, fmt: str, strip_thinking: bool = False
    ) -> None:
        last = chat.messages[-1] if chat.messages else None
        names = []
        for path in files:
            try:
                names.append(path.relative_to(self.output_dir).as_posix())
            except ValueError:
                names.append(path.name)
        self.chats[chat.chat_code] = {
            "title": chat.title,
            "files": names,
            "style": style,
            "format": fmt,
            "strip_thinking": strip_thinking,
            "complete": chat.complete is True,
            "source": chat.source,
            "message_count": len(chat.messages),
            "last_message_id": last.message_id if last else None,
            "activity_signature": chat.activity_signature,
            "exported_at": now_iso_z(),
        }

    def save(self) -> None:
        payload = {"version": _VERSION, "chats": self.chats}
        write_text_file(self.path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
