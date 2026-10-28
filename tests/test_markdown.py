import pytest

from poe_bulk_export.markdown import (
    render_archive,
    render_export_chat,
    render_markdown,
    render_message_body,
    speaker_label,
)
from poe_bulk_export.models import Attachment, Chat, Message


def _chat(*messages: Message, bot: str = "Claude-Fable-5") -> Chat:
    return Chat(
        chat_id=42,
        chat_code="abc123",
        title='Release "plan"',
        bot=bot,
        messages=list(messages),
        complete=True,
        source="raw",
    )


def test_speaker_labels():
    chat = _chat()
    assert speaker_label(Message(author="human", text="x"), chat) == "User"
    assert speaker_label(Message(author="bot", text="x", author_name="GPT-5"), chat) == "GPT-5"
    assert speaker_label(Message(author="bot", text="x"), chat) == "Claude-Fable-5"
    assert speaker_label(Message(author="unknown", text="x"), _chat(bot="")) == "Bot"
    assert speaker_label(Message(author="system", text="x"), chat) == "Poe"


def test_export_chat_layout():
    chat = _chat(
        Message(author="human", text="hi"),
        Message(author="bot", text="## Heading\n\n```bash\ngit status\n```"),
    )
    assert render_export_chat(chat) == (
        "User:\n\nhi\n\n---\n\nClaude-Fable-5:\n\n## Heading\n\n```bash\ngit status\n```"
    )


def test_chat_break_and_empty_turns():
    chat = _chat(
        Message(author="human", text="a"),
        Message(author="chat_break", text=""),
        Message(author="bot", text=""),
    )
    assert render_export_chat(chat) == "User:\n\na\n\n---\n\n*— Context cleared —*\n\n---\n\nClaude-Fable-5:"


def test_attachments_are_added_once_and_use_local_paths():
    image = Attachment(url="https://pfst.cf2.poecdn.net/img.png", name="img.png", kind="image")
    doc = Attachment(url="https://pfst.cf2.poecdn.net/doc.pdf", name="doc.pdf", kind="file")
    assert render_message_body(Message(author="human", text="look", attachments=[image, doc])) == (
        "look\n\n![img.png](https://pfst.cf2.poecdn.net/img.png)\n\n[doc.pdf](https://pfst.cf2.poecdn.net/doc.pdf)"
    )

    inline = Message(author="bot", text="![x](https://pfst.cf2.poecdn.net/img.png)", attachments=[image])
    assert render_message_body(inline) == "![x](https://pfst.cf2.poecdn.net/img.png)"

    local = Attachment(url=image.url, name="img.png", kind="image", local_path="attachments/abc123/msg-1-0-img.png")
    assert render_message_body(Message(author="bot", text=f"![x]({image.url})", attachments=[local])) == (
        "![x](attachments/abc123/msg-1-0-img.png)"
    )


def test_archive_front_matter_and_turn_comments():
    chat = _chat(
        Message(author="human", text="hi", message_id=7, creation_time_us=1705312200000000),
        Message(author="bot", text="hello", message_id=8, creation_time_us=1705312205000000),
    )
    out = render_archive(chat, exported_at="2024-01-16T00:00:00Z")
    assert out == (
        "---\n"
        'title: "Release \\"plan\\""\n'
        'bot: "Claude-Fable-5"\n'
        'chat_code: "abc123"\n'
        "chat_id: 42\n"
        'url: "https://poe.com/chat/abc123"\n'
        'created: "2024-01-15T09:50:00Z"\n'
        'updated: "2024-01-15T09:50:05Z"\n'
        "message_count: 2\n"
        "complete: true\n"
        'source: "raw"\n'
        'exported_at: "2024-01-16T00:00:00Z"\n'
        'exporter: "poe-bulk-export 0.2.0"\n'
        "---\n"
        "\n"
        "<!-- 2024-01-15T09:50:00Z · message 7 -->\n"
        "User:\n\nhi\n\n---\n\n"
        "<!-- 2024-01-15T09:50:05Z · message 8 -->\n"
        "Claude-Fable-5:\n\nhello\n"
    )


def test_render_markdown_rejects_unknown_style():
    with pytest.raises(ValueError):
        render_markdown(_chat(), "fancy")
