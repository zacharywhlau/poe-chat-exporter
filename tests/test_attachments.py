from __future__ import annotations

from pathlib import Path

import httpx

from poe_bulk_export.attachments import (
    download_chat_attachments,
    ensure_inline_markdown_embeds,
    is_skip_attachment_url,
)
from poe_bulk_export.models import Attachment, Chat, Message


def test_skip_non_media_urls():
    assert is_skip_attachment_url("https://poe.com/export-chat")
    assert is_skip_attachment_url("https://export.tools/")
    assert not is_skip_attachment_url("https://qph.cf2.poecdn.net/pic.png")


def test_ensure_inline_markdown_embeds():
    chat = Chat(
        chat_id=1,
        chat_code="xyz",
        node_id="id",
        title="T",
        bot="Bot",
        messages=[
            Message(
                author="bot",
                text="see this",
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
    ensure_inline_markdown_embeds(chat)
    assert "![pic.png](https://qph.cf2.poecdn.net/pic.png)" in chat.messages[0].text


def test_download_rejects_html(tmp_path: Path, monkeypatch):
    class FakeResponse:
        def __init__(self):
            self.content = b"<!DOCTYPE html><html><body>Error</body></html>"
            self.headers = {"content-type": "text/html; charset=utf-8"}

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)

    chat = Chat(
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

    count = download_chat_attachments(chat, tmp_path)
    assert count == 0
    assert chat.messages[0].attachments[0].local_path is None
