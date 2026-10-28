from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from typing import Any

from playwright.sync_api import Playwright, sync_playwright

from poe_bulk_export.attachments import is_skip_attachment_url
from poe_bulk_export.cleanup import cleanup_messages, normalize_author
from poe_bulk_export.gql_hashes import QUERIES
from poe_bulk_export.models import Attachment, Chat, Message
from poe_bulk_export.util import (
    coerce_poe_time_us,
    extract_urls_from_text,
    guess_attachment_name,
    guess_kind,
)

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
            if not url or url in seen or is_skip_attachment_url(url):
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
        if url in seen or is_skip_attachment_url(url):
            continue
        # Real media CDNs only — not poe.com HTML pages
        if "poecdn" not in url.lower():
            continue
        seen.add(url)
        attachments.append(
            Attachment(url=url, name=name, kind=guess_kind(url, name))
        )

    return attachments


def _node_time_us(node: dict[str, Any]) -> int | None:
    for key in (
        "creationTime",
        "createdAt",
        "timestamp",
        "time",
        "sentAt",
        "updatedAt",
        "lastMessageTime",
        "lastMessageCreationTime",
    ):
        if key in node and node.get(key) is not None:
            coerced = coerce_poe_time_us(node.get(key))
            if coerced is not None:
                return coerced
    return None


