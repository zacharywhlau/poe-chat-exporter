from __future__ import annotations

import mimetypes
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx

from poe_bulk_export.models import Chat
from poe_bulk_export.util import guess_attachment_name, sanitize_filename

_SAFE_EXT = re.compile(r"^[a-zA-Z0-9]{1,8}$")
_MEDIA_TYPES = (
    "image/",
    "video/",
    "audio/",
    "application/pdf",
    "application/zip",
    "application/octet-stream",
)
_SKIP_HOST_SNIPPETS = (
    "poe.com/export",
    "poe.com/savethischat",
    "poe.com/savechats",
    "export.tools",
    "poe.com/login",
    "poe.com/signup",
)


def _extension_for(url: str, content_type: str | None, name: str) -> str:
    for candidate in (Path(name).suffix, Path(urlparse(url).path).suffix):
        ext = candidate.lstrip(".").lower()
        if ext and _SAFE_EXT.match(ext) and ext not in {"html", "htm", "js", "css"}:
            return f".{ext}"
    if content_type:
        ctype = content_type.split(";")[0].strip().lower()
        if ctype.startswith("image/"):
            guessed = mimetypes.guess_extension(ctype) or ".img"
            return guessed
        if ctype.startswith("video/"):
            return mimetypes.guess_extension(ctype) or ".mp4"
        if ctype.startswith("audio/"):
            return mimetypes.guess_extension(ctype) or ".bin"
        if ctype == "application/pdf":
            return ".pdf"
    return ".bin"


def _looks_like_real_media(content_type: str | None, content: bytes) -> bool:
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ctype.startswith(("text/html", "text/plain", "application/json", "text/css")):
        return False
    if any(ctype.startswith(prefix) or ctype == prefix for prefix in _MEDIA_TYPES):
        # Guard: HTML mistaken as octet-stream
        head = content[:200].lstrip().lower()
        return not head.startswith((b"<!doctype html", b"<html"))
    # Sniff images
    return content.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF8", b"RIFF"))


def is_skip_attachment_url(url: str) -> bool:
    low = (url or "").lower()
    return any(s in low for s in _SKIP_HOST_SNIPPETS)


def download_chat_attachments(
    chat: Chat,
    output_dir: Path,
    *,
    cookies: dict[str, str] | None = None,
    user_agent: str | None = None,
    timeout: float = 60.0,
) -> int:
    """Download real media only; skip HTML/error pages.

    Prefer leaving CDN URLs embedded in Markdown (chat-like). This helper is
    for offline archives and refuses non-media responses.
    """
    if not any(m.attachments for m in chat.messages):
        return 0

    code = sanitize_filename(chat.chat_code or str(chat.chat_id) or "chat")
    att_dir = output_dir / "attachments" / code
    att_dir.mkdir(parents=True, exist_ok=True)

    downloaded = 0
    headers = {
        "User-Agent": user_agent or "Mozilla/5.0 (compatible; poe-bulk-export)",
        "Referer": "https://poe.com/",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }

    with httpx.Client(
        headers=headers,
        cookies=cookies or {},
        follow_redirects=True,
        timeout=timeout,
    ) as client:
        for message in chat.messages:
            for idx, att in enumerate(message.attachments):
                if not att.url or is_skip_attachment_url(att.url):
                    continue
                try:
                    resp = client.get(att.url)
                    resp.raise_for_status()
                except (httpx.HTTPError, httpx.InvalidURL):
                    continue

                ctype = resp.headers.get("content-type")
                if not _looks_like_real_media(ctype, resp.content):
                    continue

                base = sanitize_filename(
                    Path(att.name).stem or guess_attachment_name(att.url, "file")
                )
                mid = message.message_id if message.message_id is not None else "msg"
                ext = _extension_for(att.url, ctype, att.name)
                if ext in {".html", ".htm"}:
                    continue
                filename = f"msg-{mid}-{idx}-{base}{ext}"
                dest = att_dir / filename
                dest.write_bytes(resp.content)
                att.local_path = f"attachments/{code}/{filename}"
                downloaded += 1

    return downloaded
