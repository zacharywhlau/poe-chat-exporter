from __future__ import annotations

import hashlib
import json
import sys
import time
from typing import Any

from playwright.sync_api import Playwright, sync_playwright

from poe_bulk_export.gql_hashes import QUERIES
from poe_bulk_export.models import Attachment, Chat, Message
from poe_bulk_export.util import extract_urls_from_text, guess_kind, guess_attachment_name

# Poe signs each gql_POST body with md5(body + formkey + salt).
# Reusing a tag from a different request yields HTTP 400.
_POE_TAG_SALT = "4LxgHM6KpFqokX0Ox"


def _payload_json(query_name: str, variables: dict[str, Any]) -> str:
    """Compact JSON matching Poe client signing (orjson-style, no spaces)."""
    payload = {
        "queryName": query_name,
        "variables": variables,
        "extensions": {"hash": QUERIES[query_name]},
    }
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _poe_tag_id(payload_str: str, formkey: str) -> str:
    return hashlib.md5(
        (payload_str + formkey + _POE_TAG_SALT).encode("utf-8")
    ).hexdigest()


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

        def on_request(request: Any) -> None:
            if "gql_POST" in request.url and self._headers is None:
                # Keep poe-* headers except tag-id (must be signed per body).
                self._headers = {
                    k: v
                    for k, v in request.headers.items()
                    if k.startswith("poe-") and k != "poe-tag-id"
                }

        self.page.on("request", on_request)
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
            if self._headers:
                break
            self.page.wait_for_timeout(500)

        self.formkey = (self._headers or {}).get("poe-formkey", "")
        if self.formkey:
            print(f"Connected (formkey: {self.formkey[:8]}…)", file=sys.stderr)
        else:
            print(
                "Warning: could not capture poe-formkey; GraphQL may fail. "
                "Try: poe-bulk-export list --headed",
                file=sys.stderr,
            )

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
                f"Unknown query {query_name!r}. Add its hash in gql_hashes.py."
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
                    f"Request failed ({status}) for {query_name}: {body[:400]}"
                )

            data = json.loads(body)
            if "errors" in data:
                err_text = json.dumps(data["errors"])
                if "PersistedQueryNotFound" in err_text:
                    raise RuntimeError(
                        f"PersistedQueryNotFound for {query_name}. "
                        "Update the hash in poe_bulk_export/gql_hashes.py."
                    )
                if attempt <= retries and any(
                    x in err_text.lower() for x in ("rate", "limit", "throttle")
                ):
                    time.sleep(5 * attempt)
                    continue
                raise RuntimeError(f"GraphQL errors: {err_text}")

            return data


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
        # Prefer structured attachments; only add CDN-ish leftovers from text
        if not any(x in url.lower() for x in ("poecdn", "poe.com")):
            continue
        seen.add(url)
        attachments.append(
            Attachment(url=url, name=name, kind=guess_kind(url, name))
        )

    return attachments


def fetch_messages(client: PoeClient, chat: Chat) -> list[Message]:
    """Fetch messages oldest→newest (API returns newest pages first)."""
    batches: list[list[Message]] = []
    cursor: str | None = None

    while True:
        variables: dict[str, Any] = {
            "count": 100,
            "cursor": cursor,
            "id": chat.node_id,
        }
        data = client.gql_request("ChatListPaginationQuery", variables)
        chat_data = data["data"]["node"]
        msg_conn = chat_data["messagesConnection"]
        edges = msg_conn.get("edges") or []
        page_info = msg_conn.get("pageInfo") or {}

        page_messages: list[Message] = []
        # Edges arrive newest-first; reverse within page for chronological order
        for edge in reversed(edges):
            node = edge.get("node") or {}
            text = node.get("text") or ""
            page_messages.append(
                Message(
                    author=node.get("author") or "unknown",
                    text=text,
                    message_id=node.get("messageId"),
                    content_type=node.get("contentType"),
                    creation_time_us=node.get("creationTime"),
                    attachments=_attachments_from_node(node, text),
                )
            )
        batches.append(page_messages)

        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("startCursor")
        if not cursor:
            break

    # Batches are newest page first; reverse so oldest batch is first
    messages: list[Message] = []
    for batch in reversed(batches):
        messages.extend(batch)
    return messages


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
