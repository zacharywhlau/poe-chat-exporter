from poe_bulk_export.cli import filter_chats_by_codes
from poe_bulk_export.models import Chat


def _chat(code: str, title: str = "T") -> Chat:
    return Chat(
        chat_id=1,
        chat_code=code,
        node_id="id",
        title=title,
        bot="Claude",
    )


def test_filter_chats_by_codes_match():
    chats = [
        _chat("91z1xrschrxyu24wqx", "Workflow"),
        _chat("othercode", "Other"),
    ]
    out = filter_chats_by_codes(chats, ["91z1xrschrxyu24wqx"])
    assert len(out) == 1
    assert out[0].title == "Workflow"


def test_filter_chats_by_codes_case_insensitive():
    chats = [_chat("AbC123")]
    out = filter_chats_by_codes(chats, ["abc123"])
    assert len(out) == 1


def test_filter_chats_by_codes_none_returns_all():
    chats = [_chat("a"), _chat("b")]
    assert filter_chats_by_codes(chats, None) == chats
    assert filter_chats_by_codes(chats, []) == chats


def test_filter_chats_by_codes_repeatable():
    chats = [_chat("a"), _chat("b"), _chat("c")]
    out = filter_chats_by_codes(chats, ["a", "c"])
    assert [c.chat_code for c in out] == ["a", "c"]
