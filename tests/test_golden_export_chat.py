"""The export-chat style must reproduce Poe's @export-chat output exactly.

`workflow_guide_export_chat.md` is the file @export-chat produced for chat
91z1xrschrxyu24wqx. `workflow_guide_store.json` holds the same 4 messages as
Relay store records (plus a sidebar chat that must be ignored).
"""

from __future__ import annotations

import re

from helpers import GOLDEN_CODE, GOLDEN_REFERENCE, golden_chat

from poe_bulk_export.markdown import render_archive, render_export_chat, write_markdown


def test_export_chat_style_matches_reference_byte_for_byte():
    expected = GOLDEN_REFERENCE.read_text(encoding="utf-8")
    assert render_export_chat(golden_chat()) == expected


def test_written_export_chat_file_is_byte_identical(tmp_path):
    path = write_markdown(golden_chat(), tmp_path, style="export-chat")
    assert path.name.endswith(f"__{GOLDEN_CODE}.md")
    assert path.read_bytes() == GOLDEN_REFERENCE.read_bytes()


def test_golden_chat_has_four_turns_in_order():
    chat = golden_chat()
    assert [m.author for m in chat.messages] == ["human", "bot", "human", "bot"]
    assert chat.messages[0].text.startswith("Draft git and GitHub workflow")
    assert chat.messages[2].text == "recap"
    assert {m.author_name for m in chat.messages if m.author == "bot"} == {"Claude-Fable-5"}
    assert chat.complete is True
    assert chat.title == "Python GitHub Workflow Guide"


def test_archive_style_wraps_the_same_body():
    chat = golden_chat()
    archive = render_archive(chat, exported_at="2026-10-28T08:28:57Z")
    assert archive.startswith("---\ntitle: \"Python GitHub Workflow Guide\"\n")
    assert archive.endswith("\n") and not archive.endswith("\n\n")

    front, body = archive.split("\n---\n\n", 1)
    assert "message_count: 4" in front
    assert "complete: true" in front
    body = re.sub(r"(?m)^<!-- [^\n]* -->\n", "", body)
    assert body == GOLDEN_REFERENCE.read_text(encoding="utf-8") + "\n"
