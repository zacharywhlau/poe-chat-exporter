from __future__ import annotations

import hashlib
import json
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Playwright, sync_playwright

from poe_bulk_export import page_scripts
from poe_bulk_export.dom_fallback import messages_from_dom
from poe_bulk_export.extract import (
    ChatInfo,
    ChatTarget,
    Extraction,
    PageInfo,
    combine_extractions,
    extract_from_graphql,
    extract_from_next_data,
    extract_from_relay_records,
    find_chat_info,
    parse_graphql_body,
)
from poe_bulk_export.gql_hashes import QUERIES
from poe_bulk_export.models import Chat, Message
from poe_bulk_export.util import coerce_poe_time_us

Log = Callable[[str], None]

# Poe signs each gql_POST body with md5(body + formkey + salt).
_TAG_SALTS = [
    "4LxgHM6KpFqokX0Ox",
    "WpuLMiXEKKE98j56k",
]
_active_salt: str = _TAG_SALTS[0]


class NotLoggedInError(RuntimeError):
    pass


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
            _active_salt = salt
            return salt
    return None


def _update_hash_from_payload(payload: dict[str, Any]) -> None:
    name = payload.get("queryName")
    digest = (payload.get("extensions") or {}).get("hash")
    if name and digest:
        QUERIES[name] = digest


def normalize_user_agent(user_agent: str) -> str:
    """Headless Chromium's UA with the "HeadlessChrome" giveaway removed."""
    return (user_agent or "").replace("HeadlessChrome/", "Chrome/")


def _query_meta(post_data: str | None, headers: dict[str, str] | None = None) -> tuple[str | None, dict[str, Any] | None]:
    name = (headers or {}).get("poe-queryname")
    variables = None
    if post_data:
        try:
            payload = json.loads(post_data)
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            name = payload.get("queryName") or name
            if isinstance(payload.get("variables"), dict):
                variables = payload["variables"]
    return name, variables


def _chat_urls(chat: Chat) -> list[str]:
    """Candidate URLs for a chat; /chat/{code} is the current canonical one."""
    code = chat.chat_code
    if not code:
        return []
    urls = [f"https://poe.com/chat/{code}"]
    handle = (chat.bot_handle or "").strip().lstrip("@")
    if handle:
        urls.append(f"https://poe.com/{handle}/{code}")
    return urls


@dataclass
class NetworkCapture:
    url: str
    query_name: str | None
    variables: dict[str, Any] | None
    status: int
    content_type: str
    payloads: list[dict[str, Any]]
    raw_body: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "url": self.url,
            "queryName": self.query_name,
            "variables": self.variables,
            "status": self.status,
            "contentType": self.content_type,
            "payloads": self.payloads,
        }
        if self.raw_body is not None:
            out["rawBody"] = self.raw_body
        return out


@dataclass
class HarvestResult:
    messages: list[Message]
    complete: bool | None
    source: str  # raw | dom-fallback | none
    counts: dict[str, int]
    chat: ChatInfo | None
    url: str
    pages_loaded: int = 0
    graphql_pages: int = 0
    elapsed_s: float = 0.0
    notes: list[str] = field(default_factory=list)
    raw: dict[str, Any] | None = None

    @property
    def unknown_authors(self) -> int:
        """Messages whose author could not be recognised as you, a bot or Poe."""
        return sum(1 for m in self.messages if m.author == "unknown")

    @property
    def degraded(self) -> bool:
        """Written, but worth a warning: history, formatting or speakers may be off."""
        return self.complete is not True or self.source != "raw" or self.unknown_authors > 0

    def summary(self) -> str:
        sources = ", ".join(f"{k}={v}" for k, v in self.counts.items() if v)
        if self.complete is True:
            state = "complete"
        elif self.complete is False:
            state = "INCOMPLETE (older messages could not be loaded)"
        else:
            state = "completeness unknown"
        if self.source == "dom-fallback":
            state += ", DOM fallback (formatting may be lossy)"
        if self.unknown_authors:
            n = self.unknown_authors
            state += f", {n} message{'' if n == 1 else 's'} with unknown author"
        text = f"{len(self.messages)} messages"
        if sources:
            text += f" ({sources})"
        return f"{text}, {state}"


