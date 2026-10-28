from poe_bulk_export.client import (
    _chat_urls,
    _dedupe_messages,
    _looks_like_ui_chrome,
    _walk_message_nodes,
)
from poe_bulk_export.models import Chat, Message


def test_chat_prefers_chat_path_over_c():
    chat = Chat(
        chat_id=1,
        chat_code="abc123",
        node_id="id",
        title="T",
        bot="Claude",
        bot_handle="Claude-Fable-5",
    )
    urls = _chat_urls(chat)
    assert urls[0] == "https://poe.com/chat/abc123"
    assert "https://poe.com/c/abc123" in urls


def test_ui_chrome_filter():
    assert _looks_like_ui_chrome("View all")
    assert _looks_like_ui_chrome("Thinking")
    assert not _looks_like_ui_chrome("Hello, please help me learn Python")


def test_dedupe_prefers_longer_complete_copy():
    short = Message(author="bot", text="partial answer about expense tracker")
    full = Message(
        author="bot",
        text="Here's the full partial answer about expense tracker\n\n```python\nprint(1)\n```",
    )
    out = _dedupe_messages([short, full])
    assert len(out) == 1
    assert "```python" in out[0].text


def test_walk_nested_messages():
    data = {
        "data": {
            "node": {
                "messagesConnection": {
                    "edges": [
                        {
                            "node": {
                                "messageId": 1,
                                "author": "human",
                                "text": "hi",
                            }
                        }
                    ]
                }
            },
            "extra": {
                "nested": {
                    "messageId": 2,
                    "author": "bot",
                    "text": "yo",
                    "contentType": "text/plain",
                }
            },
        }
    }
    nodes = _walk_message_nodes(data)
    ids = sorted(n["messageId"] for n in nodes)
    assert ids == [1, 2]


def test_chat_urls_include_handle_variants():
    chat = Chat(
        chat_id=1,
        chat_code="abc123",
        node_id="id",
        title="T",
        bot="Claude",
        bot_handle="Claude-Fable-5",
    )
    urls = _chat_urls(chat)
    assert "https://poe.com/Claude-Fable-5/abc123" in urls
