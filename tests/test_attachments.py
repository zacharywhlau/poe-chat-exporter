from __future__ import annotations

from pathlib import Path

import httpx

from poe_bulk_export.attachments import download_chat_attachments
from poe_bulk_export.models import Attachment, Chat, Message


def test_download_chat_attachments(tmp_path: Path, monkeypatch):
    class FakeResponse:
        def __init__(self):
            self.content = b"fake-image-bytes"
            self.headers = {"content-type": "image/png"}

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
            assert url.startswith("https://")
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
    assert count == 1
    att = chat.messages[0].attachments[0]
    assert att.local_path is not None
    assert att.local_path.startswith("attachments/xyz/")
    assert (tmp_path / att.local_path).exists()
