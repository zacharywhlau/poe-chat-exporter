from __future__ import annotations

from contextlib import contextmanager

from helpers import GOLDEN_CODE, GOLDEN_REFERENCE, load_json
from typer.testing import CliRunner

from poe_bulk_export import cli
from poe_bulk_export.client import HarvestResult, NotLoggedInError
from poe_bulk_export.extract import ChatInfo, ChatTarget, extract_from_relay_records
from poe_bulk_export.manifest import INDEX_FILE
from poe_bulk_export.models import Chat

runner = CliRunner()


class FakeClient:
    def __init__(self):
        self.cookies = {"p-b": "secret-token"}
        self.user_agent = "Mozilla/5.0 Chrome/156.0.0.0"


@contextmanager
def fake_open_client(*args, **kwargs):
    yield FakeClient()


def fake_harvest(calls: list[str]):
    def harvest(client, chat, *, max_pages=200, capture_raw=False, log=None):
        calls.append(chat.chat_code)
        url = f"https://poe.com/chat/{chat.chat_code}"
        if chat.chat_code != GOLDEN_CODE:
            return HarvestResult(
                messages=[], complete=False, source="none", counts={"store": 0},
                chat=None, url=url, notes=[f"no messages found at {url}"],
            )
        ex = extract_from_relay_records(load_json("workflow_guide_store.json"), ChatTarget(chat_code=GOLDEN_CODE))
        return HarvestResult(
            messages=ex.messages, complete=True, source="raw",
            counts={"store": 4, "next_data": 2, "network": 0}, chat=ex.chat, url=url, elapsed_s=1.5,
        )

    return harvest


def _md_files(folder):
    return sorted(p.name for p in folder.glob("*.md"))


def test_direct_chat_code_export_with_failure_summary(tmp_path, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(cli, "open_client", fake_open_client)
    monkeypatch.setattr(cli, "harvest_chat", fake_harvest(calls))
    monkeypatch.setattr(cli, "list_chats", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no list scan")))

    args = [
        "export", "-t", "tok", "-o", str(tmp_path), "--style", "export-chat",
        "-c", GOLDEN_CODE, "-c", "https://poe.com/chat/missingchat",
    ]
    result = runner.invoke(cli.app, args)

    assert result.exit_code == 1, result.output
    assert calls == [GOLDEN_CODE, "missingchat"]
    expected_name = f"2026-10-28_Claude-Fable-5_Python_GitHub_Workflow_Guide__{GOLDEN_CODE}.md"
    assert _md_files(tmp_path) == [expected_name]
    assert (tmp_path / expected_name).read_bytes() == GOLDEN_REFERENCE.read_bytes()
    assert "OK   Python GitHub Workflow Guide [91z1xrschrxyu24wqx]: 4 messages (store=4, next_data=2), complete" in result.output
    assert "Failed:" in result.output and "missingchat" in result.output
    assert "Done: exported 1/2, 1 failed" in result.output

    # Exporting again replaces the file instead of adding a "-2" copy.
    result = runner.invoke(cli.app, args[:-2])
    assert result.exit_code == 0, result.output
    assert _md_files(tmp_path) == [expected_name]
    assert (tmp_path / INDEX_FILE).is_file()


def test_incremental_skips_unchanged_complete_chats(tmp_path, monkeypatch):
    calls: list[str] = []
    listed = Chat(
        chat_id=1481885248, chat_code=GOLDEN_CODE, node_id="Q2hhdDoxNDgxODg1MjQ4",
        title="Python GitHub Workflow Guide", bot="Claude-Fable-5",
        activity_signature="lastInteractionTime=1793176803222222",
    )
    monkeypatch.setattr(cli, "open_client", fake_open_client)
    monkeypatch.setattr(cli, "harvest_chat", fake_harvest(calls))
    monkeypatch.setattr(cli, "list_chats", lambda *a, **k: [Chat(**listed.__dict__)])

    args = ["export", "-t", "tok", "-o", str(tmp_path), "--incremental", "-f", "both"]
    first = runner.invoke(cli.app, args)
    assert first.exit_code == 0, first.output
    assert len(list(tmp_path.glob(f"*__{GOLDEN_CODE}.json"))) == 1 and len(_md_files(tmp_path)) == 1

    second = runner.invoke(cli.app, args)
    assert second.exit_code == 0, second.output
    assert calls == [GOLDEN_CODE]
    assert "skipped 1 unchanged" in second.output


def test_logged_out_session_exits_with_code_2(tmp_path, monkeypatch):
    @contextmanager
    def logged_out(*args, **kwargs):
        raise NotLoggedInError("Poe redirected to the login page")
        yield

    monkeypatch.setattr(cli, "open_client", logged_out)
    result = runner.invoke(cli.app, ["export", "-t", "tok", "-o", str(tmp_path), "-c", "abc"])
    assert result.exit_code == 2
    assert "login page" in result.output


def test_normalize_chat_codes():
    assert cli.normalize_chat_codes(
        ["https://poe.com/chat/abc123?ref=x", "abc123", " def ", "", "poe.com/s/SHARE1", "https://poe.com/Claude-Fable-5/xyz"]
    ) == ["abc123", "def", "SHARE1", "xyz"]


def test_apply_chat_info_fills_direct_mode_metadata():
    chat = Chat(chat_id=None, chat_code="abc")
    cli.apply_chat_info(chat, ChatInfo(title="T", chat_id=5, node_id="Q2hhdDo1", bot_name="GPT-5", bot_handle="GPT-5"))
    assert (chat.title, chat.chat_id, chat.node_id, chat.bot, chat.bot_handle) == ("T", 5, "Q2hhdDo1", "GPT-5", "GPT-5")

    listed = Chat(chat_id=1, chat_code="abc", title="From list", bot="Claude")
    cli.apply_chat_info(listed, ChatInfo(title="From page", bot_name="Other"))
    assert (listed.title, listed.bot) == ("From list", "Claude")
