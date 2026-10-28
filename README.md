# Poe bulk Markdown exporter

Export **all** of your [Poe.com](https://poe.com) conversations to **Archive Markdown** (and optional JSON) from the command line.

This is meant for bulk backup. Per-chat tagging with [`@export-chat`](https://poe.com/export-chat) is still fine for one-off transcripts; it cannot walk your full history automatically. Poe’s official API also does not expose chat-history export.

## Archive Markdown (default)

Each chat becomes one `.md` file with YAML frontmatter, ISO-8601 timestamps, clear speaker headings, and attachment links. With `--download-attachments`, media is saved under `attachments/<chat_code>/` and links are rewritten to relative paths so the archive stays usable if CDN URLs expire.

```markdown
---
title: "Conversation title"
bot: "Claude-Sonnet-4.5"
chat_id: 12345
chat_code: "abc123"
exported_at: 2026-10-28T06:25:00+00:00
message_count: 2
---

# Conversation title

## You · 2026-01-15T10:30:00+00:00

User message…

## Claude-Sonnet-4.5 · 2026-01-15T10:30:05+00:00

Bot reply…
```

## Requirements

- Python 3.10+
- A logged-in Poe account (session cookie)
- Chromium for Playwright (handles Cloudflare)

## Install

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
playwright install chromium
```

## Get your Poe session cookie

1. Open [poe.com](https://poe.com) and sign in.
2. Open DevTools → **Application** → **Cookies** → `https://poe.com`.
3. Copy the **`p-b`** value.
4. Optionally copy **`p-lat`** if auth fails with `p-b` alone.

Put them in the environment (preferred) or pass CLI flags:

```bash
cp .env.example .env
# edit .env — or:
export POE_TOKEN='your_p-b_value'
export POE_LAT='optional_p-lat_value'   # if needed
```

Never commit real cookie values.

## Usage

```bash
# List chats
poe-bulk-export list

# Export all chats as Archive Markdown (default)
poe-bulk-export export

# JSON, or both; custom output dir; first N chats
poe-bulk-export export -f json -o my_chats
poe-bulk-export export -f both -l 10

# Single chat (code from `poe-bulk-export list`, or the __code suffix in a filename)
poe-bulk-export export --chat-code 91z1xrschrxyu24wqx
# After git pull, reinstall so the CLI picks up new flags:
#   pip install -e .

# Markdown closer to @export-chat (User: / Bot: turns); strip thinking (default)
poe-bulk-export export --style export-chat
poe-bulk-export export --include-thinking   # keep reasoning blocks

# Optional: save real images offline (skips HTML error pages). Default keeps
# CDN URLs embedded in the Markdown, like the chat UI.
poe-bulk-export export --download-attachments

# Pass token explicitly
poe-bulk-export export -t 'your_p-b_value'
```

Chat pages use `https://poe.com/chat/{code}` (not `/c/`, which often 404s). Turn order follows the on-page DOM; network JSON upgrades markdown (code fences). Bare language tags from DOM text (e.g. `bash` instead of ` ```bash `) are repaired. Speakers are labeled You/User vs bot, and thinking is stripped unless `--include-thinking` is set.

Images/files stay as inline Markdown (`![…](https://…poecdn…)`) by default — same idea as viewing the chat. Separate attachment files are optional and only kept when the download is real media (not an HTML error page).

Files are named `{model}_{title}__{chatCode}.md`, with a leading `{YYYY-MM-DD}_` only when a chat date is known:

`Claude-Fable-5_Python_Learning_Project__93ozu1d1q42v5qtcou.md`  
`2024-07-09_Claude-Fable-5_Python_Learning_Project__93ozu1d1q42v5qtcou.md`


## How it works

1. Launches headless Chromium with your `p-b` cookie.
2. Captures Poe GraphQL headers (`poe-formkey`, etc.).
3. Paginates `ChatHistoryListPaginationQuery` for every conversation.
4. Paginates `ChatListPaginationQuery` for every message (oldest → newest).
5. Writes Archive Markdown and/or JSON.

GraphQL persisted-query hashes live in [`poe_bulk_export/gql_hashes.py`](poe_bulk_export/gql_hashes.py). If Poe redeploys and you see `PersistedQueryNotFound`, update that file.

## Caveats

- Uses Poe’s **unofficial** web GraphQL API; it can break without notice.
- Session cookies expire; grab a fresh `p-b` when auth fails.
- Prefer `--download-attachments` for a durable media archive.

## Development

```bash
pip install -e ".[dev]"
pytest
poe-bulk-export --help
```

Inspired by community exporters such as [ericblue/poe-chat-exporter](https://github.com/ericblue/poe-chat-exporter); this project uses its own package layout, Archive Markdown format, and optional attachment download.
