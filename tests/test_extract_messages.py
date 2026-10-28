from poe_bulk_export.client import _extract_message_nodes


def test_extract_from_chat_list_pagination_shape():
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
                                "creationTime": 1,
                            }
                        },
                        {
                            "node": {
                                "messageId": 2,
                                "author": "bot",
                                "text": "yo",
                                "creationTime": 2,
                            }
                        },
                    ]
                }
            }
        }
    }
    nodes = _extract_message_nodes(data)
    assert [n["messageId"] for n in nodes] == [1, 2]


def test_extract_from_chat_page_shape():
    data = {
        "data": {
            "chatOfCode": {
                "messagesConnection": {
                    "edges": [
                        {"node": {"messageId": 9, "author": "human", "text": "x"}}
                    ]
                }
            }
        }
    }
    nodes = _extract_message_nodes(data)
    assert nodes[0]["messageId"] == 9
