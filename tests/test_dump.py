import json

from helpers import GOLDEN_CODE, golden_chat

from poe_bulk_export.client import HarvestResult
from poe_bulk_export.dump import REDACTED, redact, write_dump
from poe_bulk_export.markdown import render_export_chat
from poe_bulk_export.models import Chat


def test_redact_hides_account_fields_only():
    data = {
        "viewer": {"primaryEmail": "me@example.com", "primaryPhoneNumber": "+15550100", "uid": 77, "id": "Vmlld2VyOjA="},
        "poe-formkey": "abc",
        "tchannelData": {"channel": "poe-chan"},
        "messagesConnection": {"edges": [{"node": {"text": "keep me", "messageId": 1}}]},
        "emailVerified": None,
    }
    out = redact(data)
    assert out["viewer"] == {"primaryEmail": REDACTED, "primaryPhoneNumber": REDACTED, "uid": REDACTED, "id": "Vmlld2VyOjA="}
    assert out["poe-formkey"] == REDACTED and out["tchannelData"] == REDACTED
    assert out["messagesConnection"]["edges"][0]["node"]["text"] == "keep me"
    assert out["emailVerified"] is None


def test_write_dump_files(tmp_path):
    chat = golden_chat()
    result = HarvestResult(
        messages=chat.messages,
        complete=True,
        source="raw",
        counts={"store": 6, "next_data": 3},
        chat=None,
        url=f"https://poe.com/chat/{GOLDEN_CODE}",
        raw={
            "final_url": f"https://poe.com/chat/{GOLDEN_CODE}",
            "probe": {"envFound": True},
            "next_data": {"props": {"pageProps": {"viewer": {"primaryEmail": "me@example.com"}}}},
            "store": {"records": {"x": {"__typename": "Message"}}, "owners": [], "envFound": True, "typenames": {"Message": 1}},
            "network": [{"queryName": "ChatListPaginationQuery", "variables": {"cursor": "1"}, "payloads": [{"data": {}}]}],
            "scroll_log": [],
            "dom_html": "<div>rendered</div>",
        },
    )
    target = Chat(chat_id=chat.chat_id, chat_code=GOLDEN_CODE, title=chat.title, bot=chat.bot)
    files = {p.relative_to(tmp_path).as_posix() for p in write_dump(result, target, tmp_path)}
    assert files == {
        "next_data.json", "store_records.json", "store_summary.json", "network/001-ChatListPaginationQuery.json",
        "dom.html", "export-chat.md", "messages.json", "summary.json",
    }
    rendered = (tmp_path / "export-chat.md").read_text(encoding="utf-8")
    assert rendered == render_export_chat(golden_chat())
    assert "*Thinking...*" in rendered
    everything = "".join(p.read_text(encoding="utf-8") for p in tmp_path.rglob("*") if p.is_file())
    assert "me@example.com" not in everything
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["counts"] == {"store": 6, "next_data": 3}
    assert summary["complete"] is True
