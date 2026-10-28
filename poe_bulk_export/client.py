from __future__ import annotations

import hashlib
import json
import sys
import time
from typing import Any

from playwright.sync_api import Playwright, sync_playwright

from poe_bulk_export.gql_hashes import QUERIES
from poe_bulk_export.models import Attachment, Chat, Message
from poe_bulk_export.util import extract_urls_from_text, guess_attachment_name, guess_kind

# Poe signs each gql_POST body with md5(body + formkey + salt).
# Salt has changed historically; we also learn it from live browser traffic.
_TAG_SALTS = [
    "4LxgHM6KpFqokX0Ox",
    "WpuLMiXEKKE98j56k",
]
_active_salt: str = _TAG_SALTS[0]


def _payload_json(query_name: str, variables: dict[str, Any]) -> str:
    """Compact JSON matching Poe client signing (orjson-style, no spaces)."""
    payload = {
        "queryName": query_name,
        "variables": variables,
        "extensions": {"hash": QUERIES[query_name]},
    }
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _poe_tag_id(payload_str: str, formkey: str, salt: str | None = None) -> str:
    return hashlib.md5(
        (payload_str + formkey + (salt or _active_salt)).encode("utf-8")
    ).hexdigest()


def _learn_salt(payload_str: str, formkey: str, tag_id: str) -> str | None:
    global _active_salt
    for salt in _TAG_SALTS:
        if _poe_tag_id(payload_str, formkey, salt) == tag_id:
            if salt != _active_salt:
                print(f"Learned poe-tag salt: {salt[:6]}…", file=sys.stderr)
            _active_salt = salt
            return salt
    return None


def _update_hash_from_payload(payload: dict[str, Any]) -> None:
    name = payload.get("queryName")
    extensions = payload.get("extensions") or {}
    digest = extensions.get("hash")
    if not name or not digest:
        return
    prev = QUERIES.get(name)
    QUERIES[name] = digest
    if prev and prev != digest:
        print(f"Updated GraphQL hash for {name}", file=sys.stderr)
    elif not prev:
        print(f"Learned GraphQL hash for {name}", file=sys.stderr)


def _message_from_node(node: dict[str, Any]) -> Message:
    text = node.get("text") or ""
    return Message(
        author=node.get("author") or "unknown",
        text=text,
        message_id=node.get("messageId"),
        content_type=node.get("contentType"),
        creation_time_us=node.get("creationTime"),
        attachments=_attachments_from_node(node, text),
    )


