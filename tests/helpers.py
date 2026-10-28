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
GOLDEN_FILE_NAME = f"2026-07-06_Claude-Fable-5_Python_GitHub_Workflow_Guide__{GOLDEN_CODE}.md"
SHARE_CODE = "AdtEREDku86PE8rUSHCO"

EXPORT_CHAT_FOOTER = (
    "*Exported with [@export-chat](<https://poe.com/export-chat>) · "
    "Also try [@SaveThisChat](<https://poe.com/SaveThisChat>) and [@savechats](<https://poe.com/savechats>) · "
    "Client-side Markdown viewer for your files at [export.tools](<https://export.tools>)*"
)
EXPORT_CHAT_ATTACHMENT = (
    "[poe-chat-export-20261028T082857Z.md](https://pfst.cf2.poecdn.net/base/text/"
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef?pmaid=100000001)"
)


def load_json(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def golden_chat(*, strip_thinking: bool = False) -> Chat:
    """The workflow-guide chat (six turns), built from its Relay store records."""
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
        messages=cleanup_messages(extraction.messages, strip_thinking=strip_thinking),
        complete=extraction.page_info.has_more is False,
        source="raw",
    )


def golden_stripped_export() -> str:
    """What ``--style export-chat --strip-thinking`` must write for the golden chat.

    The first four turns are the @export-chat file itself. Then come the
    ``@export-chat`` request and the bot's reply: that same file, a footer, and
    the exported file as an attachment.
    """
    reference = GOLDEN_REFERENCE.read_text(encoding="utf-8")
    return "\n\n---\n\n".join(
        [
            reference,
            "User:\n\n@export-chat",
            f"export-chat:\n\n{reference}\n\n---\n\n{EXPORT_CHAT_FOOTER}\n\n{EXPORT_CHAT_ATTACHMENT}",
        ]
    )
