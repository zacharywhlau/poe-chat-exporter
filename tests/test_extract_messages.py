from poe_bulk_export.client import _chat_urls, _walk_message_nodes
from poe_bulk_export.models import Chat


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


def test_chat_urls_include_c_and_handle():
    chat = Chat(
        chat_id=1,
        chat_code="abc123",
        node_id="id",
        title="T",
        bot="Claude",
        bot_handle="Claude-Fable-5",
    )
    urls = _chat_urls(chat)
    assert "https://poe.com/c/abc123" in urls
    assert "https://poe.com/chat/abc123" in urls
    assert "https://poe.com/Claude-Fable-5/abc123" in urls
