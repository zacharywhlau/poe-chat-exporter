"""``poe-bulk-export dump``: save what a chat page contains, for troubleshooting.

Cookies and request headers are never written. Account fields Poe embeds in
page data (email, phone, uid, formkey, …) are replaced with ``[redacted]``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from poe_bulk_export import __version__
from poe_bulk_export.cleanup import cleanup_messages
from poe_bulk_export.client import HarvestResult
from poe_bulk_export.markdown import render_export_chat
from poe_bulk_export.models import Chat
from poe_bulk_export.writer import write_text_file

_SENSITIVE_KEY = re.compile(
    r"(formkey|e-?mail|phone|token|cookie|secret|password|session|tchannel|^uid$|^viewerId$)",
    re.IGNORECASE,
)
REDACTED = "[redacted]"


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: REDACTED if _SENSITIVE_KEY.search(str(key)) and item not in (None, "", [], {}) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def _write_json(path: Path, data: Any) -> Path:
    return write_text_file(path, json.dumps(redact(data), indent=2, ensure_ascii=False) + "\n")


def write_dump(result: HarvestResult, chat: Chat, folder: Path) -> list[Path]:
    raw = result.raw or {}
    store = raw.get("store") or {}
    written: list[Path] = []
    folder.mkdir(parents=True, exist_ok=True)

    written.append(_write_json(folder / "next_data.json", raw.get("next_data")))
    written.append(_write_json(folder / "store_records.json", store.get("records") or {}))
    written.append(
        _write_json(
            folder / "store_summary.json",
            {key: store.get(key) for key in ("envFound", "owners", "chosen", "status", "storeRecords", "typenames")},
        )
    )

    network_dir = folder / "network"
    for i, capture in enumerate(raw.get("network") or [], 1):
        name = re.sub(r"[^A-Za-z0-9_.-]+", "_", capture.get("queryName") or "response")
        written.append(_write_json(network_dir / f"{i:03d}-{name}.json", capture))

    dom_html = raw.get("dom_html")
    if dom_html:
        written.append(write_text_file(folder / "dom.html", dom_html))

    rendered = Chat(
        chat_id=chat.chat_id,
        chat_code=chat.chat_code,
        title=chat.title,
        bot=chat.bot,
        messages=cleanup_messages(result.messages),
    )
    written.append(write_text_file(folder / "export-chat.md", render_export_chat(rendered)))
    written.append(_write_json(folder / "messages.json", [m.to_dict() for m in result.messages]))

    summary = {
        "exporter": f"poe-bulk-export {__version__}",
        "chat_code": chat.chat_code,
        "final_url": result.url,
        "summary": result.summary(),
        "complete": result.complete,
        "source": result.source,
        "counts": result.counts,
        "pages_loaded_by_scrolling": result.pages_loaded,
        "graphql_pages": result.graphql_pages,
        "elapsed_s": round(result.elapsed_s, 2),
        "notes": result.notes,
        "chat": result.chat.__dict__ if result.chat else None,
        "message_ids": [m.message_id for m in result.messages],
        "probe": raw.get("probe"),
        "scroll_log": raw.get("scroll_log"),
        "network_queries": [c.get("queryName") for c in raw.get("network") or []],
    }
    written.append(_write_json(folder / "summary.json", summary))
    return written
