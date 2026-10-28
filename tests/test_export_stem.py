from poe_bulk_export.client import _merge_metadata, _prefer_message
from poe_bulk_export.models import Chat, Message
from poe_bulk_export.util import (
    chat_export_stem,
    coerce_poe_time_us,
    earliest_message_date,
)


def test_earliest_message_date():
    messages = [
        Message(author="human", text="hi", creation_time_us=1705312200000000),
        Message(author="bot", text="yo", creation_time_us=1705398600000000),
    ]
    assert earliest_message_date(messages) == "2024-01-15"
    assert earliest_message_date([]) == "undated"
    assert (
        earliest_message_date([], fallback_time_us=1705312200000000) == "2024-01-15"
    )


def test_coerce_ms_and_seconds():
    assert coerce_poe_time_us(1705312200) == 1705312200000000
    assert coerce_poe_time_us(1705312200000) == 1705312200000000
    assert coerce_poe_time_us(1705312200000000) == 1705312200000000


def test_prefer_keeps_network_timestamp_when_dom_text_wins():
    network = Message(
        author="human",
        text="short",
        creation_time_us=1705312200000000,
        source="network",
    )
    dom = Message(
        author="unknown",
        text="short but much longer scraped copy from the DOM pane",
        source="dom",
    )
    merged = _prefer_message(network, dom)
    assert merged.creation_time_us == 1705312200000000
    assert "longer scraped" in merged.text



def test_chat_export_stem_order():
    chat = Chat(
        chat_id=1,
        chat_code="93ozu1d1q42v5qtcou",
        node_id="id",
        title="Python Learning Project",
        bot="Claude-Fable-5",
        messages=[
            Message(
                author="human",
                text="hi",
                creation_time_us=1720490244153650,  # ~2024-07-09-ish; use known
            )
        ],
    )
    # Use fixture epoch from sample: 1705312200000000 → 2024-01-15
    chat.messages[0].creation_time_us = 1705312200000000
    stem = chat_export_stem(
        title=chat.title,
        bot=chat.bot,
        messages=chat.messages,
        chat_code=chat.chat_code,
    )
    assert stem.startswith("2024-01-15_Claude-Fable-5_Python_Learning_Project")
    assert stem.endswith("__93ozu1d1q42v5qtcou")
    assert " " not in stem
