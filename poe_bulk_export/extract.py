"""Read Poe chat messages out of the data Poe ships with each chat page.

A Poe chat page carries every message it has loaded, with the raw markdown
`@export-chat` prints, in three shapes:

* the Relay record store (normalized records linked by ``{"__ref": id}``),
* ``window.__NEXT_DATA__`` (the server-rendered GraphQL response tree),
* GraphQL responses (the same tree shape, sometimes ``multipart/mixed``).

All three hang the messages off an *owner* record (the chat, or a chat share)
through a field whose name contains ``messagesConnection``. Taking messages
only from the owner that matches the target chat keeps sidebar previews of
other chats out. Messages from all sources are merged by ``messageId``.

Nothing in this module touches a browser, so all of it is unit-tested.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field, replace
from typing import Any

from poe_bulk_export.attachments import is_skip_attachment_url
from poe_bulk_export.models import Attachment, Message
from poe_bulk_export.util import (
    coerce_poe_time_us,
    extract_urls_from_text,
    guess_attachment_name,
    guess_kind,
)

_CONNECTION_KEY = re.compile(r"messagesconnection", re.IGNORECASE)
# Relay "handle" connections (e.g. `__ChatMessagesView_chat_messagesConnection_connection`)
# accumulate every page the UI has loaded, so their pageInfo is authoritative.
_HANDLE_CONNECTION_KEY = re.compile(r"^__.*_connection$")
_BOT_KEYS = ("defaultBotObject", "chatBot", "bot")

Deref = Callable[[Any], Any]


@dataclass(frozen=True)
class ChatTarget:
    """Identifies the conversation whose messages we want."""

    chat_code: str | None = None
    chat_id: int | str | None = None
    node_id: str | None = None
    share_code: str | None = None

    def matches(self, record: dict[str, Any]) -> bool | None:
        """True/False if the record carries a comparable id, None if it carries none."""
        results: list[bool] = []
        for field_name, wanted in (
            ("chatCode", self.chat_code),
            ("chatId", self.chat_id),
            ("id", self.node_id),
            ("shareCode", self.share_code),
        ):
            if wanted in (None, ""):
                continue
            have = record.get(field_name)
            if have in (None, "") or isinstance(have, (dict, list)):
                continue
            results.append(str(have) == str(wanted))
        if results:
            return any(results)
        return None

    def matches_variables(self, variables: dict[str, Any] | None) -> bool:
        """True if GraphQL request variables point at this chat."""
        if not isinstance(variables, dict):
            return False
        for keys, wanted in (
            (("id", "nodeId"), self.node_id),
            (("chatId",), self.chat_id),
            (("chatCode", "code"), self.chat_code),
            (("shareCode",), self.share_code),
        ):
            if wanted in (None, ""):
                continue
            for key in keys:
                if key in variables and str(variables[key]) == str(wanted):
                    return True
        return False

    def enriched(self, info: ChatInfo | None) -> ChatTarget:
        """Fill in ids learned from the page (e.g. the node id for pagination)."""
        if info is None:
            return self
        return replace(
            self,
            chat_code=self.chat_code or info.chat_code,
            chat_id=self.chat_id if self.chat_id not in (None, "") else info.chat_id,
            node_id=self.node_id or info.node_id,
        )

    def as_js(self) -> dict[str, Any]:
        return {
            "chatCode": self.chat_code,
            "chatId": None if self.chat_id is None else str(self.chat_id),
            "nodeId": self.node_id,
            "shareCode": self.share_code,
        }


@dataclass
class PageInfo:
    has_previous_page: bool | None = None
    start_cursor: str | None = None
    has_next_page: bool | None = None
    end_cursor: str | None = None

    @property
    def has_more(self) -> bool | None:
        """True if the connection says more messages exist, None if it does not say."""
        flags = [f for f in (self.has_previous_page, self.has_next_page) if f is not None]
        if not flags:
            return None
        return any(flags)

    @classmethod
    def from_dict(cls, raw: Any) -> PageInfo | None:
        if not isinstance(raw, dict):
            return None
        info = cls(
            has_previous_page=_opt_bool(raw.get("hasPreviousPage")),
            start_cursor=_opt_str(raw.get("startCursor")),
            has_next_page=_opt_bool(raw.get("hasNextPage")),
            end_cursor=_opt_str(raw.get("endCursor")),
        )
        if info.has_more is None and info.start_cursor is None and info.end_cursor is None:
            return None
        return info


@dataclass
class ChatInfo:
    """Chat metadata found on the owner record."""

    title: str | None = None
    chat_code: str | None = None
    chat_id: int | str | None = None
    node_id: str | None = None
    bot_name: str | None = None
    bot_handle: str | None = None
    bot_nickname: str | None = None

    def merged(self, other: ChatInfo | None) -> ChatInfo:
        if other is None:
            return self
        values = {}
        for name in self.__dataclass_fields__:
            mine = getattr(self, name)
            values[name] = mine if mine not in (None, "") else getattr(other, name)
        return ChatInfo(**values)


@dataclass
class Extraction:
    messages: list[Message] = field(default_factory=list)
    page_info: PageInfo | None = None
    chat: ChatInfo | None = None
    owners_seen: int = 0
    owners_used: int = 0


# --------------------------------------------------------------------------- #
# Public entry points
# --------------------------------------------------------------------------- #


def extract_from_relay_records(
    records: dict[str, Any] | None,
    target: ChatTarget,
    *,
    source: str = "store",
) -> Extraction:
    """Messages of the target chat from Relay store records (``{dataID: record}``)."""
    if not isinstance(records, dict) or not records:
        return Extraction()

    def deref(value: Any) -> Any:
        if isinstance(value, dict):
            ref = value.get("__ref")
            if isinstance(ref, str):
                return records.get(ref)
            refs = value.get("__refs")
            if isinstance(refs, list):
                return [records[r] for r in refs if isinstance(r, str) and r in records]
        return value

    owners: list[tuple[dict[str, Any], list[tuple[str, dict[str, Any]]]]] = []
    for record in records.values():
        if not isinstance(record, dict):
            continue
        conns = []
        for key, value in record.items():
            if not _CONNECTION_KEY.search(key):
                continue
            conn = deref(value)
            if isinstance(conn, dict) and "edges" in conn:
                conns.append((key, conn))
        if conns:
            owners.append((record, conns))
    return _extract_from_owners(owners, target, deref=deref, source=source)


def extract_from_tree(
    data: Any,
    target: ChatTarget,
    *,
    source: str,
    variables_match: bool = False,
) -> Extraction:
    """Messages of the target chat from a GraphQL response tree / ``__NEXT_DATA__``."""
    owners: list[tuple[dict[str, Any], list[tuple[str, dict[str, Any]]]]] = []
    for node in _iter_dicts(data):
        conns = [
            (key, value)
            for key, value in node.items()
            if _CONNECTION_KEY.search(key)
            and isinstance(value, dict)
            and isinstance(value.get("edges"), list)
        ]
        if conns:
            owners.append((node, conns))
    return _extract_from_owners(
        owners,
        target,
        deref=_identity,
        source=source,
        variables_match=variables_match,
    )


def extract_from_next_data(next_data: Any, target: ChatTarget) -> Extraction:
    return extract_from_tree(next_data, target, source="next_data")


def extract_from_graphql(
    payloads: Iterable[dict[str, Any]],
    target: ChatTarget,
    *,
    variables: dict[str, Any] | None = None,
    source: str = "network",
) -> Extraction:
    """Messages of the target chat from parsed GraphQL payloads of one response.

    When several payloads carry page info, the one holding the oldest message
    wins: it says whether anything older is left.
    """
    variables_match = target.matches_variables(variables)
    parts = [
        extract_from_tree(p, target, source=source, variables_match=variables_match)
        for p in payloads
        if isinstance(p, dict)
    ]
    return combine_extractions(parts, page_info="oldest")


def combine_extractions(
    parts: Iterable[Extraction],
    *,
    page_info: str = "first",
) -> Extraction:
    """Merge extractions; ``page_info`` is ``"first"`` (priority order) or ``"oldest"``."""
    parts = list(parts)
    out = Extraction(
        messages=merge_messages(*(p.messages for p in parts)),
        owners_seen=sum(p.owners_seen for p in parts),
        owners_used=sum(p.owners_used for p in parts),
    )
    for part in parts:
        if part.chat is not None:
            out.chat = part.chat if out.chat is None else out.chat.merged(part.chat)
    with_info = [p for p in parts if p.page_info is not None]
    if with_info:
        if page_info == "oldest":
            with_info.sort(key=lambda p: _oldest_key(p.messages))
        out.page_info = with_info[0].page_info
    return out


def find_chat_info(data: Any, target: ChatTarget) -> ChatInfo | None:
    """Title/bot of the target chat from any JSON tree (e.g. a sidebar list)."""
    for node in _iter_dicts(data):
        if node.get("chatCode") is None and node.get("chatId") is None:
            continue
        if target.matches(node) is True:
            info = _chat_info(node, _identity)
            if info.title or info.bot_name:
                return info
    return None


# --------------------------------------------------------------------------- #
# GraphQL response bodies
# --------------------------------------------------------------------------- #


def parse_graphql_body(body: str | bytes | None, content_type: str | None = None) -> list[dict[str, Any]]:
    """Parse a GraphQL HTTP body into payloads (JSON, NDJSON or ``multipart/mixed``).

    Incremental-delivery parts (``@defer``/``@stream``) are folded back into the
    initial payload so connection edges stay attached to their owner.
    """
    if body is None:
        return []
    text = body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else str(body)
    if not text.strip():
        return []
    boundary = _multipart_boundary(content_type or "")
    if boundary is None:
        first_line = text.lstrip("\r\n").split("\n", 1)[0].strip()
        if first_line.startswith("--") and len(first_line) > 2:
            boundary = first_line[2:]

    if boundary is not None:
        payloads = [p for p in (_load_json(part) for part in _multipart_parts(text, boundary)) if p]
    else:
        loaded = _load_json(text)
        if loaded is None:
            payloads = [p for p in (_load_json(line) for line in text.splitlines()) if p]
        elif isinstance(loaded, list):
            payloads = [p for p in loaded if isinstance(p, dict)]
        else:
            payloads = [loaded]
    return _assemble_incremental(payloads)


def _multipart_boundary(content_type: str) -> str | None:
    if "multipart" not in content_type.lower():
        return None
    match = re.search(r'boundary\s*=\s*"?([^";]+)"?', content_type, re.IGNORECASE)
    return match.group(1).strip() if match else "-"


def _multipart_parts(text: str, boundary: str) -> Iterator[str]:
    delimiter = re.compile(r"(?:^|\r?\n)--" + re.escape(boundary) + r"(?:--)?[ \t]*(?=\r?\n|$)")
    for chunk in delimiter.split(text):
        chunk = chunk.strip("\r\n")
        if not chunk.strip():
            continue
        # A part is "headers, blank line, body"; some servers omit the headers.
        match = re.search(r"\r?\n\r?\n", chunk)
        if match and re.match(r"^[A-Za-z-]+\s*:", chunk):
            yield chunk[match.end() :]
        else:
            yield chunk


def _load_json(text: str) -> Any:
    text = (text or "").strip()
    if not text or text[0] not in "{[":
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def _assemble_incremental(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    pending: dict[str, list[Any]] = {}
    for payload in payloads:
        for entry in payload.get("pending") or []:
            if isinstance(entry, dict) and isinstance(entry.get("path"), list):
                pending[str(entry.get("id"))] = entry["path"]
        incremental = payload.get("incremental")
        if isinstance(incremental, list) and out:
            for patch in incremental:
                if not isinstance(patch, dict):
                    continue
                if "path" not in patch and str(patch.get("id")) in pending:
                    path = list(pending[str(patch.get("id"))]) + list(patch.get("subPath") or [])
                    patch = {**patch, "path": path}
                _apply_patch(out[-1], patch)
            continue
        # Pre-2023 @defer/@stream format: each part is {"path": [...], "data"/"items": ...}
        if out and "path" in payload and ("items" in payload or "data" in payload):
            _apply_patch(out[-1], payload)
            continue
        out.append(payload)
    return out


def _apply_patch(base: dict[str, Any], patch: dict[str, Any]) -> None:
    path = patch.get("path")
    if not isinstance(path, list):
        return
    root = base.setdefault("data", {})
    if "items" in patch and isinstance(patch["items"], list) and path:
        # Old format: path ends with the first item's index. New format: path is the list.
        if isinstance(path[-1], int):
            parent, index = _walk_path(root, path[:-1], create=True), path[-1]
        else:
            parent = _walk_path(root, path, create=True)
            index = len(parent) if isinstance(parent, list) else 0
        if isinstance(parent, list):
            for offset, item in enumerate(patch["items"]):
                pos = index + offset
                if pos < len(parent):
                    parent[pos] = item
                else:
                    parent.append(item)
        return
    data = patch.get("data")
    if isinstance(data, dict):
        target = _walk_path(root, path, create=True)
        if isinstance(target, dict):
            _deep_merge(target, data)


def _walk_path(root: Any, path: list[Any], *, create: bool) -> Any:
    node = root
    for i, key in enumerate(path):
        if isinstance(node, dict) and isinstance(key, str):
            if key not in node and create:
                nxt = path[i + 1] if i + 1 < len(path) else None
                node[key] = [] if isinstance(nxt, int) else {}
            node = node.get(key)
        elif isinstance(node, list) and isinstance(key, int) and 0 <= key < len(node):
            node = node[key]
        else:
            return None
    return node


def _deep_merge(dst: dict[str, Any], src: dict[str, Any]) -> None:
    for key, value in src.items():
        if isinstance(value, dict) and isinstance(dst.get(key), dict):
            _deep_merge(dst[key], value)
        else:
            dst[key] = value


# --------------------------------------------------------------------------- #
# Message normalization and merging
# --------------------------------------------------------------------------- #


def message_from_node(
    node: Any,
    *,
    deref: Deref | None = None,
    source: str = "unknown",
    default_bot: ChatInfo | None = None,
) -> Message | None:
    """Normalize one raw Poe ``Message`` node (tree or Relay record)."""
    deref = deref or _identity
    if not isinstance(node, dict):
        return None
    if "messageId" not in node and "text" not in node:
        return None

    raw_author = _opt_str(node.get("author")) or ""
    role = _role(raw_author, node)
    text = node.get("text")
    text = text if isinstance(text, str) else ""

    author_name = None
    if role == "bot":
        author_name = _bot_label(deref(node.get("authorBot")) or deref(node.get("bot")), raw_author, default_bot)
    elif role == "human":
        user = deref(node.get("authorUser"))
        if isinstance(user, dict):
            author_name = _opt_str(user.get("fullName")) or _opt_str(user.get("handle"))

    time_us = None
    for key in ("creationTime", "sendTime", "createdAt"):
        time_us = coerce_poe_time_us(node.get(key))
        if time_us is not None:
            break

    return Message(
        author=role,
        text=text,
        message_id=_message_id(node.get("messageId")),
        content_type=_opt_str(node.get("contentType")),
        creation_time_us=time_us,
        attachments=_attachments(node, deref, text),
        source=source,
        author_name=author_name,
        author_raw=raw_author or None,
        state=_opt_str(node.get("state")),
    )


def merge_messages(*groups: Iterable[Message]) -> list[Message]:
    """Union of messages keyed by ``messageId``; earlier groups win on conflicts.

    Messages without an id (DOM fallback) are kept in their given order after
    the identified ones.
    """
    by_id: dict[Any, Message] = {}
    anonymous: list[Message] = []
    for group in groups:
        for message in group:
            if message.message_id is None:
                anonymous.append(message)
                continue
            key = _id_key(message.message_id)
            existing = by_id.get(key)
            by_id[key] = message if existing is None else _combine(existing, message)
    return order_messages(list(by_id.values())) + anonymous


def order_messages(messages: list[Message]) -> list[Message]:
    """Chronological order: by (time, id) when every message has a time, else by id."""
    if messages and all(m.creation_time_us is not None for m in messages):
        return sorted(messages, key=lambda m: (m.creation_time_us, _id_key(m.message_id)))
    return sorted(messages, key=lambda m: _id_key(m.message_id))


def _combine(primary: Message, other: Message) -> Message:
    text = primary.text if primary.text.strip() else other.text
    attachments = list(primary.attachments)
    known = {a.url for a in attachments}
    attachments.extend(a for a in other.attachments if a.url not in known)
    return replace(
        primary,
        text=text,
        author=primary.author if primary.author != "unknown" else other.author,
        content_type=primary.content_type or other.content_type,
        creation_time_us=primary.creation_time_us if primary.creation_time_us is not None else other.creation_time_us,
        attachments=attachments,
        author_name=primary.author_name or other.author_name,
        author_raw=primary.author_raw or other.author_raw,
        state=primary.state or other.state,
    )


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #


def _extract_from_owners(
    owners: list[tuple[dict[str, Any], list[tuple[str, dict[str, Any]]]]],
    target: ChatTarget,
    *,
    deref: Deref,
    source: str,
    variables_match: bool = False,
) -> Extraction:
    chosen = _choose_owners(owners, target, variables_match=variables_match)
    out = Extraction(owners_seen=len(owners), owners_used=len(chosen))
    groups: list[list[Message]] = []
    handle_info: PageInfo | None = None
    plain_info: PageInfo | None = None

    for owner, conns in chosen:
        info = _chat_info(owner, deref)
        out.chat = info if out.chat is None else out.chat.merged(info)
        for key, conn in conns:
            group: list[Message] = []
            edges = deref(conn.get("edges"))
            for edge in edges if isinstance(edges, list) else []:
                edge = deref(edge)
                node = deref(edge.get("node")) if isinstance(edge, dict) else None
                message = message_from_node(node, deref=deref, source=source, default_bot=info)
                if message is not None:
                    group.append(message)
            groups.append(group)
            page_info = PageInfo.from_dict(deref(conn.get("pageInfo")))
            if page_info is None:
                continue
            if _HANDLE_CONNECTION_KEY.match(key):
                handle_info = handle_info or page_info
            else:
                plain_info = plain_info or page_info

    out.messages = merge_messages(*groups)
    out.page_info = handle_info or plain_info
    return out


def _choose_owners(owners, target: ChatTarget, *, variables_match: bool):
    verdicts = [target.matches(owner) for owner, _ in owners]
    matched = [o for o, v in zip(owners, verdicts) if v is True]
    if matched:
        return matched
    unknown = [o for o, v in zip(owners, verdicts) if v is None]
    if variables_match and unknown:
        return unknown
    if len(unknown) == 1 and False not in verdicts:
        return unknown
    return []


def _chat_info(owner: dict[str, Any], deref: Deref) -> ChatInfo:
    bot = None
    for key in _BOT_KEYS:
        candidate = deref(owner.get(key))
        if isinstance(candidate, dict):
            bot = candidate
            break
    chat_id = owner.get("chatId")
    return ChatInfo(
        title=_opt_str(owner.get("title")),
        chat_code=_opt_str(owner.get("chatCode")),
        chat_id=chat_id if isinstance(chat_id, (int, str)) and chat_id != "" else None,
        node_id=_opt_str(owner.get("id")),
        bot_name=_opt_str((bot or {}).get("displayName")) or _opt_str((bot or {}).get("handle")),
        bot_handle=_opt_str((bot or {}).get("handle")),
        bot_nickname=_opt_str((bot or {}).get("nickname")),
    )


def _role(raw_author: str, node: dict[str, Any]) -> str:
    author = raw_author.strip().lower()
    if node.get("isChatAnnouncement") is True:
        return "system"
    if author == "human":
        return "human"
    if author in ("chat_break", "chatbreak"):
        return "chat_break"
    if not author:
        return "bot" if node.get("authorBot") else "unknown"
    return "bot"


def _bot_label(bot: Any, raw_author: str, default_bot: ChatInfo | None) -> str | None:
    """Display name of the answering bot, or None to fall back to the chat's bot."""
    nickname = None
    if isinstance(bot, dict):
        for key in ("displayName", "handle"):
            value = _opt_str(bot.get(key))
            if value:
                return value
        nickname = _opt_str(bot.get("nickname"))
    nickname = nickname or raw_author or None
    if default_bot is None or not default_bot.bot_name:
        return None
    if nickname is None or nickname == default_bot.bot_nickname:
        return default_bot.bot_name
    # A different bot (e.g. an @-mention) known only by its internal nickname.
    return nickname


