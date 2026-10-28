from __future__ import annotations

import json

from helpers import SHARE_CODE, load_json

from poe_bulk_export.extract import (
    ChatInfo,
    ChatTarget,
    PageInfo,
    combine_extractions,
    extract_from_graphql,
    extract_from_next_data,
    extract_from_relay_records,
    extract_from_tree,
    find_chat_info,
    merge_messages,
    message_from_node,
    parse_graphql_body,
)
from poe_bulk_export.models import Message

CHAT = ChatTarget(chat_code="code1", node_id="Q2hhdDox")


def _node(mid, author, text, t=None, **extra):
    node = {"messageId": mid, "author": author, "text": text}
    if t is not None:
        node["creationTime"] = t
    node.update(extra)
    return node


def _chat_page(nodes, *, has_previous, code="code1", node_id="Q2hhdDox", key="messagesConnection"):
    return {
        "id": node_id,
        "chatCode": code,
        "title": f"Chat {code}",
        "defaultBotObject": {"displayName": "Claude-Fable-5", "handle": "Claude-Fable-5", "nickname": "claude_fable_5"},
        key: {
            "edges": [{"node": n, "cursor": str(n["messageId"])} for n in nodes],
            "pageInfo": {"hasPreviousPage": has_previous, "startCursor": str(nodes[0]["messageId"]) if nodes else None},
        },
    }


# --------------------------------------------------------------------------- #
# Real share-page data (https://poe.com/s/AdtEREDku86PE8rUSHCO)
# --------------------------------------------------------------------------- #


def test_share_next_data_fixture():
    target = ChatTarget(share_code=SHARE_CODE)
    ex = extract_from_next_data(load_json("share_next_data.json"), target)

    assert ex.owners_used == 1
    assert [m.message_id for m in ex.messages] == [13692479, 13692480]
    human, bot = ex.messages
    assert (human.author, human.text, human.author_name) == ("human", "Who is Louis Cha?", None)
    assert human.creation_time_us == 1710744585686648
    assert bot.author == "bot"
    assert bot.author_name == "Gemini-1.0-Pro"
    assert bot.author_raw == "gemini_pro"
    assert bot.text.startswith("Louis Cha (1924-2018), also known by his pen name Jin Yong")
    assert bot.creation_time_us == 1710744585766838
    assert ex.page_info.has_more is False
    assert ex.chat.bot_name == "Gemini-1.0-Pro"


def test_share_store_records_fixture_matches_next_data():
    target = ChatTarget(share_code=SHARE_CODE)
    store = extract_from_relay_records(load_json("share_store_records.json"), target)
    next_data = extract_from_next_data(load_json("share_next_data.json"), target)

    assert store.owners_used == 1
    # The store record says `sendTime`, __NEXT_DATA__ says `creationTime`; same instant.
    assert [(m.message_id, m.author, m.creation_time_us, m.text) for m in store.messages] == [
        (m.message_id, m.author, m.creation_time_us, m.text) for m in next_data.messages
    ]
    # pageInfo comes from the Relay handle connection, which knows both directions.
    assert store.page_info == PageInfo(
        has_previous_page=False, start_cursor=None, has_next_page=False, end_cursor="13692480"
    )
    merged = combine_extractions([store, next_data])
    assert len(merged.messages) == 2


# --------------------------------------------------------------------------- #
# Scoping and pagination
# --------------------------------------------------------------------------- #


def test_pagination_pages_merge_into_one_ordered_history():
    initial = {"props": {"pageProps": {"data": {"chatOfCode": _chat_page(
        [_node(3, "human", "third", 3_000_000), _node(4, "claude_fable_5", "fourth", 4_000_000)],
        has_previous=True,
    )}}}}
    older_page = {"data": {"node": {"id": "Q2hhdDox", "messagesConnection": {
        "edges": [{"node": _node(1, "human", "first", 1_000_000)}, {"node": _node(2, "claude_fable_5", "second", 2_000_000)}],
        "pageInfo": {"hasPreviousPage": False, "startCursor": "1"},
    }}}}
    last_message_again = {"data": {"chatOfCode": _chat_page([_node(4, "claude_fable_5", "fourth", 4_000_000)], has_previous=True)}}

    next_data = extract_from_next_data(initial, CHAT)
    assert next_data.page_info.has_previous_page is True
    network = combine_extractions(
        [
            extract_from_graphql([last_message_again], CHAT),
            extract_from_graphql([older_page], CHAT, variables={"id": "Q2hhdDox", "cursor": "3"}),
        ],
        page_info="oldest",
    )
    assert network.page_info.has_previous_page is False

    merged = combine_extractions([network, next_data])
    assert [m.text for m in merged.messages] == ["first", "second", "third", "fourth"]
    assert [m.author for m in merged.messages] == ["human", "bot", "human", "bot"]


