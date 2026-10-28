from __future__ import annotations

import json
from pathlib import Path

from poe_bulk_export.markdown import display_author, render_archive_markdown, write_markdown
from poe_bulk_export.models import Attachment, Chat, Message
from poe_bulk_export.util import epoch_us_to_iso, extract_urls_from_text, sanitize_filename


FIXTURE = Path(__file__).parent / "fixtures" / "sample_chat.json"


def chat_from_fixture() -> Chat:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    messages = []
    for m in raw["messages"]:
        messages.append(
            Message(
                author=m["author"],
                text=m["text"],
                message_id=m.get("messageId"),
                content_type=m.get("contentType"),
                creation_time_us=m.get("time_epoch_us"),
                attachments=[
                    Attachment(
                        url=a["url"],
                        name=a.get("name") or "attachment",
                        kind=a.get("kind") or "file",
                        local_path=a.get("local_path"),
                    )
                    for a in m.get("attachments") or []
                ],
            )
        )
    return Chat(
        chat_id=raw["chatId"],
        chat_code=raw["chatCode"],
        node_id=raw["id"],
        title=raw["title"],
        bot=raw["bot"],
        messages=messages,
    )


def test_sanitize_filename():
    assert sanitize_filename('a/b:c*?"') == "a_b_c___"
    assert sanitize_filename("   ") == "Untitled"


def test_epoch_us_to_iso():
    assert epoch_us_to_iso(1705312200000000).startswith("2024-01-15T")
    assert epoch_us_to_iso(None) == ""


def test_display_author():
    assert display_author("human", "Claude") == "You"
    assert display_author("bot", "Claude") == "Claude"
    assert display_author("AssistantX", "Claude") == "AssistantX"


def test_extract_urls_from_text():
    text = "see ![x](https://qph.cf2.poecdn.net/a.png) and https://qph.cf2.poecdn.net/b.jpg"
    urls = extract_urls_from_text(text)
    assert any("a.png" in u for _, u in urls)
    assert any("b.jpg" in u for _, u in urls)


def test_render_archive_markdown_shape():
    chat = chat_from_fixture()
    md = render_archive_markdown(chat, exported_at="2026-10-28T00:00:00+00:00")

    assert md.startswith("---\n")
    assert 'title: "Sample Poe Chat"' in md
    assert "chat_id: 12345" in md
    assert "chat_code: \"abc123\"" in md
    assert "exported_at: 2026-10-28T00:00:00+00:00" in md
    assert "# Sample Poe Chat" in md
    assert "## You ·" in md
    assert "Hello — please summarize this." in md
    assert "![example.png](https://qph.cf2.poecdn.net/example.png)" in md
    # Local path rewrites CDN URL already present in the message body
    assert "attachments/abc123/msg-1003-0-sketch.jpg" in md
    assert "https://qph.cf2.poecdn.net/sketch.jpg" not in md


def test_write_markdown(tmp_path: Path):
    chat = chat_from_fixture()
    path = write_markdown(chat, tmp_path)
    assert path.exists()
    assert path.suffix == ".md"
    assert "Sample Poe Chat" in path.read_text(encoding="utf-8")
    # date_model_title__code
    assert path.name.startswith(
        "2024-01-15_Claude-Sonnet-4.5_Sample_Poe_Chat__abc123"
    )