def _extract_message_nodes(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull message nodes from common Poe GraphQL response shapes."""
    nodes: list[dict[str, Any]] = []

    def from_connection(conn: Any) -> None:
        if not isinstance(conn, dict):
            return
        for edge in conn.get("edges") or []:
            node = (edge or {}).get("node")
            if isinstance(node, dict) and (
                "messageId" in node or "author" in node or "text" in node
            ):
                nodes.append(node)

    root = data.get("data") or {}
    if not isinstance(root, dict):
        return nodes

    node = root.get("node")
    if isinstance(node, dict):
        from_connection(node.get("messagesConnection"))

    for key in ("chatOfCode", "chat", "chatOfId"):
        chat_obj = root.get(key)
        if isinstance(chat_obj, dict):
            from_connection(chat_obj.get("messagesConnection"))

    viewer = root.get("viewer")
    if isinstance(viewer, dict):
        for key, val in viewer.items():
            if isinstance(val, dict) and "messagesConnection" in val:
                from_connection(val.get("messagesConnection"))

    return nodes


class PoeClient:
    """Poe GraphQL client via Playwright (Cloudflare + session cookies)."""

    def __init__(
        self,
        playwright: Playwright,
        token: str,
        lat: str | None = None,
        headless: bool = True,
    ) -> None:
        self.browser = playwright.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self.context = self.browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        cookies: list[dict[str, Any]] = [
            {
                "name": "p-b",
                "value": token,
                "domain": "poe.com",
                "path": "/",
            }
        ]
        if lat:
            cookies.append(
                {
                    "name": "p-lat",
                    "value": lat,
                    "domain": "poe.com",
                    "path": "/",
                }
            )
        self.context.add_cookies(cookies)
        self.page = self.context.new_page()
        self._headers: dict[str, str] | None = None
        self.formkey = ""
        self._calibrated = False

        self.page.on("request", self._on_request)
        print("Loading poe.com…", file=sys.stderr)
        # Poe keeps background traffic open, so networkidle often never settles.
        self.page.goto(
            "https://poe.com",
            wait_until="domcontentloaded",
            timeout=90_000,
        )
        try:
            self.page.wait_for_load_state("load", timeout=30_000)
        except Exception:
            pass

        # Wait briefly for the SPA to issue a gql_POST so we can copy poe-* headers.
        for _ in range(20):
            if self._headers and self.formkey:
                break
            self.page.wait_for_timeout(500)

        if self.formkey:
            print(f"Connected (formkey: {self.formkey[:8]}…)", file=sys.stderr)
        else:
            print(
                "Warning: could not capture poe-formkey; GraphQL may fail. "
                "Try: poe-bulk-export list --headed",
                file=sys.stderr,
            )

    def _on_request(self, request: Any) -> None:
        if "gql_POST" not in request.url:
            return

        headers = {
            k: v
            for k, v in request.headers.items()
            if k.startswith("poe-") and k != "poe-tag-id"
        }
        if headers and self._headers is None:
            self._headers = headers
        if headers.get("poe-formkey"):
            self.formkey = headers["poe-formkey"]

        post_data = request.post_data
        if not post_data:
            return
        try:
            payload = json.loads(post_data)
        except json.JSONDecodeError:
            return
        if isinstance(payload, dict):
            _update_hash_from_payload(payload)

        tag = request.headers.get("poe-tag-id")
        formkey = request.headers.get("poe-formkey") or self.formkey
        if tag and formkey:
            _learn_salt(post_data, formkey, tag)

    def close(self) -> None:
        self.browser.close()

    def gql_request(
        self,
        query_name: str,
        variables: dict[str, Any],
        *,
        retries: int = 5,
    ) -> dict[str, Any]:
        if query_name not in QUERIES:
            raise KeyError(
                f"Unknown query {query_name!r}. Open a chat once so the hash "
                "can be learned, or add it in gql_hashes.py."
            )

        payload_str = _payload_json(query_name, variables)
        headers = dict(self._headers or {})
        headers["Content-Type"] = "application/json"
        headers["poe-queryname"] = query_name
        if self.formkey:
            headers["poe-formkey"] = self.formkey
            headers["poe-tag-id"] = _poe_tag_id(payload_str, self.formkey)

        attempt = 0
        while True:
            attempt += 1
            result = self.page.evaluate(
                """async ([payloadStr, headers]) => {
                    const resp = await fetch("/api/gql_POST", {
                        method: "POST",
                        headers: headers,
                        body: payloadStr,
                    });
                    return {status: resp.status, body: await resp.text()};
                }""",
                [payload_str, headers],
            )

            status = result["status"]
            body = result["body"]

            if status == 429:
                wait = min(30, 5 * attempt)
                print(
                    f"Rate limited on {query_name}; waiting {wait}s…",
                    file=sys.stderr,
                )
                time.sleep(wait)
                if attempt <= retries:
                    continue
                raise RuntimeError(f"Rate limited after {retries} retries")

            if status in (502, 503, 504) and attempt <= retries:
                time.sleep(2 * attempt)
                continue

            if status != 200:
                raise RuntimeError(
                    f"Request failed ({status}) for {query_name}: "
                    f"{body[:400] if body else '(empty body)'}"
                )

            data = json.loads(body)
            if "errors" in data:
                err_text = json.dumps(data["errors"])
                if "PersistedQueryNotFound" in err_text:
                    raise RuntimeError(
                        f"PersistedQueryNotFound for {query_name}. "
                        "Update the hash in poe_bulk_export/gql_hashes.py "
                        "or open a chat so a live hash can be learned."
                    )
                if attempt <= retries and any(
                    x in err_text.lower() for x in ("rate", "limit", "throttle")
                ):
                    time.sleep(5 * attempt)
                    continue
                raise RuntimeError(f"GraphQL errors: {err_text}")

            return data

    def calibrate_message_queries(self, chat: Chat) -> list[Message]:
        """Open one chat in the browser to learn live hashes/salt and harvest messages."""
        print(
            f"Calibrating message API via chat page ({chat.chat_code or chat.chat_id})…",
            file=sys.stderr,
        )
        harvested = self._harvest_via_navigation(chat, scroll_pages=8)
        self._calibrated = True
        if "ChatListPaginationQuery" in QUERIES:
            print(
                f"ChatListPaginationQuery hash ready "
                f"({QUERIES['ChatListPaginationQuery'][:10]}…)",
                file=sys.stderr,
            )
        return harvested

    def _harvest_via_navigation(
        self,
        chat: Chat,
        *,
        scroll_pages: int = 15,
    ) -> list[Message]:
        by_id: dict[Any, Message] = {}

        def on_response(response: Any) -> None:
            if "gql_POST" not in response.url:
                return
            try:
                data = response.json()
            except Exception:
                return
            if not isinstance(data, dict):
                return
            for node in _extract_message_nodes(data):
                msg = _message_from_node(node)
                key = msg.message_id if msg.message_id is not None else id(msg)
                by_id[key] = msg

        self.page.on("response", on_response)
        try:
            targets = []
            if chat.chat_code:
                targets.append(f"https://poe.com/chat/{chat.chat_code}")
            targets.append(f"https://poe.com/{chat.chat_code}" if chat.chat_code else "")
            targets = [t for t in targets if t]

            loaded = False
            for url in targets:
                try:
                    self.page.goto(url, wait_until="domcontentloaded", timeout=90_000)
                    loaded = True
                    break
                except Exception as exc:
                    print(f"Navigation failed for {url}: {exc}", file=sys.stderr)
            if not loaded:
                return []

            try:
                self.page.wait_for_load_state("load", timeout=20_000)
            except Exception:
                pass
            self.page.wait_for_timeout(2000)

            for _ in range(scroll_pages):
                before = len(by_id)
                self.page.evaluate(
                    """() => {
                        const candidates = [
                          ...document.querySelectorAll(
                            '[class*="Message"], [class*="ChatMessage"], main, [class*="infinite"]'
                          )
                        ];
                        const el = candidates.find(e => e.scrollHeight > e.clientHeight)
                                   || document.scrollingElement;
                        if (el) el.scrollTop = 0;
                        window.scrollTo(0, 0);
                    }"""
                )
                self.page.wait_for_timeout(900)
                if len(by_id) == before:
                    self.page.wait_for_timeout(1100)
                    if len(by_id) == before:
                        break
        finally:
            self.page.remove_listener("response", on_response)

        messages = list(by_id.values())

        def sort_key(m: Message) -> tuple:
            t = m.creation_time_us or 0
            try:
                t = int(t)
            except (TypeError, ValueError):
                t = 0
            mid = m.message_id or 0
            try:
                mid = int(mid)
            except (TypeError, ValueError):
                mid = 0
            return (t, mid)

        messages.sort(key=sort_key)
        return messages


def list_chats(client: PoeClient, limit: int | None = None) -> list[Chat]:
    chats: list[Chat] = []
    cursor: str | None = None

    while True:
        variables: dict[str, Any] = {"count": 50}
        if cursor:
            variables["cursor"] = cursor

        data = client.gql_request("ChatHistoryListPaginationQuery", variables)
        chats_data = data["data"]["chats"]
        edges = chats_data.get("edges") or []
        page_info = chats_data.get("pageInfo") or {}

        for edge in edges:
            node = edge.get("node") or {}
            bot_obj = node.get("defaultBotObject") or {}
            chats.append(
                Chat(
                    chat_id=node.get("chatId"),
                    chat_code=node.get("chatCode") or "",
                    node_id=node["id"],
                    title=node.get("title") or "Untitled",
                    bot=(
                        bot_obj.get("displayName")
                        or node.get("defaultBotNickname")
                        or "unknown"
                    ),
                )
            )
            if limit is not None and len(chats) >= limit:
                return chats

        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")
        if not cursor:
            break

    return chats


def _attachments_from_node(node: dict[str, Any], text: str) -> list[Attachment]:
    attachments: list[Attachment] = []
    seen: set[str] = set()

    raw_list = node.get("attachments") or node.get("fileAttachments") or []
    if isinstance(raw_list, list):
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            url = (
                item.get("url")
                or item.get("fileUrl")
                or item.get("attachmentUrl")
                or item.get("downloadUrl")
                or ""
            )
            if not url or url in seen:
                continue
            seen.add(url)
            name = (
                item.get("name")
                or item.get("filename")
                or guess_attachment_name(url)
            )
            attachments.append(
                Attachment(url=url, name=name, kind=guess_kind(url, name))
            )

    for name, url in extract_urls_from_text(text):
        if url in seen:
            continue
        if not any(x in url.lower() for x in ("poecdn", "poe.com")):
            continue
        seen.add(url)
        attachments.append(
            Attachment(url=url, name=name, kind=guess_kind(url, name))
        )

    return attachments


def _fetch_messages_graphql(client: PoeClient, chat: Chat) -> list[Message]:
    """Fetch messages oldest→newest via ChatListPaginationQuery."""
    batches: list[list[Message]] = []
    cursor: str | None = None

    while True:
        variables: dict[str, Any] = {
            "count": 100,
            "id": chat.node_id,
        }
        # Some Poe builds reject explicit null cursors.
        if cursor is not None:
            variables["cursor"] = cursor

        data = client.gql_request("ChatListPaginationQuery", variables)
        chat_data = data["data"]["node"]
        msg_conn = chat_data["messagesConnection"]
        edges = msg_conn.get("edges") or []
        page_info = msg_conn.get("pageInfo") or {}

        page_messages: list[Message] = []
        for edge in reversed(edges):
            node = edge.get("node") or {}
            page_messages.append(_message_from_node(node))
        batches.append(page_messages)

        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("startCursor")
        if not cursor:
            break

    messages: list[Message] = []
    for batch in reversed(batches):
        messages.extend(batch)
    return messages


def _fetch_messages_chat_page_query(client: PoeClient, chat: Chat) -> list[Message]:
    if "ChatPageQuery" not in QUERIES or not chat.chat_code:
        raise RuntimeError("ChatPageQuery hash/chatCode unavailable")
    data = client.gql_request("ChatPageQuery", {"chatCode": chat.chat_code})
    nodes = _extract_message_nodes(data)
    messages = [_message_from_node(n) for n in nodes]
    # ChatPageQuery returns newest-first edges typically; sort chronologically
    messages.sort(
        key=lambda m: (
            int(m.creation_time_us or 0),
            int(m.message_id or 0) if str(m.message_id).isdigit() else 0,
        )
    )
    return messages


def fetch_messages(client: PoeClient, chat: Chat) -> list[Message]:
    """Fetch all messages for a chat, calibrating/falling back if GraphQL 400s."""
    errors: list[str] = []

    if client._calibrated or "ChatListPaginationQuery" in QUERIES:
        try:
            return _fetch_messages_graphql(client, chat)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"ChatListPaginationQuery: {exc}")

    try:
        return _fetch_messages_chat_page_query(client, chat)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"ChatPageQuery: {exc}")

    # Learn live hashes/salt from the real chat page, keep harvested messages.
    harvested = client.calibrate_message_queries(chat)
    if harvested:
        return harvested

    # Retry GraphQL now that hashes may have been updated from navigation.
    try:
        return _fetch_messages_graphql(client, chat)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"ChatListPaginationQuery(after calibrate): {exc}")

    raise RuntimeError(
        "Failed to fetch messages for "
        f"'{chat.title}' ({chat.chat_code}). "
        + " | ".join(errors)
    )


def open_client(
    token: str,
    lat: str | None = None,
    headless: bool = True,
):
    """Context-manager style helper: yields (playwright, client)."""

    class _Ctx:
        def __enter__(self):
            self._pw = sync_playwright().start()
            self.client = PoeClient(self._pw, token, lat=lat, headless=headless)
            return self.client

        def __exit__(self, exc_type, exc, tb):
            try:
                self.client.close()
            finally:
                self._pw.stop()
            return False

    return _Ctx()