def test_sidebar_previews_of_other_chats_are_ignored():
    tree = {"data": {
        "chats": {"edges": [
            {"node": _chat_page([_node(90, "claude_fable_5", "other chat preview", 9)], has_previous=True, code="other", node_id="Q2hhdDo5")},
        ]},
        "chatOfCode": _chat_page([_node(1, "human", "mine", 1), _node(2, "claude_fable_5", "reply", 2)], has_previous=False),
    }}
    ex = extract_from_tree(tree, CHAT, source="network")
    assert ex.owners_seen == 2 and ex.owners_used == 1
    assert [m.text for m in ex.messages] == ["mine", "reply"]


def test_golden_store_fixture_ignores_sidebar_chat():
    ex = extract_from_relay_records(load_json("workflow_guide_store.json"), ChatTarget(chat_code="91z1xrschrxyu24wqx"))
    assert ex.owners_seen == 2 and ex.owners_used == 1
    assert len(ex.messages) == 4
    assert all("different conversation" not in m.text for m in ex.messages)
    # Handle connection (all loaded pages) wins over the raw first-page field.
    assert ex.page_info.has_previous_page is False


def test_owner_without_ids_is_used_only_when_unambiguous():
    lone = {"data": {"node": {"messagesConnection": {"edges": [{"node": _node(1, "human", "hi")}]}}}}
    assert len(extract_from_tree(lone, CHAT, source="network").messages) == 1

    two = {"data": {
        "a": {"messagesConnection": {"edges": [{"node": _node(1, "human", "a")}]}},
        "b": {"messagesConnection": {"edges": [{"node": _node(2, "human", "b")}]}},
    }}
    assert extract_from_tree(two, CHAT, source="network").messages == []
    # Request variables naming this chat make the response's owners trustworthy.
    hinted = extract_from_graphql([two], CHAT, variables={"id": "Q2hhdDox"})
    assert [m.text for m in hinted.messages] == ["a", "b"]


def test_mismatched_owner_is_never_used():
    other = {"data": {"chatOfCode": _chat_page([_node(1, "human", "x")], has_previous=False, code="zzz", node_id="Q2hhdDo5")}}
    assert extract_from_tree(other, CHAT, source="network").messages == []


def test_target_learns_node_id_for_pagination():
    ex = extract_from_tree({"data": {"chatOfCode": _chat_page([_node(1, "human", "x")], has_previous=True)}},
                           ChatTarget(chat_code="code1"), source="next_data")
    target = ChatTarget(chat_code="code1").enriched(ex.chat)
    assert target.node_id == "Q2hhdDox"
    assert target.matches_variables({"id": "Q2hhdDox", "cursor": "1"})


def test_find_chat_info_from_sidebar_list():
    payload = {"data": {"chats": {"edges": [
        {"node": {"chatCode": "nope", "title": "Other"}},
        {"node": {"chatCode": "code1", "chatId": 5, "title": "Mine", "defaultBotObject": {"displayName": "GPT-5"}}},
    ]}}}
    info = find_chat_info(payload, ChatTarget(chat_code="code1"))
    assert info == ChatInfo(title="Mine", chat_code="code1", chat_id=5, bot_name="GPT-5")


# --------------------------------------------------------------------------- #
# GraphQL bodies
# --------------------------------------------------------------------------- #


def _part(payload):
    return "\r\n---\r\nContent-Type: application/json; charset=utf-8\r\n\r\n" + json.dumps(payload)


def test_multipart_stream_items_are_folded_into_their_connection():
    initial = {"data": {"node": {"id": "Q2hhdDox", "messagesConnection": {
        "edges": [{"node": _node(5, "human", "q", 5)}],
        "pageInfo": {"hasPreviousPage": False},
    }}}, "hasNext": True}
    streamed = {"incremental": [{"items": [{"node": _node(6, "claude_fable_5", "a", 6)}],
                                 "path": ["node", "messagesConnection", "edges", 1]}], "hasNext": False}
    body = (_part(initial) + _part(streamed) + "\r\n-----\r\n").encode()

    payloads = parse_graphql_body(body, 'multipart/mixed; boundary="-"; deferSpec=20220824')
    assert len(payloads) == 1
    ex = extract_from_graphql(payloads, CHAT)
    assert [(m.message_id, m.text) for m in ex.messages] == [(5, "q"), (6, "a")]
    # Same body without a content-type header is still recognized.
    assert parse_graphql_body(body, None) == payloads


