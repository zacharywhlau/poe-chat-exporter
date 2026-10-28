from poe_bulk_export.markdown import render_archive_markdown
from poe_bulk_export.models import Chat, Message


def _chat() -> Chat:
    return Chat(
        chat_id=1,
        chat_code="abc",
        node_id="id",
        title="Demo",
        bot="Claude-Fable-5",
        messages=[
            Message(author="human", text="Hello"),
            Message(author="bot", text="Hi there\n\n```python\nprint(1)\n```"),
        ],
    )


def test_archive_style_uses_you_headings():
    md = render_archive_markdown(_chat(), style="archive")
    assert "## You" in md
    assert "## Claude-Fable-5" in md
    assert md.startswith("---\n")


def test_export_chat_style():
    md = render_archive_markdown(_chat(), style="export-chat")
    assert md.startswith("User:")
    assert "Claude-Fable-5:" in md
    assert "---" in md
    assert "export-chat" in md
