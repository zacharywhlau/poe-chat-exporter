from poe_bulk_export.client import (
    HarvestResult,
    _chat_urls,
    _query_meta,
    chat_from_list_node,
    normalize_user_agent,
)
from poe_bulk_export.gql_hashes import QUERIES
from poe_bulk_export.models import Chat


def test_user_agent_drops_headless_marker_but_keeps_real_version():
    ua = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/156.0.8078.4 Safari/537.36"
    assert normalize_user_agent(ua) == (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.8078.4 Safari/537.36"
    )


def test_chat_urls():
    assert _chat_urls(Chat(chat_id=1, chat_code="abc")) == ["https://poe.com/chat/abc"]
    assert _chat_urls(Chat(chat_id=1, chat_code="abc", bot_handle="@Claude-Fable-5")) == [
        "https://poe.com/chat/abc",
        "https://poe.com/Claude-Fable-5/abc",
    ]
    assert _chat_urls(Chat(chat_id=1, chat_code="")) == []


def test_query_meta():
    post = '{"queryName":"ChatListPaginationQuery","variables":{"count":10,"cursor":"5","id":"Q2hhdDox"}}'
    assert _query_meta(post) == ("ChatListPaginationQuery", {"count": 10, "cursor": "5", "id": "Q2hhdDox"})
    assert _query_meta("not json", {"poe-queryname": "ChatLastMessageAreaQuery"}) == ("ChatLastMessageAreaQuery", None)
    assert _query_meta(None) == (None, None)


def test_chat_list_node_activity_signature():
    node = {
        "id": "Q2hhdDox",
        "chatId": 1,
        "chatCode": "abc",
        "title": "Plan",
        "creationTime": 1705312200000000,
        "lastInteractionTime": 1705398600000000,
        "defaultBotObject": {"displayName": "Claude-Fable-5", "handle": "Claude-Fable-5"},
    }
    chat = chat_from_list_node(node)
    assert (chat.title, chat.bot, chat.bot_handle, chat.node_id) == ("Plan", "Claude-Fable-5", "Claude-Fable-5", "Q2hhdDox")
    assert chat.activity_signature == "lastInteractionTime=1705398600000000"
    assert chat.activity_time_us == 1705398600000000
    assert chat.created_time_us == 1705312200000000

    # Creation time alone says nothing about new messages: never skip such chats.
    assert chat_from_list_node({"chatCode": "abc", "creationTime": 1}).activity_signature is None
    assert chat_from_list_node({"chatCode": "abc", "lastMessage": {"messageId": 99}}).activity_signature == "lastMessage=99"


def test_chat_list_pagination_hash_is_the_documented_value():
    assert QUERIES["ChatListPaginationQuery"] == "c1a8fd96dd6e0a4679814182951b1e256e175587513c81b223addf931833a692"


def test_harvest_summary_line():
    base = {"messages": [object()] * 4, "chat": None, "url": "u"}
    assert HarvestResult(complete=True, source="raw", counts={"store": 4, "next_data": 2, "network": 0}, **base).summary() == (
        "4 messages (store=4, next_data=2), complete"
    )
    incomplete = HarvestResult(complete=False, source="raw", counts={"store": 4}, **base).summary()
    assert "INCOMPLETE" in incomplete
    degraded = HarvestResult(complete=None, source="dom-fallback", counts={"dom": 4}, **base).summary()
    assert "DOM fallback" in degraded and "unknown" in degraded