def test_multipart_new_incremental_format_with_pending_ids():
    initial = {"data": {"chat": {"chatCode": "code1", "messagesConnection": {"edges": []}}},
               "pending": [{"id": "0", "path": ["chat", "messagesConnection", "edges"]}], "hasNext": True}
    later = {"incremental": [{"id": "0", "items": [{"node": _node(1, "human", "hello")}]}], "hasNext": False}
    payloads = parse_graphql_body(_part(initial) + _part(later) + "\r\n-----\r\n", "multipart/mixed")
    assert [m.text for m in extract_from_graphql(payloads, CHAT).messages] == ["hello"]


def test_plain_json_and_ndjson_bodies():
    one = {"data": {"x": 1}}
    assert parse_graphql_body(json.dumps(one), "application/json") == [one]
    assert parse_graphql_body(json.dumps([one, one]), "application/json") == [one, one]
    assert parse_graphql_body(json.dumps(one) + "\n" + json.dumps(one), "") == [one, one]
    assert parse_graphql_body("", "application/json") == []
    assert parse_graphql_body("<html>nope</html>", "text/html") == []


# --------------------------------------------------------------------------- #
# Normalization and merging
# --------------------------------------------------------------------------- #


def test_message_normalization():
    msg = message_from_node(
        {
            "messageId": "123",
            "author": "human",
            "text": "see ![chart](https://pfst.cf2.poecdn.net/base/image/abc.png)",
            "creationTime": "1705312200000",
            "authorUser": {"fullName": "Ada"},
            "attachments": [
                {"name": "report.pdf", "url": "https://pfst.cf2.poecdn.net/base/application/report.pdf",
                 "file": {"mimeType": "application/pdf"}},
                {"name": "photo", "file": {"url": "https://pfst.cf2.poecdn.net/base/x/photo", "mimeType": "image/jpeg"}},
            ],
        }
    )
    assert msg.message_id == 123
    assert msg.creation_time_us == 1705312200000000
    assert msg.author == "human" and msg.author_name == "Ada"
    assert [(a.name, a.kind) for a in msg.attachments] == [("report.pdf", "file"), ("photo", "image"), ("chart", "image")]

    assert message_from_node({"messageId": 1, "author": "chat_break", "text": ""}).author == "chat_break"
    assert message_from_node({"messageId": 2, "author": "x", "text": "", "isChatAnnouncement": True}).author == "system"
    assert message_from_node({"messageId": 3, "author": "", "text": "?"}).author == "unknown"
    assert message_from_node({"cursor": "1"}) is None


def test_bot_label_fallbacks():
    default = ChatInfo(bot_name="Claude-Fable-5", bot_nickname="claude_fable_5")
    resolved = {"messageId": 1, "author": "gpt_5", "text": "x", "authorBot": {"handle": "GPT-5"}}
    assert message_from_node(resolved, default_bot=default).author_name == "GPT-5"

    same_bot = {"messageId": 1, "author": "claude_fable_5", "text": "x"}
    assert message_from_node(same_bot, default_bot=default).author_name == "Claude-Fable-5"
    mention = {"messageId": 1, "author": "gemini_pro", "text": "x"}
    assert message_from_node(mention, default_bot=default).author_name == "gemini_pro"
    # Without the chat's bot, leave it to the renderer (chat.bot).
    assert message_from_node(same_bot).author_name is None


def test_merge_by_message_id_first_source_wins():
    store = [Message(author="bot", text="fresh text", message_id=2, source="store")]
    next_data = [
        Message(author="human", text="q", message_id=1, creation_time_us=10, source="next_data"),
        Message(author="bot", text="stale text", message_id=2, creation_time_us=20, source="next_data"),
    ]
    merged = merge_messages(store, next_data)
    assert [(m.message_id, m.text) for m in merged] == [(1, "q"), (2, "fresh text")]
    assert merged[1].creation_time_us == 20  # metadata filled from the other copy

    empty_first = merge_messages([Message(author="bot", text=" ", message_id=7)], [Message(author="bot", text="real", message_id=7)])
    assert empty_first[0].text == "real"


def test_ordering_uses_time_then_id_and_falls_back_to_id():
    timed = [
        Message(author="bot", text="b", message_id=9, creation_time_us=200),
        Message(author="human", text="a", message_id=10, creation_time_us=100),
    ]
    assert [m.text for m in merge_messages(timed)] == ["a", "b"]
    partly_timed = [
        Message(author="bot", text="b", message_id=2, creation_time_us=None),
        Message(author="human", text="a", message_id=1, creation_time_us=500),
    ]
    assert [m.text for m in merge_messages(partly_timed)] == ["a", "b"]


def test_page_info_has_more():
    assert PageInfo(has_previous_page=True).has_more is True
    assert PageInfo(has_previous_page=False, has_next_page=False).has_more is False
    assert PageInfo(start_cursor="x").has_more is None
    assert PageInfo.from_dict({}) is None
    assert PageInfo.from_dict({"hasNextPage": False}).has_more is False
