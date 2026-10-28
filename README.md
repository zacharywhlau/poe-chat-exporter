# Poe chat exporter (`poe-bulk-export`)

Export your [Poe.com](https://poe.com) conversations to Markdown (and optionally JSON) from the command line: every chat in one run, or specific chats by code.

The exporter reads the raw message data Poe ships with each chat page: the same Markdown that [`@export-chat`](https://poe.com/export-chat) prints. Code blocks, headings and lists come through exactly as the bot wrote them, and `--style export-chat --strip-thinking` produces a file byte-for-byte identical to `@export-chat`'s.

## Requirements

- Python 3.10+
- A signed-in Poe account (its `p-b` session cookie)
- Chromium for Playwright (Poe sits behind Cloudflare, so a real browser does the requests)

## Install

```bash
python3 -m venv .venv                  # or: /opt/anaconda3/bin/python -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
playwright install chromium
```

On a Mac, if you also use Anaconda, run `conda deactivate` first so `.venv`'s `python` wins (or call `.venv/bin/poe-bulk-export` directly). After moving the project folder (e.g. to iCloud), delete `.venv` and recreate it — old venvs break when their path changes.

After `git pull`, run `pip install -e .` again so new dependencies and CLI options are picked up. On a Mac you can also double-click [`mac/Setup.command`](mac/Setup.command).

## Sign-in cookie

1. Open [poe.com](https://poe.com) and sign in.
2. Open DevTools → **Application** → **Cookies** → `https://poe.com`.
3. Copy the **`p-b`** value. If exports fail with `p-b` alone, also copy **`p-lat`**.

Put them in a local `.env` (git-ignored — never commit real values):

```bash
cp .env.example .env                   # then edit .env
# POE_TOKEN=your_p-b_cookie_value
# POE_LAT=                                 # optional
```

Load once per terminal session, then run as many commands as you like in that same tab:

```bash
set -a; source .env; set +a
poe-bulk-export list
```

You do **not** need to re-run `source .env` before every command — only when you open a new terminal. The Mac helpers in [`mac/`](#mac-helpers-double-click) load `.env` for you.

You can also pass `--token` / `--lat`, or export the variables yourself. On Windows PowerShell: `$env:POE_TOKEN = 'your_p-b_value'`.

When the cookie expires, the CLI stops with exit code 2 instead of writing empty exports. Paste a fresh `p-b` into `.env`.

## Usage

**Preferred export** (same layout as Poe's `@export-chat`, every chat, into `./poe_exports`):

```bash
poe-bulk-export export --style export-chat -o poe_exports
```

Thinking blocks are kept by default. Re-run later with `--incremental` to skip chats that have not changed.

```bash
# List your chats (bot, title, chat code)
poe-bulk-export list

# Preferred: every chat, @export-chat layout
poe-bulk-export export --style export-chat -o poe_exports

# Same, but only chats that changed since the last complete export
poe-bulk-export export --style export-chat -o poe_exports --incremental

# One or more specific chats (code or URL; repeatable)
poe-bulk-export export --style export-chat -o poe_exports --chat-code abc123xyz
poe-bulk-export export --style export-chat -o poe_exports -c https://poe.com/chat/abc123xyz -c def456uvw

# Also write JSON, drop Thinking blocks, and/or save images locally
poe-bulk-export export --style export-chat -o poe_exports -f both --strip-thinking --download-attachments
```

### Mac helpers (double-click)

The [`mac/`](mac/) folder has Finder-friendly `.command` scripts (the Mac equivalent of a `.bat` file). They `cd` to the project, use `.venv`, and load `.env` automatically:

| Double-click | What it does |
| --- | --- |
| [`Setup.command`](mac/Setup.command) | Create `.venv`, install the package + Chromium, create `.env` from the example if missing |
| [`List Chats.command`](mac/List%20Chats.command) | `poe-bulk-export list` |
| [`Export All Chats.command`](mac/Export%20All%20Chats.command) | Preferred: `export --style export-chat -o poe_exports` |
| [`Export Changed Only.command`](mac/Export%20Changed%20Only.command) | Same, with `--incremental` |
| [`Export One Chat.command`](mac/Export%20One%20Chat.command) | Asks for a chat code/URL, then exports that chat |
| [`Poe Tools.command`](mac/Poe%20Tools.command) | Small menu of the above |

After `git pull`, make them executable once if macOS complains:

```bash
chmod +x mac/*.command mac/_lib.sh
```

First time: run **Setup**, edit `.env` with your cookie, then use **Export All Chats** (or **Poe Tools**).

| Option | Meaning |
| --- | --- |
| `-c, --chat-code` | Export only these chats (code or URL, repeatable). Skips the chat-list scan. |
| `-f, --format` | `markdown` (default), `json` or `both`. |
| `--style` | `archive` (default) or `export-chat`. See [Output](#output). |
| `--strip-thinking` | Remove the leading `*Thinking...*` reasoning block some bots write before their answer. By default it is kept, as in Poe. |
| `-o, --output` | Output directory (default `poe_exports`). |
| `--incremental` | Skip chats that are unchanged and were exported completely before with the same `--format`, `--style` and thinking choice. |
| `--download-attachments` | Save real media under `attachments/<chat_code>/` and link the local copies. |
| `-l, --limit` | Export at most N chats from the list. |
| `--max-pages` | Upper bound on pages of older messages loaded per chat (default 200). |
| `-v, --verbose` | Show how each chat was harvested. |
| `--headed` | Show the browser window. |

Each chat gets one status line, and the run ends with a summary:

```text
OK   Trip planning [abc123xyz]: 42 messages (store=42, next_data=2), complete (4.2s) -> 2026-01-15_Claude-Sonnet-4.5_Trip_planning__abc123xyz.md
Done: exported 1/1 -> poe_exports/
```

`WARN` means the export was written, but something in it may be off:

- the chat's full history could not be confirmed as loaded (`INCOMPLETE` or `completeness unknown`),
- the page had no raw data and the rendered HTML was used instead (`DOM fallback`), or
- some messages could not be attributed to you or a bot (`N messages with unknown author`). Those turns are labelled with the chat's bot name, so check them.

`FAIL` means nothing could be read for that chat. Warnings and failures are listed again at the end, followed by a hint to run [`dump`](#troubleshooting) on them.

## Output

### Styles

**`export-chat`**: the layout of Poe's `@export-chat`. Each turn is `User:` or `<Bot name>:`, a blank line, then the message's raw Markdown. Turns are separated by `---`. There is no header and no trailing newline, matching Poe's file. Each bot reply is labelled with the bot that wrote it, so a reply from `@export-chat` or another mentioned bot shows that bot's name. `@export-chat` itself leaves out `*Thinking...*` blocks; add `--strip-thinking` to do the same.

```markdown
User:

Plan a three-day trip to Kyoto.

---

Claude-Sonnet-4.5:

## Day 1
…
```

**`archive`** (default): YAML front matter, then the same transcript. Before each turn, an HTML comment records the message time and id; it does not show up when the Markdown is rendered.

```markdown
---
title: "Trip planning"
bot: "Claude-Sonnet-4.5"
chat_code: "abc123xyz"
chat_id: 123456789
url: "https://poe.com/chat/abc123xyz"
created: "2026-01-15T10:30:00Z"
updated: "2026-01-15T10:31:12Z"
message_count: 2
complete: true
source: "raw"
exported_at: "2026-10-28T09:30:00Z"
exporter: "poe-bulk-export 0.2.0"
---

<!-- 2026-01-15T10:30:00Z · message 1001 -->
User:

Plan a three-day trip to Kyoto.

---

<!-- 2026-01-15T10:31:12Z · message 1002 -->
Claude-Sonnet-4.5:

## Day 1
…
```

`complete: false` means older messages could not all be loaded, and `complete: null` means Poe gave no paging information to check against. `source: "dom-fallback"` means the page carried no raw message data and the text was converted from the rendered HTML, so formatting may differ from the original.

**JSON** (`-f json` or `both`) holds the same chat metadata plus one object per message: `messageId`, `role`, `author`, `authorName`, `text`, `contentType`, `state`, `time`, `time_epoch_us` and `attachments`.

### Files

- Names are `{date}_{bot}_{title}__{chatCode}.md` (and `.json`). The date is the first message's day and is left out when unknown.
- Re-exporting a chat replaces its file, including when the chat was renamed, so each chat has exactly one file per format.
- Images and files already in a message's Markdown stay as Poe's CDN links. Attachments not mentioned in the text are appended as links. `--download-attachments` saves real media only (never HTML error pages) and points the links at the local copies.
- `.poe-export-index.json` in the output directory records what was exported, for `--incremental`.

**Upgrading from 0.1:** older versions saved repeated exports as extra copies ending in `-2`, `-3`, … (for example `…__abc123xyz-5.md`). Version 0.2 never creates them and leaves existing ones alone; delete them by hand after re-exporting.

### Checking an export against `@export-chat`

```bash
poe-bulk-export export --chat-code abc123xyz --style export-chat --strip-thinking -o check
cmp poe-chat-export-<timestamp>.md check/*__abc123xyz.md
```

`cmp` prints nothing when the two files are identical. If the chat continued after `@export-chat` ran (the `@export-chat` request and its reply are part of the chat too), the export is longer, and `cmp` reports `EOF on poe-chat-export-<timestamp>.md`: everything up to that point matched.

## How it works

1. Chromium starts with your cookies and loads poe.com once to confirm you are signed in.
2. Without `--chat-code`, the chat list is paged through Poe's `ChatHistoryListPaginationQuery`. With `--chat-code`, that scan is skipped and the title and bot come from the chat page itself.
3. Each chat opens at `https://poe.com/chat/<code>`, and its messages are read from three places on the page:
   - the Relay store (the web app's in-memory GraphQL cache),
   - `window.__NEXT_DATA__` (the server-rendered page data),
   - GraphQL responses captured while the page loads, including multipart `@defer`/`@stream` responses.

   Only messages on this chat's own message connection are taken, so previews of other chats in the sidebar cannot leak in.
4. While the connection reports older messages (`hasPreviousPage`), the message list is scrolled to the top so Poe loads them itself. If scrolling stalls, older pages are requested directly with a signed `ChatListPaginationQuery`. A chat whose history still is not complete is exported with `complete: false` and a warning.
5. Messages from all sources are merged by message id and ordered by creation time. Text is not edited. The only exception is `--strip-thinking`, which removes a leading `*Thinking...*` header plus its `>` quote block from every turn not written by you, and only when an answer follows.
6. Only when a page has no raw message data at all is the rendered HTML converted to Markdown (with `markdownify`). Those exports are marked `source: "dom-fallback"` and reported as warnings.

GraphQL persisted-query hashes live in [`poe_bulk_export/gql_hashes.py`](poe_bulk_export/gql_hashes.py); hashes seen in live traffic take precedence.

## Troubleshooting

If a chat is reported as `WARN` or `FAIL`, or its export looks wrong, capture what the page contained:

```bash
poe-bulk-export dump --chat-code abc123xyz
```

This writes `poe_debug/abc123xyz/`:

| File | Contents |
| --- | --- |
| `summary.json` | Message counts per source, completeness, notes, the scroll log |
| `messages.json` | The merged raw messages |
| `export-chat.md` | What `--style export-chat` would write |
| `next_data.json` | The page's `__NEXT_DATA__` |
| `store_records.json`, `store_summary.json` | The chat's records from the Relay store |
| `network/NNN-<Query>.json` | Captured GraphQL responses |
| `dom.html` | The rendered message list |

Cookies and request headers are never written, and account fields such as email, phone, uid and formkey are replaced with `[redacted]`. The dump still contains the chat itself (and `dom.html` may include sidebar chat titles), so review it before sharing.

Other things to try:

- Exit code 2 or "not logged in": copy a fresh `p-b` (and `p-lat`) cookie.
- `--headed --verbose` to watch the browser and see each harvesting step.
- `PersistedQueryNotFound`: Poe redeployed; update `gql_hashes.py`.

| Exit code | Meaning |
| --- | --- |
| 0 | Every chat was exported (warnings may be listed) |
| 1 | At least one chat failed, or no cookie was given |
| 2 | Poe redirected to the login page (cookie missing or expired), or the command-line options were invalid |

## Caveats

- This uses Poe's unofficial web app data and GraphQL API, which can change without notice. `dump` shows what a page contains when that happens.
- Session cookies expire; grab a fresh `p-b` when sign-in fails.
- Poe's CDN links can expire; use `--download-attachments` for a durable media archive.

## Development

```bash
pip install -e ".[dev]"
pytest                                       # offline tests, including the golden @export-chat comparison
POE_LIVE=1 pytest tests/test_live_share.py   # also harvest a public Poe share page in Chromium
ruff check .
```

The golden test uses a real chat's six messages as Relay store records, in the shape Poe's private chat page uses (`tests/fixtures/workflow_guide_store.json`; ids, times and the user record are placeholders). The chat holds a prompt, an answer with a `*Thinking...*` block, a follow-up and its answer, then `@export-chat` and its reply. With `--strip-thinking`, the export must start with that chat's `@export-chat` file byte for byte (`tests/fixtures/workflow_guide_export_chat.md`), followed by the `@export-chat` request and reply as normal turns. By default, the thinking block is kept and every turn is labelled with its own speaker. The other fixtures are trimmed page data from a public share page.

Inspired by community exporters such as [ericblue/poe-chat-exporter](https://github.com/ericblue/poe-chat-exporter).