class PoeClient:
    """A logged-in (or anonymous) Poe browser session driven by Playwright."""

    def __init__(
        self,
        playwright: Playwright,
        token: str | None,
        lat: str | None = None,
        headless: bool = True,
        warmup: bool = True,
    ) -> None:
        self.browser = playwright.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self.user_agent = self._detect_user_agent()
        self.context = self.browser.new_context(
            user_agent=self.user_agent,
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )
        cookies: list[dict[str, Any]] = []
        if token:
            cookies.append({"name": "p-b", "value": token, "domain": "poe.com", "path": "/"})
        if lat:
            cookies.append({"name": "p-lat", "value": lat, "domain": "poe.com", "path": "/"})
        if cookies:
            self.context.add_cookies(cookies)
        self.cookies = {c["name"]: c["value"] for c in cookies}
        self.page = self.context.new_page()
        self._headers: dict[str, str] | None = None
        self.formkey = ""
        self._pagination_variables: dict[str, Any] | None = None
        self.page.on("request", self._on_request)
        if warmup:
            self._warmup()

    def _detect_user_agent(self) -> str:
        try:
            probe = self.browser.new_context()
            try:
                ua = probe.new_page().evaluate("navigator.userAgent")
            finally:
                probe.close()
            if ua:
                return normalize_user_agent(ua)
        except PlaywrightError:
            pass
        major = (self.browser.version or "0").split(".")[0]
        return (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"
        )

    def _warmup(self) -> None:
        print("Loading poe.com…", file=sys.stderr)
        self.page.goto("https://poe.com", wait_until="domcontentloaded", timeout=90_000)
        if "/login" in self.page.url:
            raise NotLoggedInError(
                "Poe redirected to the login page: the p-b cookie is missing or expired. "
                "Copy fresh p-b (and p-lat) values from your browser."
            )
        for _ in range(40):
            if self._headers and self.formkey:
                break
            self.page.wait_for_timeout(250)
        if self.formkey:
            print("Connected.", file=sys.stderr)
        else:
            print(
                "Warning: could not capture poe-formkey; chat listing may fail. "
                "Try again with --headed.",
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
            if payload.get("queryName") == "ChatListPaginationQuery" and isinstance(
                payload.get("variables"), dict
            ):
                self._pagination_variables = dict(payload["variables"])

        tag = request.headers.get("poe-tag-id")
        formkey = request.headers.get("poe-formkey") or self.formkey
        if tag and formkey:
            _learn_salt(post_data, formkey, tag)

    def close(self) -> None:
        self.browser.close()

    # ------------------------------------------------------------------ #
    # GraphQL
    # ------------------------------------------------------------------ #

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
            result = self._safe_evaluate(
                """async ([payloadStr, headers]) => {
                    const resp = await fetch("/api/gql_POST", {
                        method: "POST",
                        headers: headers,
                        body: payloadStr,
                        credentials: "include",
                    });
                    return {
                        status: resp.status,
                        contentType: resp.headers.get("content-type") || "",
                        body: await resp.text(),
                    };
                }""",
                [payload_str, headers],
            )
            status = result["status"]
            body = result["body"]

            if status == 429:
                wait = min(30, 5 * attempt)
                print(f"Rate limited on {query_name}; waiting {wait}s…", file=sys.stderr)
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

            payloads = parse_graphql_body(body, result.get("contentType"))
            if not payloads:
                raise RuntimeError(f"Unreadable response for {query_name}: {body[:200]!r}")
            data = payloads[0]
            if data.get("errors") and not data.get("data"):
                err_text = json.dumps(data["errors"])
                if "PersistedQueryNotFound" in err_text:
                    raise RuntimeError(
                        f"PersistedQueryNotFound for {query_name}: Poe changed this query's hash."
                    )
                if attempt <= retries and any(
                    x in err_text.lower() for x in ("rate", "limit", "throttle")
                ):
                    time.sleep(5 * attempt)
                    continue
                raise RuntimeError(f"GraphQL errors: {err_text}")
            return data

    # ------------------------------------------------------------------ #
    # Page helpers
    # ------------------------------------------------------------------ #

    def _wait_for_navigation_settle(self, quiet_ms: int = 800, timeout_ms: int = 20_000) -> None:
        deadline = time.time() + timeout_ms / 1000
        last = self.page.url
        stable_since = time.time()
        while time.time() < deadline:
            try:
                self.page.wait_for_load_state("domcontentloaded", timeout=3_000)
            except PlaywrightError:
                pass
            self.page.wait_for_timeout(200)
            current = self.page.url
            if current != last:
                last = current
                stable_since = time.time()
                continue
            if (time.time() - stable_since) * 1000 >= quiet_ms:
                return

    def _safe_evaluate(self, expression: str, arg: Any = None, retries: int = 5) -> Any:
        """page.evaluate that retries when Poe navigates mid-call."""
        last_exc: Exception | None = None
        for _ in range(retries):
            try:
                if arg is None:
                    return self.page.evaluate(expression)
                return self.page.evaluate(expression, arg)
            except PlaywrightError as exc:
                last_exc = exc
                msg = str(exc).lower()
                if "context was destroyed" in msg or "navigation" in msg:
                    self._wait_for_navigation_settle()
                    continue
                raise
        if last_exc:
            raise last_exc
        return None

    def _probe(self, target: ChatTarget) -> dict[str, Any]:
        try:
            return self._safe_evaluate(page_scripts.PROBE_JS, target.as_js()) or {}
        except PlaywrightError:
            return {}

    def _wait_until_ready(self, target: ChatTarget, *, timeout_s: float = 25.0) -> dict[str, Any]:
        """Poll until the Relay store holds this chat's messages (or give up)."""
        started = time.monotonic()
        probe: dict[str, Any] = {}
        while time.monotonic() - started < timeout_s:
            probe = self._probe(target)
            store = probe.get("store") or {}
            if store.get("messageCount"):
                return probe
            elapsed = time.monotonic() - started
            # No Relay environment, but server data is there: give hydration a moment.
            if probe.get("hasNextData") and not probe.get("envFound") and elapsed > 8:
                return probe
            if probe.get("envFound") and elapsed > 12:
                return probe
            self.page.wait_for_timeout(250)
        return probe

    # ------------------------------------------------------------------ #
    # Harvest
    # ------------------------------------------------------------------ #

    def harvest(
        self,
        target: ChatTarget,
        urls: list[str],
        *,
        max_pages: int = 200,
        capture_raw: bool = False,
        log: Log | None = None,
    ) -> HarvestResult:
        """Open a chat page and return its messages exactly as Poe stores them."""
        log = log or (lambda _msg: None)
        started = time.monotonic()
        captures: list[NetworkCapture] = []
        notes: list[str] = []

        def on_response(response: Any) -> None:
            capture = self._capture_response(response, keep_raw=capture_raw)
            if capture is not None:
                captures.append(capture)

        self.page.on("response", on_response)
        try:
            probe = self._open(target, urls, log)
            final_url = self.page.url

            next_data = self._safe_evaluate(page_scripts.NEXT_DATA_JS)
            next_ex = extract_from_next_data(next_data, target)
            target = target.enriched(next_ex.chat)

            store_status = probe.get("store") or {}
            page_info = PageInfo.from_dict(store_status.get("pageInfo")) or next_ex.page_info
            pages_loaded = 0
            scroll_log: list[dict[str, Any]] = []
            if probe.get("envFound") and (page_info is None or page_info.has_previous_page):
                pages_loaded, scroll_log = self._load_older_by_scrolling(
                    target, page_info, max_pages=max_pages, log=log
                )

            snapshot = self._safe_evaluate(page_scripts.SNAPSHOT_JS, target.as_js()) or {}
            store_ex = extract_from_relay_records(snapshot.get("records"), target)
            target = target.enriched(store_ex.chat)

            network_ex = combine_extractions(
                [
                    extract_from_graphql(c.payloads, target, variables=c.variables)
                    for c in captures
                ],
                page_info="oldest",
            )

            page_info = store_ex.page_info or network_ex.page_info or next_ex.page_info
            graphql_ex = Extraction()
            graphql_pages = 0
            if page_info is not None and page_info.has_previous_page:
                cursor = _oldest_cursor(page_info, network_ex)
                if target.node_id and cursor:
                    log("scrolling stopped early; fetching older pages over GraphQL")
                    try:
                        graphql_ex, graphql_pages = self._load_older_via_graphql(
                            target, cursor, max_pages=max_pages
                        )
                        if graphql_ex.page_info is not None:
                            page_info = graphql_ex.page_info
                    except Exception as exc:  # noqa: BLE001 - the chat is still reported as incomplete
                        notes.append(f"GraphQL pagination failed: {exc}")

            merged = combine_extractions([store_ex, network_ex, graphql_ex, next_ex])
            chat_info = merged.chat
            if chat_info is None or not chat_info.title:
                # The sidebar chat list (page data or network) also carries the title.
                for data in [next_data, *(c.payloads for c in captures)]:
                    found = find_chat_info(data, target)
                    if found is not None:
                        chat_info = found if chat_info is None else chat_info.merged(found)
                        break

            counts = {
                "store": len(store_ex.messages),
                "next_data": len(next_ex.messages),
                "network": len(network_ex.messages),
                "graphql": len(graphql_ex.messages),
            }
            messages = merged.messages
            source = "raw"
            if page_info is None:
                complete = None if messages else False
            else:
                complete = page_info.has_more is False

            if not messages:
                source = "none"
                if _url_matches_target(final_url, target):
                    dom_messages = messages_from_dom(
                        self._safe_evaluate(page_scripts.DOM_MESSAGES_JS) or []
                    )
                    counts["dom"] = len(dom_messages)
                    if dom_messages:
                        messages = dom_messages
                        source = "dom-fallback"
                        complete = None
                        notes.append("no raw message data on the page; converted rendered HTML instead")
                if not messages:
                    complete = False
                    notes.append(
                        f"no messages found at {final_url} "
                        f"(title={probe.get('title')!r}, relay store found={probe.get('envFound')})"
                    )

            raw = None
            if capture_raw:
                raw = {
                    "final_url": final_url,
                    "probe": probe,
                    "next_data": next_data,
                    "store": snapshot,
                    "network": [c.to_dict() for c in captures],
                    "scroll_log": scroll_log,
                    "dom_html": self._safe_evaluate(page_scripts.DOM_SNAPSHOT_JS),
                }

            return HarvestResult(
                messages=messages,
                complete=complete,
                source=source,
                counts=counts,
                chat=chat_info,
                url=final_url,
                pages_loaded=pages_loaded,
                graphql_pages=graphql_pages,
                elapsed_s=time.monotonic() - started,
                notes=notes,
                raw=raw,
            )
        finally:
            self.page.remove_listener("response", on_response)

    def _open(self, target: ChatTarget, urls: list[str], log: Log) -> dict[str, Any]:
        probe: dict[str, Any] = {}
        for url in urls:
            log(f"opening {url}")
            try:
                response = self.page.goto(url, wait_until="domcontentloaded", timeout=90_000)
            except PlaywrightError as exc:
                log(f"navigation error: {exc}")
                continue
            if "/login" in self.page.url:
                raise NotLoggedInError(
                    "Poe redirected to the login page: the p-b cookie is missing or expired."
                )
            probe = self._wait_until_ready(target)
            store = probe.get("store") or {}
            log(
                f"landed on {self.page.url} (relay store={probe.get('envFound')}, "
                f"messages={store.get('messageCount', 0)}, __NEXT_DATA__={probe.get('hasNextData')})"
            )
            if store.get("messageCount") or (response is not None and response.status < 400):
                return probe
        return probe

    def _capture_response(self, response: Any, *, keep_raw: bool) -> NetworkCapture | None:
        url = response.url
        if "poe.com" not in url or "gql" not in url.lower():
            return None
        try:
            request = response.request
            query_name, variables = _query_meta(request.post_data, request.headers)
            body = response.body()
        except Exception:  # noqa: BLE001 - an event handler must never raise
            return None
        content_type = response.headers.get("content-type", "")
        payloads = parse_graphql_body(body, content_type)
        raw_body = body.decode("utf-8", "replace") if keep_raw and not payloads else None
        return NetworkCapture(
            url=url,
            query_name=query_name,
            variables=variables,
            status=response.status,
            content_type=content_type,
            payloads=payloads,
            raw_body=raw_body,
        )

    def _scroll_to_oldest(self) -> dict[str, Any]:
        info = self._safe_evaluate(page_scripts.SCROLL_TO_OLDEST_JS) or {}
        if info.get("x") is not None and info.get("y") is not None:
            try:
                self.page.mouse.move(info["x"], info["y"])
                for _ in range(3):
                    self.page.mouse.wheel(0, -2400)
            except PlaywrightError:
                pass
        return info

    def _load_older_by_scrolling(
        self,
        target: ChatTarget,
        page_info: PageInfo | None,
        *,
        max_pages: int,
        log: Log,
        wait_s: float = 6.0,
    ) -> tuple[int, list[dict[str, Any]]]:
        """Scroll to the top until the store says there is no previous page.

        The page sends its own signed pagination requests, so no GraphQL
        details have to be guessed. Gives up after two rounds without progress.
        """
        count = int(((self._probe(target).get("store")) or {}).get("messageCount") or 0)
        loaded = 0
        stale = 0
        scroll_log: list[dict[str, Any]] = []
        for _ in range(max_pages):
            if page_info is not None and not page_info.has_previous_page:
                break
            scroll = self._scroll_to_oldest()
            started = time.monotonic()
            nudged = False
            new_count = count
            while time.monotonic() - started < wait_s:
                self.page.wait_for_timeout(300)
                store = self._probe(target).get("store") or {}
                new_count = int(store.get("messageCount") or 0)
                page_info = PageInfo.from_dict(store.get("pageInfo")) or page_info
                if new_count > count or (page_info is not None and not page_info.has_previous_page):
                    break
                if not nudged and time.monotonic() - started > wait_s / 2:
                    # Infinite-scroll sentinels sometimes need a second scroll event.
                    self._scroll_to_oldest()
                    nudged = True
            scroll_log.append(
                {
                    "before": count,
                    "after": new_count,
                    "scroll": scroll,
                    "pageInfo": asdict(page_info) if page_info else None,
                }
            )
            if new_count > count:
                loaded += 1
                stale = 0
                log(f"loaded older messages: {count} -> {new_count}")
                count = new_count
            else:
                stale += 1
                if stale >= 2:
                    break
        return loaded, scroll_log

    def _load_older_via_graphql(
        self,
        target: ChatTarget,
        cursor: str,
        *,
        max_pages: int,
    ) -> tuple[Extraction, int]:
        """Page backwards with the same signed query the page itself uses."""
        template = dict(self._pagination_variables or {"count": 50})
        parts: list[Extraction] = []
        seen: set[str] = set()
        pages = 0
        while cursor and cursor not in seen and pages < max_pages:
            seen.add(cursor)
            variables = {**template, "cursor": cursor, "id": target.node_id}
            data = self.gql_request("ChatListPaginationQuery", variables)
            part = extract_from_graphql([data], target, variables=variables, source="graphql")
            parts.append(part)
            pages += 1
            info = part.page_info
            if not part.messages or info is None or not info.has_previous_page:
                break
            cursor = info.start_cursor or ""
        return combine_extractions(parts, page_info="oldest"), pages


def _oldest_cursor(page_info: PageInfo, network: Extraction) -> str | None:
    if network.page_info is not None and network.page_info.start_cursor:
        return network.page_info.start_cursor
    return page_info.start_cursor


def _url_matches_target(url: str, target: ChatTarget) -> bool:
    codes = [c for c in (target.chat_code, target.share_code) if c]
    return not codes or any(code in (url or "") for code in codes)


def harvest_chat(
    client: PoeClient,
    chat: Chat,
    *,
    max_pages: int = 200,
    capture_raw: bool = False,
    log: Log | None = None,
) -> HarvestResult:
    target = ChatTarget(
        chat_code=chat.chat_code or None,
        chat_id=chat.chat_id,
        node_id=chat.node_id or None,
    )
    return client.harvest(
        target,
        _chat_urls(chat),
        max_pages=max_pages,
        capture_raw=capture_raw,
        log=log,
    )


_ACTIVITY_KEYS = (
    "lastInteractionTime",
    "lastMessageTime",
    "lastMessageCreationTime",
    "lastActivityTime",
    "updatedTime",
    "updatedAt",
)
_LAST_MESSAGE_KEYS = ("lastMessage", "latestMessage", "newestMessage")


def _activity_signature(node: dict[str, Any]) -> str | None:
    """A value that changes whenever the chat gets a new message, if Poe sends one."""
    for key in _ACTIVITY_KEYS:
        if node.get(key) not in (None, ""):
            return f"{key}={node[key]}"
    for key in _LAST_MESSAGE_KEYS:
        nested = node.get(key)
        if isinstance(nested, dict):
            marker = nested.get("messageId") or nested.get("creationTime")
            if marker not in (None, ""):
                return f"{key}={marker}"
    return None


def _activity_time_us(node: dict[str, Any]) -> int | None:
    for key in _ACTIVITY_KEYS:
        value = coerce_poe_time_us(node.get(key))
        if value is not None:
            return value
    for key in _LAST_MESSAGE_KEYS:
        nested = node.get(key)
        if isinstance(nested, dict):
            value = coerce_poe_time_us(nested.get("creationTime"))
            if value is not None:
                return value
    return None


def chat_from_list_node(node: dict[str, Any]) -> Chat:
    bot_obj = node.get("defaultBotObject") or {}
    handle = bot_obj.get("handle") or bot_obj.get("nickname") or node.get("defaultBotNickname") or ""
    return Chat(
        chat_id=node.get("chatId"),
        chat_code=node.get("chatCode") or "",
        node_id=node.get("id") or "",
        title=node.get("title") or "Untitled",
        bot=bot_obj.get("displayName") or handle or "",
        bot_handle=str(handle or ""),
        activity_time_us=_activity_time_us(node),
        created_time_us=coerce_poe_time_us(node.get("creationTime")),
        activity_signature=_activity_signature(node),
    )


def list_chats(client: PoeClient, limit: int | None = None) -> list[Chat]:
    chats: list[Chat] = []
    cursor: str | None = None
    while True:
        variables: dict[str, Any] = {"count": 50}
        if cursor:
            variables["cursor"] = cursor
        data = client.gql_request("ChatHistoryListPaginationQuery", variables)
        chats_data = data["data"]["chats"]
        for edge in chats_data.get("edges") or []:
            node = edge.get("node") or {}
            if not node.get("chatCode"):
                continue
            chats.append(chat_from_list_node(node))
            if limit is not None and len(chats) >= limit:
                return chats
        page_info = chats_data.get("pageInfo") or {}
        cursor = page_info.get("endCursor")
        if not page_info.get("hasNextPage") or not cursor:
            break
    return chats


def open_client(
    token: str | None,
    lat: str | None = None,
    headless: bool = True,
    warmup: bool = True,
):
    class _Ctx:
        def __enter__(self):
            self._pw = sync_playwright().start()
            try:
                self.client = PoeClient(self._pw, token, lat=lat, headless=headless, warmup=warmup)
            except BaseException:
                self._pw.stop()
                raise
            return self.client

        def __exit__(self, exc_type, exc, tb):
            try:
                self.client.close()
            finally:
                self._pw.stop()
            return False

    return _Ctx()