def _message_from_node(node: dict[str, Any]) -> Message:
    text = node.get("text") or ""
    return Message(
        author=node.get("author") or "unknown",
        text=text,
        message_id=node.get("messageId"),
        content_type=node.get("contentType"),
        creation_time_us=_node_time_us(node),
        attachments=_attachments_from_node(node, text),
        source="network",
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
        # Prefer /chat/ — /c/ often 404s on current Poe.
        urls.extend(
            [
                f"https://poe.com/chat/{code}",
                f"https://poe.com/c/{code}",
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


_UI_CHROME = {
    "thinking",
    "thinking...",
    "*thinking...*",
    "view all",
    "run",
    "copy",
    "edited",
    "regenerate",
}


def _looks_like_ui_chrome(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return True
    if t in _UI_CHROME:
        return True
    # Truncated virtualized code panes from the Poe UI
    if t.startswith("python\nview all") or t.startswith("python\nView all".lower()):
        return True
    if "\nview all\n" in f"\n{t}\n" and len(t) < 800 and "```" not in t:
        return True
    return False


_BARE_LANG_LINE = re.compile(
    r"(?mi)^\s*(?:bash|sh|shell|zsh|python|py|yaml|yml|json|javascript|js|"
    r"typescript|ts|html|css|sql|toml|ini|gitignore|dockerfile|docker|"
    r"console|text|plaintext|markdown|md|xml|rust|go|ruby|java|c|cpp|"
    r"csharp|swift|kotlin|r|php|diff|makefile)\s*$"
)


def _normalize_for_dedupe(text: str) -> str:
    """Fingerprint that ignores markdown fences so DOM/network copies match."""
    t = text or ""
    t = re.sub(r"```[\w+-]*\n?", "\n", t)
    t = _BARE_LANG_LINE.sub("\n", t)
    # Horizontal rules and ATX headings differ between DOM plain text and MD
    t = re.sub(r"(?m)^\s*-{3,}\s*$", "\n", t)
    t = re.sub(r"(?m)^\s*#{1,6}\s*", "", t)
    t = re.sub(r"[*_`>~]+", " ", t)
    return " ".join(t.split()).lower()


def _speaker_side(author: str) -> str:
    a = normalize_author(author or "")
    if a == "human":
        return "human"
    if a in ("unknown", ""):
        return "unknown"
    return "bot"


def _same_speaker(a: str, b: str) -> bool:
    sa, sb = _speaker_side(a), _speaker_side(b)
    if sa == "unknown" or sb == "unknown":
        return True
    return sa == sb


def _chunk_hit_ratio(shorter: str, longer: str, chunk: int = 72, step: int = 72) -> float:
    """How many windows of shorter appear inside longer (markdown-noise tolerant)."""
    if not shorter:
        return 0.0
    if shorter in longer:
        return 1.0
    if len(shorter) < chunk:
        return 1.0 if shorter in longer else 0.0
    hits = 0
    total = 0
    for start in range(0, len(shorter) - chunk + 1, step):
        total += 1
        if shorter[start : start + chunk] in longer:
            hits += 1
    return hits / max(total, 1)


def _overlap_score(a: str, b: str) -> float:
    fa, fb = _normalize_for_dedupe(a), _normalize_for_dedupe(b)
    if not fa or not fb:
        return 0.0
    if fa == fb:
        return 1.0
    shorter, longer = (fa, fb) if len(fa) <= len(fb) else (fb, fa)
    if shorter in longer:
        return len(shorter) / max(len(longer), 1)

    # Shared prefix — network markdown vs DOM plain text often diverge mid-body
    # after a long identical lead-in.
    i = 0
    limit = min(len(fa), len(fb))
    while i < limit and fa[i] == fb[i]:
        i += 1
    prefix_ratio = i / max(len(fa), len(fb), 1)
    if i >= 60 and prefix_ratio >= 0.35:
        return max(0.6, prefix_ratio)
    if i >= 100:
        return 0.7

    # Long near-duplicates that diverge early on formatting still share body chunks
    if len(shorter) >= 400:
        hit = _chunk_hit_ratio(shorter, longer)
        if hit >= 0.55:
            return max(0.65, hit)

    n = min(120, len(fa), len(fb))
    if n >= 40 and fa[:n] == fb[:n]:
        return 0.8
    return 0.0


def _merge_metadata(winner: Message, other: Message) -> Message:
    """Keep timestamps / ids from either side when the chosen text wins."""
    return Message(
        author=(
            winner.author
            if winner.author not in ("", "unknown")
            else other.author
        ),
        text=winner.text,
        message_id=winner.message_id
        if winner.message_id is not None
        else other.message_id,
        content_type=winner.content_type or other.content_type,
        creation_time_us=winner.creation_time_us
        if winner.creation_time_us is not None
        else other.creation_time_us,
        attachments=winner.attachments or other.attachments,
        source=winner.source
        if winner.source != "unknown"
        else other.source,
    )


def _prefer_message(a: Message, b: Message) -> Message:
    """Prefer network JSON over DOM, then richer / better-labeled copies."""
    a_net = 1 if a.source == "network" else 0
    b_net = 1 if b.source == "network" else 0
    a_fences = (a.text or "").count("```")
    b_fences = (b.text or "").count("```")
    # Strong preference: real markdown fences beat bare language tags
    if a_fences != b_fences:
        winner, loser = (a, b) if a_fences > b_fences else (b, a)
        if len(winner.text or "") + 120 >= len(loser.text or ""):
            return _merge_metadata(winner, loser)
    if a_net != b_net:
        # Network text wins unless it's dramatically shorter/truncated
        winner, loser = (a, b) if a_net else (b, a)
        if len(winner.text or "") + 80 >= len(loser.text or ""):
            return _merge_metadata(winner, loser)
        # DOM was much longer — keep DOM text but preserve network metadata
        return _merge_metadata(loser, winner)
    if abs(len(a.text or "") - len(b.text or "")) > 40:
        return _merge_metadata(
            *((a, b) if len(a.text or "") >= len(b.text or "") else (b, a))
        )
    a_score = (0 if a.author == "unknown" else 1) + (1 if a.creation_time_us else 0)
    b_score = (0 if b.author == "unknown" else 1) + (1 if b.creation_time_us else 0)
    if a_score != b_score:
        return _merge_metadata(*( (a, b) if a_score > b_score else (b, a) ))
    return _merge_metadata(
        *((a, b) if len(a.text or "") >= len(b.text or "") else (b, a))
    )


def _dedupe_messages(messages: list[Message]) -> list[Message]:
    """Drop UI chrome and keep the best copy of overlapping turns."""
    cleaned = [m for m in messages if not _looks_like_ui_chrome(m.text)]
    kept: list[Message] = []
    for msg in cleaned:
        norm = _normalize_for_dedupe(msg.text)
        if not norm:
            continue
        replaced = False
        for i, prev in enumerate(kept):
            if not _same_speaker(prev.author, msg.author):
                continue
            prev_norm = _normalize_for_dedupe(prev.text)
            # Same id
            if (
                msg.message_id is not None
                and prev.message_id is not None
                and msg.message_id == prev.message_id
            ):
                kept[i] = _prefer_message(prev, msg)
                replaced = True
                break
            score = _overlap_score(msg.text, prev.text)
            if score >= 0.5:
                kept[i] = _prefer_message(prev, msg)
                replaced = True
                break
            # One contains the other (truncated DOM vs full answer)
            if norm in prev_norm or prev_norm in norm:
                if abs(len(norm) - len(prev_norm)) < max(
                    80, int(0.2 * max(len(norm), len(prev_norm)))
                ):
                    kept[i] = _prefer_message(prev, msg)
                    replaced = True
                    break
                if len(norm) > len(prev_norm) and prev_norm in norm:
                    kept[i] = _prefer_message(prev, msg)
                    replaced = True
                    break
                if len(prev_norm) > len(norm) and norm in prev_norm:
                    replaced = True
                    break
        if not replaced:
            kept.append(msg)
    return kept


def _collapse_duplicate_turns(messages: list[Message]) -> list[Message]:
    """Final pass: merge adjacent/same-speaker near-duplicates after cleanup."""
    if len(messages) < 2:
        return messages
    return _dedupe_messages(messages)


def _assemble_from_dom_and_network(
    dom_msgs: list[Message],
    network_msgs: list[Message],
) -> list[Message]:
    """DOM document order drives turns; network upgrades text/metadata."""
    if not dom_msgs:
        messages = list(network_msgs)
        if any(m.creation_time_us for m in messages):
            return _sort_messages(messages)
        return messages

    unused = list(network_msgs)
    result: list[Message] = []

    for dom in dom_msgs:
        if _looks_like_ui_chrome(dom.text):
            continue
        best_i = -1
        best_score = 0.0
        for i, net in enumerate(unused):
            if not _same_speaker(dom.author, net.author):
                continue
            score = _overlap_score(dom.text, net.text)
            if score > best_score:
                best_score = score
                best_i = i
        if best_i >= 0 and best_score >= 0.55:
            net = unused.pop(best_i)
            result.append(_prefer_message(net, dom))
        else:
            result.append(dom)

    leftovers = unused
    if any(m.creation_time_us for m in leftovers):
        leftovers = _sort_messages(list(leftovers))
    for net in leftovers:
        if _looks_like_ui_chrome(net.text):
            continue
        if any(
            _same_speaker(net.author, r.author)
            and _overlap_score(net.text, r.text) >= 0.55
            for r in result
        ):
            continue
        result.append(net)

    return result


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

    def _wait_for_navigation_settle(self, quiet_ms: int = 800, timeout_ms: int = 20_000) -> None:
        """Wait until the page URL/load stops changing (Poe often redirects /c → bot URL)."""
        deadline = time.time() + timeout_ms / 1000
        last = self.page.url
        stable_since = time.time()
        while time.time() < deadline:
            try:
                self.page.wait_for_load_state("domcontentloaded", timeout=3_000)
            except Exception:
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
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                msg = str(exc).lower()
                if "context was destroyed" in msg or "navigation" in msg:
                    self._wait_for_navigation_settle()
                    continue
                raise
        if last_exc:
            raise last_exc
        return None

    def _scroll_chat_up(self) -> None:
        """Scroll toward older messages without relying on a fragile evaluate."""
        try:
            self.page.keyboard.press("Home")
        except Exception:
            pass
        try:
            self.page.mouse.wheel(0, -4000)
        except Exception:
            pass
        try:
            self._safe_evaluate(
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
        except Exception:
            # Scroll is best-effort; message harvest still uses network events.
            pass

    def _scrape_dom_messages(self) -> tuple[list[Message], dict[str, Any]]:
        """Read visible chat bubbles from the DOM (works even when gql harvest is empty)."""
        info = self._safe_evaluate(
            """() => {
              const messages = [];
              const seen = new Set();
              const chrome = new Set([
                'thinking', 'thinking...', 'view all', 'run', 'copy', 'edited', 'regenerate'
              ]);
              const push = (author, text) => {
                const t = (text || '').trim();
                if (!t) return;
                if (chrome.has(t.toLowerCase())) return;
                // Skip tiny UI fragments
                if (t.length < 3) return;
                const key = author + '\\n' + t;
                if (seen.has(key)) return;
                seen.add(key);
                messages.push({ author, text: t });
              };

              const containers = document.querySelectorAll(
                '[class*="Markdown_markdownContainer"], [class*="Markdown_markdown"]'
              );
              for (const container of containers) {
                let host = container;
                let author = 'unknown';
                // Walk ancestors for side / role class names (Poe MessageBubble)
                for (let i = 0; i < 12 && host; i++) {
                  const cls = String(host.className || '');
                  if (/rightSide|RightSide|UserMessage|Outbound|fromUser/i.test(cls)) {
                    author = 'human';
                    break;
                  }
                  if (/leftSide|LeftSide|BotMessage|Inbound|fromBot/i.test(cls)) {
                    author = 'bot';
                    break;
                  }
                  if (/Message|Bubble|ChatMessage/i.test(cls) && host !== container) {
                    // keep walking a bit more on the bubble for side classes
                  }
                  host = host.parentElement;
                }
                if (author === 'unknown') {
                  const rect = container.getBoundingClientRect();
                  const mid = window.innerWidth / 2;
                  // User bubbles are typically on the right half
                  author = rect.left >= mid * 0.55 ? 'human' : 'bot';
                }
                push(author, container.innerText || '');
              }

              if (messages.length === 0) {
                // Broader fallback: any obvious message row text
                const rows = document.querySelectorAll(
                  '[class*="Message_row"], [class*="ChatMessage"], [data-testid*="message"]'
                );
                for (const row of rows) {
                  const text = (row.innerText || '').trim();
                  if (text) push('unknown', text);
                }
              }

              const bodyText = (document.body && document.body.innerText) || '';
              return {
                title: document.title || '',
                url: location.href,
                messageCount: messages.length,
                messages,
                bodySample: bodyText.slice(0, 400),
                looksLikeLogin: /log\\s*in|sign\\s*in|create account/i.test(bodyText.slice(0, 2000)),
              };
            }"""
        ) or {}

        messages = [
            Message(
                author=m.get("author") or "unknown",
                text=m.get("text") or "",
                source="dom",
            )
            for m in (info.get("messages") or [])
            if m.get("text")
        ]
        return messages, info

    def _merge_message(self, store: dict[Any, Message], msg: Message) -> None:
        key: Any
        if msg.message_id is not None:
            key = ("id", msg.message_id)
        else:
            key = ("text", msg.author, (msg.text or "")[:240])
        prev = store.get(key)
        if prev is None:
            store[key] = msg
        else:
            store[key] = _prefer_message(prev, msg)

    def harvest_chat_messages(
        self,
        chat: Chat,
        *,
        scroll_pages: int = 25,
        include_thinking: bool = False,
    ) -> list[Message]:
        """Open the chat page; DOM order drives turns, network upgrades text."""
        network_by_key: dict[Any, Message] = {}
        dom_ordered: list[Message] = []
        api_hits = 0
        network_count = 0

        def on_response(response: Any) -> None:
            nonlocal api_hits, network_count
            url = response.url
            if "poe.com" not in url:
                return
            if not any(x in url for x in ("/api/", "gql", "graphql")):
                return
            api_hits += 1
            try:
                data = response.json()
            except Exception:
                return
            for node in _walk_message_nodes(data):
                network_count += 1
                self._merge_message(network_by_key, _message_from_node(node))

        self.page.on("response", on_response)
        page_info: dict[str, Any] = {}
        try:
            opened = False
            for url in _chat_urls(chat):
                print(f"Opening {url}", file=sys.stderr)
                try:
                    self.page.goto(url, wait_until="commit", timeout=90_000)
                except Exception as exc:
                    print(f"  navigation error: {exc}", file=sys.stderr)
                    continue
                self._wait_for_navigation_settle()
                try:
                    self.page.wait_for_load_state("load", timeout=20_000)
                except Exception:
                    pass
                self.page.wait_for_timeout(3500)
                self._wait_for_navigation_settle()
                print(f"  landed on {self.page.url}", file=sys.stderr)
                opened = True

                # DOM document order is the turn sequence; network upgrades
                # markdown quality (fences) later in assemble.
                dom_msgs, page_info = self._scrape_dom_messages()
                if dom_msgs:
                    dom_ordered = dom_msgs
                if network_by_key or dom_ordered:
                    break
                if api_hits > 0:
                    break

            if not opened:
                print("Could not open any chat URL", file=sys.stderr)
                return []

            for i in range(scroll_pages):
                before_net = len(network_by_key)
                before_dom = len(dom_ordered)
                before_nodes = network_count
                self._scroll_chat_up()
                self.page.wait_for_timeout(1200)
                dom_msgs, page_info = self._scrape_dom_messages()
                # Prefer the scrape with the most bubbles (older history loaded)
                if len(dom_msgs) >= len(dom_ordered):
                    dom_ordered = dom_msgs
                if (
                    len(network_by_key) == before_net
                    and len(dom_ordered) == before_dom
                    and network_count == before_nodes
                ):
                    self.page.wait_for_timeout(1500)
                    dom_msgs, page_info = self._scrape_dom_messages()
                    if len(dom_msgs) >= len(dom_ordered):
                        dom_ordered = dom_msgs
                    if (
                        len(network_by_key) == before_net
                        and len(dom_ordered) == before_dom
                        and i > 2
                    ):
                        break

            print(
                f"Harvested network={len(network_by_key)} dom={len(dom_ordered)} "
                f"(api responses={api_hits}, network_nodes={network_count}, "
                f"dom_scrape={page_info.get('messageCount', 0)}) "
                f"at {self.page.url}",
                file=sys.stderr,
            )
            if not network_by_key and not dom_ordered:
                sample = (page_info.get("bodySample") or "").replace("\n", " ")[:200]
                print(
                    f"Page debug: title={page_info.get('title')!r} "
                    f"login={page_info.get('looksLikeLogin')} sample={sample!r}",
                    file=sys.stderr,
                )
                if page_info.get("looksLikeLogin"):
                    print(
                        "Chat page looks logged out. Re-copy p-b and also set "
                        "POE_LAT from Cookies, then retry with --headed.",
                        file=sys.stderr,
                    )
        finally:
            self.page.remove_listener("response", on_response)

        assembled = _assemble_from_dom_and_network(
            dom_ordered, list(network_by_key.values())
        )
        messages = _dedupe_messages(assembled)
        # Only chronologically sort when every turn has a timestamp — otherwise
        # preserve DOM document order (network-only stamps would shove the
        # bot reply above an untimed user prompt).
        if messages and all(m.creation_time_us for m in messages):
            messages = _sort_messages(messages)
        cleaned = cleanup_messages(
            messages,
            include_thinking=include_thinking,
            bot_name=chat.bot,
            bot_handle=chat.bot_handle,
        )
        # Fence repair can make DOM/network copies comparable only after cleanup.
        return _collapse_duplicate_turns(cleaned)


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
            activity = _node_time_us(node)
            # Some list payloads nest the latest message time
            if activity is None:
                for nested_key in ("lastMessage", "newestMessage", "latestMessage"):
                    nested = node.get(nested_key)
                    if isinstance(nested, dict):
                        activity = _node_time_us(nested)
                        if activity is not None:
                            break
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
                    activity_time_us=activity,
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


def _fetch_messages_graphql(
    client: PoeClient,
    chat: Chat,
    *,
    include_thinking: bool = False,
) -> list[Message]:
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
    cleaned = cleanup_messages(
        messages,
        include_thinking=include_thinking,
        bot_name=chat.bot,
        bot_handle=chat.bot_handle,
    )
    return _collapse_duplicate_turns(_dedupe_messages(cleaned))


def fetch_messages(
    client: PoeClient,
    chat: Chat,
    *,
    include_thinking: bool = False,
) -> list[Message]:
    """Prefer browser chat-page harvest; GraphQL is fallback / later-chat speedup."""
    if client._graphql_messages_ok:
        try:
            return _fetch_messages_graphql(
                client, chat, include_thinking=include_thinking
            )
        except Exception as exc:  # noqa: BLE001
            print(
                f"GraphQL message fetch failed, falling back to page harvest: {exc}",
                file=sys.stderr,
            )

    messages = client.harvest_chat_messages(
        chat, include_thinking=include_thinking
    )
    if messages:
        # Probe GraphQL for later chats, but never replace this chat's harvest —
        # GraphQL often returns plain + markdown duplicates of the same bot turn.
        if not client._graphql_messages_ok:
            try:
                gql_msgs = _fetch_messages_graphql(
                    client, chat, include_thinking=include_thinking
                )
                if gql_msgs:
                    client._graphql_messages_ok = True
                    print(
                        "GraphQL message fetch OK — will try it for remaining chats "
                        "(keeping page harvest for this chat)",
                        file=sys.stderr,
                    )
            except Exception:
                pass
        return messages

    try:
        messages = _fetch_messages_graphql(
            client, chat, include_thinking=include_thinking
        )
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
