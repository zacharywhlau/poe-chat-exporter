"""The export-chat style must reproduce Poe's @export-chat output exactly.

`workflow_guide_export_chat.md` is the file @export-chat produced for chat
91z1xrschrxyu24wqx after its first four messages. `workflow_guide_store.json`
holds that chat as Relay store records in the shape of Poe's private chat page:
the four messages (the first answer still starts with its *Thinking...* block),
then the @export-chat request and reply, plus a sidebar chat that must be
ignored. Message ids, times and the user record are placeholders.
"""

from __future__ import annotations

import re

from helpers import (
    GOLDEN_FILE_NAME,
    GOLDEN_REFERENCE,
    golden_chat,
    golden_stripped_export,
)

from poe_bulk_export.markdown import (
    render_archive,
    render_export_chat,
    speaker_label,
    write_markdown,
)

LABELS = ["User", "Claude-Fable-5", "User", "Claude-Fable-5", "User", "export-chat"]


def test_stripped_export_starts_with_the_export_chat_file_byte_for_byte():
    rendered = render_export_chat(golden_chat(strip_thinking=True))
    assert rendered.startswith(GOLDEN_REFERENCE.read_text(encoding="utf-8"))
    assert rendered == golden_stripped_export()


def test_default_export_keeps_thinking_and_labels_every_speaker():
    kept, stripped = golden_chat(), golden_chat(strip_thinking=True)
    assert [speaker_label(m, kept) for m in kept.messages] == LABELS

    answer = kept.messages[1].text
    assert answer.startswith("*Thinking...*\n\n> I need to create a comprehensive Git and GitHub workflow guide")
    thinking = answer[: -len(stripped.messages[1].text)]
    assert answer.endswith(stripped.messages[1].text) and len(thinking) == 2196
    assert render_export_chat(kept).replace(thinking, "", 1) == golden_stripped_export()


def test_written_file_is_named_after_the_first_message_day(tmp_path):
    path = write_markdown(golden_chat(strip_thinking=True), tmp_path, style="export-chat")
    assert path.name == GOLDEN_FILE_NAME
    assert path.read_bytes() == golden_stripped_export().encode("utf-8")


def test_golden_chat_turns():
    chat = golden_chat()
    assert [m.author for m in chat.messages] == ["human", "bot", "human", "bot", "human", "bot"]
    assert chat.messages[0].text.startswith("Draft git and GitHub workflow")
    assert [chat.messages[2].text, chat.messages[4].text] == ["recap", "@export-chat"]
    assert [m.author_name for m in chat.messages if m.author == "bot"] == ["Claude-Fable-5", "Claude-Fable-5", "export-chat"]
    reply = chat.messages[5]
    assert [(a.name, a.kind) for a in reply.attachments] == [("poe-chat-export-20261028T082857Z.md", "file")]
    assert (chat.title, chat.bot, chat.complete) == ("Python GitHub Workflow Guide", "Claude-Fable-5", True)


def test_archive_style_wraps_the_same_body():
    chat = golden_chat(strip_thinking=True)
    archive = render_archive(chat, exported_at="2026-10-28T08:30:00Z")
    assert archive.startswith("---\ntitle: \"Python GitHub Workflow Guide\"\n")
    assert archive.endswith("\n") and not archive.endswith("\n\n")

    front, body = archive.split("\n---\n\n", 1)
    assert "message_count: 6" in front and "complete: true" in front
    assert 'created: "2026-07-06T09:14:03Z"' in front
    assert body.startswith("<!-- 2026-07-06T09:14:03Z · message 421907361532 -->\nUser:\n\n")
    body = re.sub(r"(?m)^<!-- [^\n]* -->\n", "", body)
    assert body == golden_stripped_export() + "\n"