def _attachments(node: dict[str, Any], deref: Deref, text: str) -> list[Attachment]:
    out: list[Attachment] = []
    seen: set[str] = set()
    raw = deref(node.get("attachments"))
    if isinstance(raw, dict):
        raw = [raw]
    for item in raw if isinstance(raw, list) else []:
        item = deref(item)
        if not isinstance(item, dict):
            continue
        file_info = deref(item.get("file"))
        file_info = file_info if isinstance(file_info, dict) else {}
        url = _opt_str(item.get("url")) or _opt_str(file_info.get("url")) or _opt_str(item.get("fileUrl"))
        if not url or url in seen or is_skip_attachment_url(url):
            continue
        name = _opt_str(item.get("name")) or _opt_str(file_info.get("name")) or guess_attachment_name(url)
        mime = (_opt_str(file_info.get("mimeType")) or _opt_str(item.get("mimeType")) or "").lower()
        if mime.startswith("image/"):
            kind = "image"
        elif mime.startswith(("video/", "audio/")):
            kind = "media"
        else:
            kind = guess_kind(url, name)
        out.append(Attachment(url=url, name=name, kind=kind))
        seen.add(url)
    for name, url in extract_urls_from_text(text):
        if url in seen or "poecdn" not in url.lower() or is_skip_attachment_url(url):
            continue
        out.append(Attachment(url=url, name=name, kind=guess_kind(url, name)))
        seen.add(url)
    return out


def _iter_dicts(data: Any) -> Iterator[dict[str, Any]]:
    stack = [data]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            yield value
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)


def _identity(value: Any) -> Any:
    return value


def _message_id(value: Any) -> int | str | None:
    if value is None or value == "" or isinstance(value, (dict, list, bool)):
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    return int(text) if text.isdigit() else text


def _id_key(value: Any) -> tuple[int, int, str]:
    if isinstance(value, int):
        return (0, value, "")
    return (1, 0, str(value))


def _oldest_key(messages: list[Message]) -> tuple[int, Any]:
    if not messages:
        return (1, (0, 0, ""))
    return (0, min(_id_key(m.message_id) for m in messages))


def _opt_str(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    text = str(value)
    return text if text else None


def _opt_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None
