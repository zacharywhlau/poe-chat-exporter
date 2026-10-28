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
_TAG_SALTS = [
    "4LxgHM6KpFqokX0Ox",
    "WpuLMiXEKKE98j56k",
]
_active_salt: str = _TAG_SALTS[0]


def _payload_json(query_name: str, variables: dict[str, Any]) -> str:
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
    if prev != digest:
        print(f"Learned GraphQL hash for {name}", file=sys.stderr)


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


def _walk_message_nodes(obj: Any) -> list[dict[str, Any]]:
    """Deep-scan a GraphQL JSON payload for message-like dicts."""
    found: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if "messageId" in value and (
                "text" in value or "author" in value or "contentType" in value
            ):
                found.append(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(obj)
    return found


def _sort_messages(messages: list[Message]) -> list[Message]:
    def sort_key(m: Message) -> tuple:
        try:
            t = int(m.creation_time_us or 0)
        except (TypeError, ValueError):
            t = 0
        try:
            mid = int(m.message_id) if m.message_id is not None else 0
        except (TypeError, ValueError):
            mid = 0
        return (t, mid)

    messages.sort(key=sort_key)
    return messages


def _chat_urls(chat: Chat) -> list[str]:
    urls: list[str] = []
    code = chat.chat_code
    handle = (chat.bot_handle or "").strip().lstrip("@")
    if code:
        urls.extend(
            [
                f"https://poe.com/c/{code}",
                f"https://poe.com/chat/{code}",
            ]
        )
        if handle:
            urls.extend(
                [
                    f"https://poe.com/{handle}/{code}",
                    f"https://poe.com/{handle}?chat={code}",
                ]
            )
    # De-dupe, preserve order
    seen: set[str] = set()
    out: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


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
        self._graphql_messages_ok = False

        self.page.on("request", self._on_request)
        print("Loading poe.com…", file=sys.stderr)
        self.page.goto(
            "https://poe.com",
            wait_until="domcontentloaded",
            timeout=90_000,
        )
        try:
            self.page.wait_for_load_state("load", timeout=30_000)
        except Exception:
            pass

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
        retries: int = 3,
    ) -> dict[str, Any]:
        if query_name not in QUERIES:
            raise KeyError(f"Unknown query {query_name!r}")

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
                        credentials: "include",
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
                        f"PersistedQueryNotFound for {query_name}."
                    )
                if attempt <= retries and any(
                    x in err_text.lower() for x in ("rate", "limit", "throttle")
                ):
                    time.sleep(5 * attempt)
                    continue
                raise RuntimeError(f"GraphQL errors: {err_text}")

            return data

    def harvest_chat_messages(
        self,
        chat: Chat,
        *,
        scroll_pages: int = 20,
    ) -> list[Message]:
        """Open the chat in the browser and collect messages from live gql traffic."""
        by_id: dict[Any, Message] = {}
        gql_hits = 0

        def on_response(response: Any) -> None:
            nonlocal gql_hits
            if "gql_POST" not in response.url:
                return
            gql_hits += 1
            try:
                data = response.json()
            except Exception:
                return
            for node in _walk_message_nodes(data):
                msg = _message_from_node(node)
                key = (
                    msg.message_id
                    if msg.message_id is not None
                    else (msg.author, msg.text[:80], msg.creation_time_us)
                )
                by_id[key] = msg

        self.page.on("response", on_response)
        try:
            loaded_url = None
            for url in _chat_urls(chat):
                print(f"Opening {url}", file=sys.stderr)
                try:
                    self.page.goto(url, wait_until="domcontentloaded", timeout=90_000)
                except Exception as exc:
                    print(f"  navigation error: {exc}", file=sys.stderr)
                    continue
                try:
                    self.page.wait_for_load_state("load", timeout=20_000)
                except Exception:
                    pass
                self.page.wait_for_timeout(2500)
                if by_id or gql_hits > 0:
                    loaded_url = url
                    break
                # Still try next URL pattern if nothing useful arrived

            if not loaded_url and _chat_urls(chat):
                # Stay on last attempted URL and keep waiting/scrolling
                loaded_url = self.page.url
                print(
                    f"No messages yet; continuing on {loaded_url}",
                    file=sys.stderr,
                )

            for i in range(scroll_pages):
                before = len(by_id)
                self.page.evaluate(
                    """() => {
                        const nodes = Array.from(document.querySelectorAll('*'));
                        let best = document.scrollingElement;
                        let bestOverflow = 0;
                        for (const el of nodes) {
                          const style = getComputedStyle(el);
                          const oy = style.overflowY;
                          if ((oy === 'auto' || oy === 'scroll') &&
                              el.scrollHeight > el.clientHeight + 50) {
                            const score = el.scrollHeight - el.clientHeight;
                            if (score > bestOverflow) {
                              bestOverflow = score;
                              best = el;
                            }
                          }
                        }
                        if (best) best.scrollTop = 0;
                        window.scrollTo(0, 0);
                    }"""
                )
                self.page.wait_for_timeout(1000)
                if len(by_id) == before:
                    self.page.wait_for_timeout(1500)
                    if len(by_id) == before and i > 2:
                        break

            print(
                f"Harvested {len(by_id)} message(s) "
                f"from {gql_hits} gql response(s)",
                file=sys.stderr,
            )
        finally:
            self.page.remove_listener("response", on_response)

        return _sort_messages(list(by_id.values()))


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
            handle = (
                bot_obj.get("handle")
                or bot_obj.get("nickname")
                or node.get("defaultBotNickname")
                or ""
            )
            chats.append(
                Chat(
                    chat_id=node.get("chatId"),
                    chat_code=node.get("chatCode") or "",
                    node_id=node["id"],
                    title=node.get("title") or "Untitled",
                    bot=(
                        bot_obj.get("displayName")
                        or handle
                        or "unknown"
                    ),
                    bot_handle=str(handle or ""),
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


def _fetch_messages_graphql(client: PoeClient, chat: Chat) -> list[Message]:
    batches: list[list[Message]] = []
    cursor: str | None = None

    while True:
        variables: dict[str, Any] = {
            "count": 100,
            "id": chat.node_id,
        }
        if cursor is not None:
            variables["cursor"] = cursor

        data = client.gql_request("ChatListPaginationQuery", variables)
        chat_data = data["data"]["node"]
        msg_conn = chat_data["messagesConnection"]
        edges = msg_conn.get("edges") or []
        page_info = msg_conn.get("pageInfo") or {}

        page_messages = [
            _message_from_node(edge.get("node") or {}) for edge in reversed(edges)
        ]
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


def fetch_messages(client: PoeClient, chat: Chat) -> list[Message]:
    """Prefer browser chat-page harvest; use GraphQL only after it has proven OK."""
    if client._graphql_messages_ok:
        try:
            return _fetch_messages_graphql(client, chat)
        except Exception as exc:  # noqa: BLE001
            print(
                f"GraphQL message fetch failed, falling back to page harvest: {exc}",
                file=sys.stderr,
            )

    messages = client.harvest_chat_messages(chat)
    if messages:
        # After a successful harvest, try enabling fast GraphQL for later chats.
        if not client._graphql_messages_ok:
            try:
                gql_msgs = _fetch_messages_graphql(client, chat)
                if gql_msgs:
                    client._graphql_messages_ok = True
                    print(
                        "GraphQL message fetch OK — using it for remaining chats",
                        file=sys.stderr,
                    )
                    return gql_msgs
            except Exception as exc:  # noqa: BLE001
                print(
                    f"GraphQL still unavailable ({exc}); "
                    "continuing with page harvest per chat",
                    file=sys.stderr,
                )
        return messages

    # Last resort: GraphQL even if harvest was empty
    try:
        messages = _fetch_messages_graphql(client, chat)
        if messages:
            client._graphql_messages_ok = True
            return messages
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"No messages harvested for '{chat.title}' "
            f"(code={chat.chat_code}, handle={chat.bot_handle or '?'}). "
            f"GraphQL also failed: {exc}"
        ) from exc

    raise RuntimeError(
        f"No messages found for '{chat.title}' "
        f"(code={chat.chat_code}). Try --headed and confirm the chat opens."
    )


def open_client(
    token: str,
    lat: str | None = None,
    headless: bool = True,
):
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
