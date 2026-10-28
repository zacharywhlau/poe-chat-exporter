from __future__ import annotations

from pathlib import Path

import httpx

from poe_bulk_export.attachments import (
    download_chat_attachments,
    is_skip_attachment_url,
)
from poe_bulk_export.models import Attachment, Chat, Message


def test_skip_non_media_urls():
    assert is_skip_attachment_url("https://poe.com/export-chat")
    assert is_skip_attachment_url("https://export.tools/")
    assert not is_skip_attachment_url("https://qph.cf2.poecdn.net/pic.png")


def _chat_with_image() -> Chat:
    return Chat(
        chat_id=1,
        chat_code="xyz",
        node_id="id",
        title="T",
        bot="Bot",
        messages=[
            Message(
                author="human",
                text="hi",
                message_id=9,
                attachments=[
                    Attachment(
                        url="https://qph.cf2.poecdn.net/pic.png",
                        name="pic.png",
                        kind="image",
                    )
                ],
            )
        ],
    )


class _FakeResponse:
    def __init__(self, content: bytes, content_type: str):
        self.content = content
        self.headers = {"content-type": content_type}

    def raise_for_status(self):
        return None


def _fake_httpx(monkeypatch, response: _FakeResponse, seen: dict) -> None:
    class FakeClient:
        def __init__(self, *args, **kwargs):
            seen.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            return response

    monkeypatch.setattr(httpx, "Client", FakeClient)


def test_download_saves_real_media_with_browser_user_agent(tmp_path: Path, monkeypatch):
    seen: dict = {}
    _fake_httpx(monkeypatch, _FakeResponse(b"\x89PNG\r\n\x1a\nrest", "image/png"), seen)
    chat = _chat_with_image()
    count = download_chat_attachments(chat, tmp_path, user_agent="Mozilla/5.0 Chrome/156.0.0.0")
    assert count == 1
    assert chat.messages[0].attachments[0].local_path == "attachments/xyz/msg-9-0-pic.png"
    assert (tmp_path / "attachments" / "xyz" / "msg-9-0-pic.png").read_bytes().startswith(b"\x89PNG")
    assert seen["headers"]["User-Agent"] == "Mozilla/5.0 Chrome/156.0.0.0"


def test_download_rejects_html(tmp_path: Path, monkeypatch):
    _fake_httpx(
        monkeypatch,
        _FakeResponse(b"<!DOCTYPE html><html><body>Error</body></html>", "text/html; charset=utf-8"),
        {},
    )
    chat = _chat_with_image()
    assert download_chat_attachments(chat, tmp_path) == 0
    assert chat.messages[0].attachments[0].local_path is None
