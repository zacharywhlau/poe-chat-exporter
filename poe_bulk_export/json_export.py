from __future__ import annotations

import json
from pathlib import Path

from poe_bulk_export.models import Chat
from poe_bulk_export.util import chat_export_stem, epoch_us_to_iso, now_iso, unique_path


def chat_to_export_dict(chat: Chat) -> dict:
    return {
        "chatId": chat.chat_id,
        "chatCode": chat.chat_code,
        "title": chat.title,
        "bot": chat.bot,
        "exported_at": now_iso(),
        "messages": [
            {
                "author": m.author,
                "text": m.text,
                "messageId": m.message_id,
                "contentType": m.content_type,
                "time": epoch_us_to_iso(m.creation_time_us),
                "time_epoch_us": m.creation_time_us,
                "attachments": [
                    {
                        "url": a.url,
                        "name": a.name,
                        "kind": a.kind,
                        "local_path": a.local_path,
                    }
                    for a in m.attachments
                ],
            }
            for m in chat.messages
        ],
    }


def write_json(chat: Chat, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = chat_export_stem(
        title=chat.title,
        bot=chat.bot,
        messages=chat.messages,
        chat_code=chat.chat_code,
    )
    path = unique_path(output_dir, stem, ".json")
    path.write_text(
        json.dumps(chat_to_export_dict(chat), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path
