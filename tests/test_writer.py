from pathlib import Path

from poe_bulk_export.json_export import write_json
from poe_bulk_export.manifest import INDEX_FILE, ExportIndex
from poe_bulk_export.markdown import write_markdown
from poe_bulk_export.models import Chat, Message
from poe_bulk_export.writer import write_text_file


def _chat(title: str = "Plan", code: str = "abc123", signature: str | None = "lastInteractionTime=1") -> Chat:
    return Chat(
        chat_id=1,
        chat_code=code,
        title=title,
        bot="Claude-Fable-5",
        messages=[Message(author="human", text="hi", message_id=1, creation_time_us=1705312200000000)],
        complete=True,
        source="raw",
        activity_signature=signature,
    )


def _names(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir() if p.is_file())


def test_reexport_replaces_the_same_file(tmp_path):
    first = write_markdown(_chat(), tmp_path)
    second = write_markdown(_chat(), tmp_path)
    assert first == second
    assert _names(tmp_path) == ["2024-01-15_Claude-Fable-5_Plan__abc123.md"]


def test_renamed_chat_replaces_its_old_file_only(tmp_path):
    write_markdown(_chat(title="Old title"), tmp_path)
    write_markdown(_chat(code="zzz999"), tmp_path)
    write_json(_chat(title="Old title"), tmp_path)
    write_markdown(_chat(title="New title"), tmp_path)
    assert _names(tmp_path) == [
        "2024-01-15_Claude-Fable-5_New_title__abc123.md",
        "2024-01-15_Claude-Fable-5_Old_title__abc123.json",
        "2024-01-15_Claude-Fable-5_Plan__zzz999.md",
    ]


def test_write_text_file_keeps_bytes_exact(tmp_path):
    path = write_text_file(tmp_path / "x.md", "a\nb — c")
    assert path.read_bytes() == "a\nb — c".encode()
    assert _names(tmp_path) == ["x.md"]


def test_incremental_index_round_trip(tmp_path):
    chat = _chat()
    path = write_markdown(chat, tmp_path)
    index = ExportIndex.load(tmp_path)
    index.record(chat, [path], style="archive", fmt="markdown")
    index.save()
    assert (tmp_path / INDEX_FILE).is_file()

    reloaded = ExportIndex.load(tmp_path)
    assert reloaded.is_current(_chat(), style="archive", fmt="markdown")
    assert not reloaded.is_current(_chat(signature="lastInteractionTime=2"), style="archive", fmt="markdown")
    assert not reloaded.is_current(_chat(signature=None), style="archive", fmt="markdown")
    assert not reloaded.is_current(_chat(), style="export-chat", fmt="markdown")
    assert not reloaded.is_current(_chat(code="other"), style="archive", fmt="markdown")

    path.unlink()
    assert not reloaded.is_current(_chat(), style="archive", fmt="markdown")


def test_incomplete_exports_are_never_skipped(tmp_path):
    chat = _chat()
    chat.complete = False
    path = write_markdown(chat, tmp_path)
    index = ExportIndex.load(tmp_path)
    index.record(chat, [path], style="archive", fmt="markdown")
    assert not index.is_current(_chat(), style="archive", fmt="markdown")


def test_corrupt_index_is_ignored(tmp_path):
    (tmp_path / INDEX_FILE).write_text("{not json", encoding="utf-8")
    assert ExportIndex.load(tmp_path).chats == {}
