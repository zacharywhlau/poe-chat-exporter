from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse


_INVALID_FS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\((https?://[^)\s]+)\)")
_MD_LINK = re.compile(r"(?<!!)\[([^\]]*)\]\((https?://[^)\s]+)\)")
_CDN_URL = re.compile(
    r"https?://(?:[^\s)\"']*poecdn\.net|[^\s)\"']*poe\.com)[^\s)\"']*",
    re.IGNORECASE,
)


def sanitize_filename(name: str, max_len: int = 180) -> str:
    cleaned = _INVALID_FS.sub("_", name or "")
    cleaned = cleaned.strip(". ").strip() or "Untitled"
    return cleaned[:max_len]


def unique_path(directory: Path, stem: str, suffix: str) -> Path:
    """Return directory/stem.suffix, adding -2, -3, ... on collision."""
    candidate = directory / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate
    n = 2
    while True:
        candidate = directory / f"{stem}-{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def epoch_us_to_iso(epoch_us: int | str | None) -> str:
    if epoch_us is None or epoch_us == "":
        return ""
    try:
        us = int(epoch_us)
        dt = datetime.fromtimestamp(us / 1_000_000, tz=timezone.utc)
        return dt.isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return str(epoch_us)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def guess_attachment_name(url: str, fallback: str = "attachment") -> str:
    path = unquote(urlparse(url).path)
    name = Path(path).name
    if name and "." in name:
        return name
    return fallback


def guess_kind(url: str, name: str = "") -> str:
    lower = f"{url} {name}".lower()
    if any(ext in lower for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp")):
        return "image"
    if any(ext in lower for ext in (".mp4", ".webm", ".mov", ".mp3", ".wav", ".m4a")):
        return "media"
    return "file"


def extract_urls_from_text(text: str) -> list[tuple[str, str]]:
    """Return (name, url) pairs found in markdown / bare CDN URLs."""
    found: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(name: str, url: str) -> None:
        if url in seen:
            return
        seen.add(url)
        found.append((name or guess_attachment_name(url), url))

    for name, url in _MD_IMAGE.findall(text or ""):
        add(name or "image", url)
    for name, url in _MD_LINK.findall(text or ""):
        if any(x in url.lower() for x in ("poecdn", "poe.com", "/api/", "attachment")):
            add(name or guess_attachment_name(url), url)
    for url in _CDN_URL.findall(text or ""):
        add(guess_attachment_name(url), url.rstrip(".,;"))

    return found


def yaml_escape(value: str) -> str:
    """Quote a YAML scalar safely for frontmatter."""
    s = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'
