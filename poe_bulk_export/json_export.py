from __future__ import annotations

import json
from pathlib import Path

from poe_bulk_export import __version__
from poe_bulk_export.models import Chat
from poe_bulk_export.util import epoch_us_to_iso, now_iso_z
from poe_bulk_export.writer import chat_output_path, write_text_file


def chat_to_export_dict(chat: Chat, *, exported_at: str | None = None) -> dict:
    return {
        "chatId": chat.chat_id,
        "chatCode": chat.chat_code,
        "nodeId": chat.node_id or None,
        "title": chat.title,
        "bot": chat.bot,
        "botHandle": chat.bot_handle or None,
        "url": chat.url,
        "complete": chat.complete,
        "source": chat.source,
        "exported_at": exported_at or now_iso_z(),
        "exporter": f"poe-bulk-export {__version__}",
        "messages": [
            {
                "messageId": m.message_id,
                "role": m.author,
                "author": m.author_raw or m.author,
                "authorName": m.author_name,
                "text": m.text,
                "contentType": m.content_type,
                "state": m.state,
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


def write_json(chat: Chat, output_dir: Path, *, exported_at: str | None = None) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = chat_output_path(output_dir, chat, ".json")
    content = json.dumps(chat_to_export_dict(chat, exported_at=exported_at), indent=2, ensure_ascii=False)
    return write_text_file(path, content + "\n")
