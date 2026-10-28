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


def sanitize_filename_component(name: str, max_len: int = 80) -> str:
    """Filename-safe component: invalid chars + spaces → underscores."""
    cleaned = _INVALID_FS.sub("_", name or "")
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned)
    cleaned = cleaned.strip("._ ") or "Untitled"
    return cleaned[:max_len]


def earliest_message_date(messages: list) -> str:
    """Return YYYY-MM-DD (UTC) from the earliest message timestamp, else undated."""
    times: list[int] = []
    for msg in messages or []:
        raw = getattr(msg, "creation_time_us", None)
        if raw is None and isinstance(msg, dict):
            raw = msg.get("creation_time_us") or msg.get("time_epoch_us")
        if raw is None or raw == "":
            continue
        try:
            times.append(int(raw))
        except (TypeError, ValueError):
            continue
    if not times:
        return "undated"
    try:
        dt = datetime.fromtimestamp(min(times) / 1_000_000, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d")
    except (OSError, OverflowError, ValueError):
        return "undated"


def chat_export_stem(
    *,
    title: str,
    bot: str,
    messages: list | None = None,
    chat_code: str = "",
) -> str:
    """Informative stem: {date}_{model}_{title}[__{chat_code}]."""
    date = earliest_message_date(messages or [])
    model = sanitize_filename_component(bot or "unknown", max_len=48)
    title_part = sanitize_filename_component(title or "Untitled", max_len=80)
    stem = f"{date}_{model}_{title_part}"
    if chat_code:
        stem = f"{stem}__{sanitize_filename_component(chat_code, max_len=24)}"
    return sanitize_filename_component(stem, max_len=180)


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
