from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from poe_bulk_export.cleanup import cleanup_messages
from poe_bulk_export.extract import ChatTarget, extract_from_relay_records
from poe_bulk_export.models import Chat

FIXTURES = Path(__file__).parent / "fixtures"

GOLDEN_CODE = "91z1xrschrxyu24wqx"
GOLDEN_REFERENCE = FIXTURES / "workflow_guide_export_chat.md"
SHARE_CODE = "AdtEREDku86PE8rUSHCO"


def load_json(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def golden_chat() -> Chat:
    """The 4-turn workflow-guide chat, built from its Relay store records."""
    extraction = extract_from_relay_records(
        load_json("workflow_guide_store.json"), ChatTarget(chat_code=GOLDEN_CODE)
    )
    info = extraction.chat
    return Chat(
        chat_id=info.chat_id,
        chat_code=GOLDEN_CODE,
        node_id=info.node_id or "",
        title=info.title or "Untitled",
        bot=info.bot_name or "",
        bot_handle=info.bot_handle or "",
        messages=cleanup_messages(extraction.messages),
        complete=extraction.page_info.has_more is False,
        source="raw",
    )
