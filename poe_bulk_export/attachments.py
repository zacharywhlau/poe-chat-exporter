from __future__ import annotations

import mimetypes
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx

from poe_bulk_export.models import Chat
from poe_bulk_export.util import guess_attachment_name, sanitize_filename


_SAFE_EXT = re.compile(r"^[a-zA-Z0-9]{1,8}$")


def _extension_for(url: str, content_type: str | None, name: str) -> str:
    for candidate in (Path(name).suffix, Path(urlparse(url).path).suffix):
        ext = candidate.lstrip(".").lower()
        if ext and _SAFE_EXT.match(ext):
            return f".{ext}"
    if content_type:
        guessed = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if guessed:
            return guessed
    return ".bin"


def download_chat_attachments(
    chat: Chat,
    output_dir: Path,
    *,
    cookies: dict[str, str] | None = None,
    timeout: float = 60.0,
) -> int:
    """Download attachments into output_dir/attachments/<chat_code>/ and rewrite local_path.

    Returns the number of files successfully downloaded.
    """
    if not any(m.attachments for m in chat.messages):
        return 0

    code = sanitize_filename(chat.chat_code or str(chat.chat_id) or "chat")
    att_dir = output_dir / "attachments" / code
    att_dir.mkdir(parents=True, exist_ok=True)

    downloaded = 0
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; poe-bulk-export/0.1; +https://poe.com)"
        ),
        "Referer": "https://poe.com/",
    }

    with httpx.Client(
        headers=headers,
        cookies=cookies or {},
        follow_redirects=True,
        timeout=timeout,
    ) as client:
        for message in chat.messages:
            for idx, att in enumerate(message.attachments):
                if not att.url:
                    continue
                try:
                    resp = client.get(att.url)
                    resp.raise_for_status()
                except Exception:
                    continue

                base = sanitize_filename(
                    Path(att.name).stem or guess_attachment_name(att.url, "file")
                )
                mid = message.message_id if message.message_id is not None else "msg"
                ext = _extension_for(
                    att.url, resp.headers.get("content-type"), att.name
                )
                filename = f"msg-{mid}-{idx}-{base}{ext}"
                dest = att_dir / filename
                dest.write_bytes(resp.content)
                # Relative path from the chat .md/.json sitting in output_dir
                att.local_path = f"attachments/{code}/{filename}"
                downloaded += 1

    return downloaded
