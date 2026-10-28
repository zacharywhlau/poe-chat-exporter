from __future__ import annotations

import os
import re
import sys
from enum import Enum
from pathlib import Path

import typer
from tqdm import tqdm

from poe_bulk_export import __version__
from poe_bulk_export.attachments import download_chat_attachments
from poe_bulk_export.cleanup import cleanup_messages
from poe_bulk_export.client import (
    HarvestResult,
    NotLoggedInError,
    PoeClient,
    harvest_chat,
    list_chats,
    open_client,
)
from poe_bulk_export.extract import ChatInfo
from poe_bulk_export.json_export import write_json
from poe_bulk_export.manifest import ExportIndex
from poe_bulk_export.markdown import write_markdown
from poe_bulk_export.models import Chat
from poe_bulk_export.util import now_iso_z

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Export Poe.com chats to Markdown (and optional JSON) from Poe's raw message data.",
)


class ExportFormat(str, Enum):
    markdown = "markdown"
    json = "json"
    both = "both"


class MarkdownStyle(str, Enum):
    archive = "archive"
    export_chat = "export-chat"


_CODE_IN_URL = re.compile(r"poe\.com/(?:chat|c|s)/([A-Za-z0-9_-]+)")


def _resolve_token(token: str | None) -> str:
    value = token or os.environ.get("POE_TOKEN")
    if not value:
        typer.echo(
            "Error: Poe token required. Pass --token or set POE_TOKEN "
            "(p-b cookie from poe.com).",
            err=True,
        )
        raise typer.Exit(code=1)
    return value


def _resolve_lat(lat: str | None) -> str | None:
    return lat or os.environ.get("POE_LAT") or None


def normalize_chat_codes(values: list[str] | None) -> list[str]:
    """Accept bare codes or chat URLs; drop blanks and duplicates, keep order."""
    codes: list[str] = []
    for value in values or []:
        value = (value or "").strip()
        match = _CODE_IN_URL.search(value)
        if match:
            value = match.group(1)
        value = value.strip("/").split("/")[-1].split("?")[0]
        if value and value not in codes:
            codes.append(value)
    return codes


def apply_chat_info(chat: Chat, info: ChatInfo | None, result: HarvestResult | None = None) -> None:
    """Fill metadata the chat list did not provide (e.g. with --chat-code)."""
    if info is not None:
        if info.title and chat.title in ("", "Untitled"):
            chat.title = info.title
        if info.bot_name and not chat.bot:
            chat.bot = info.bot_name
        if info.bot_handle and not chat.bot_handle:
            chat.bot_handle = info.bot_handle
        if chat.chat_id is None and info.chat_id is not None:
            chat.chat_id = info.chat_id
        if not chat.node_id and info.node_id:
            chat.node_id = info.node_id
    if not chat.bot and result is not None:
        names = [m.author_name for m in result.messages if m.author == "bot" and m.author_name]
        if names:
            chat.bot = names[0]


def _chat_label(chat: Chat) -> str:
    title = chat.title if chat.title not in ("", "Untitled") else "(untitled)"
    return f"{title} [{chat.chat_code}]"


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main_callback(
    version: bool | None = typer.Option(
        None,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    return None


@app.command("list")
def list_cmd(
    token: str | None = typer.Option(None, "--token", "-t", help="Poe p-b cookie (or POE_TOKEN)."),
    lat: str | None = typer.Option(None, "--lat", help="Optional p-lat cookie (or POE_LAT)."),
    limit: int | None = typer.Option(None, "--limit", "-l", help="Max conversations to list."),
    headless: bool = typer.Option(True, "--headless/--headed", help="Run Chromium headless."),
) -> None:
    """List conversations without exporting."""
    pb = _resolve_token(token)
    try:
        with open_client(pb, lat=_resolve_lat(lat), headless=headless) as client:
            chats = list_chats(client, limit=limit)
    except NotLoggedInError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2) from None
    typer.echo(f"Found {len(chats)} conversation(s)")
    for i, chat in enumerate(chats, 1):
        typer.echo(f"  {i}. [{chat.bot}] {chat.title} ({chat.chat_code})")


def _export_one(
    client: PoeClient,
    chat: Chat,
    *,
    output: Path,
    fmt: ExportFormat,
    style: MarkdownStyle,
    include_thinking: bool,
    download_attachments: bool,
    max_pages: int,
    exported_at: str,
    verbose: bool,
) -> tuple[HarvestResult, list[Path]]:
    log = (lambda msg: tqdm.write(f"    {msg}", file=sys.stderr)) if verbose else None
    result = harvest_chat(client, chat, max_pages=max_pages, log=log)
    if not result.messages:
        raise RuntimeError("; ".join(result.notes) or "no messages found")

    apply_chat_info(chat, result.chat, result)
    chat.messages = cleanup_messages(result.messages, strip_thinking=not include_thinking)
    chat.complete = result.complete
    chat.source = result.source

    if download_attachments:
        saved = download_chat_attachments(
            chat, output, cookies=client.cookies, user_agent=client.user_agent
        )
        if saved and verbose:
            tqdm.write(f"    saved {saved} attachment file(s)", file=sys.stderr)

    paths: list[Path] = []
    if fmt in (ExportFormat.markdown, ExportFormat.both):
        paths.append(write_markdown(chat, output, style=style.value, exported_at=exported_at))
    if fmt in (ExportFormat.json, ExportFormat.both):
        paths.append(write_json(chat, output, exported_at=exported_at))
    return result, paths


@app.command("export")
def export_cmd(
    token: str | None = typer.Option(None, "--token", "-t", help="Poe p-b cookie (or POE_TOKEN)."),
    lat: str | None = typer.Option(None, "--lat", help="Optional p-lat cookie (or POE_LAT)."),
    chat_code: list[str] | None = typer.Option(
        None,
        "--chat-code",
        "-c",
        help="Export only this chat, opened directly (repeatable; a chat URL works too).",
    ),
    limit: int | None = typer.Option(None, "--limit", "-l", help="Max conversations to export."),
    format: ExportFormat = typer.Option(ExportFormat.markdown, "--format", "-f", help="Output format."),
    style: MarkdownStyle = typer.Option(
        MarkdownStyle.archive,
        "--style",
        help="Markdown layout: archive (front matter + transcript) or export-chat (@export-chat's layout).",
    ),
    include_thinking: bool = typer.Option(
        True,
        "--include-thinking/--strip-thinking",
        help="Keep (default) or remove the leading '*Thinking...*' reasoning block some bots write before their answer.",
    ),
    output: Path = typer.Option(Path("poe_exports"), "--output", "-o", help="Output directory."),
    download_attachments: bool = typer.Option(
        False,
        "--download-attachments",
        help="Also save real images/files locally and link them (default keeps CDN URLs).",
    ),
    incremental: bool = typer.Option(
        False,
        "--incremental",
        help="Skip chats unchanged since their last complete export (tracked in .poe-export-index.json).",
    ),
    max_pages: int = typer.Option(
        200, "--max-pages", min=1, help="Max pages of older messages to load per chat."
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show per-chat harvesting details."),
    headless: bool = typer.Option(True, "--headless/--headed", help="Run Chromium headless."),
) -> None:
    """Export conversations to Markdown and/or JSON."""
    pb = _resolve_token(token)
    plat = _resolve_lat(lat)
    codes = normalize_chat_codes(chat_code)
    output.mkdir(parents=True, exist_ok=True)
    index = ExportIndex.load(output)
    exported_at = now_iso_z()

    exported = 0
    skipped = 0
    warnings: list[str] = []
    failures: list[str] = []
    total = 0

    try:
        with open_client(pb, lat=plat, headless=headless) as client:
            if codes:
                chats = [Chat(chat_id=None, chat_code=code) for code in codes]
            else:
                typer.echo("Fetching conversation list…", err=True)
                chats = list_chats(client, limit=limit)
                typer.echo(f"Found {len(chats)} conversation(s)", err=True)
            total = len(chats)

            for chat in tqdm(chats, desc="Exporting", unit="chat", file=sys.stderr, disable=total < 2):
                if incremental and index.is_current(
                    chat, style=style.value, fmt=format.value, strip_thinking=not include_thinking
                ):
                    skipped += 1
                    if verbose:
                        tqdm.write(f"SKIP {_chat_label(chat)}: unchanged", file=sys.stderr)
                    continue
                try:
                    result, paths = _export_one(
                        client,
                        chat,
                        output=output,
                        fmt=format,
                        style=style,
                        include_thinking=include_thinking,
                        download_attachments=download_attachments,
                        max_pages=max_pages,
                        exported_at=exported_at,
                        verbose=verbose,
                    )
                except NotLoggedInError:
                    raise
                except Exception as exc:  # noqa: BLE001 - keep exporting the other chats
                    failures.append(f"{_chat_label(chat)}: {exc}")
                    tqdm.write(f"FAIL {_chat_label(chat)}: {exc}", file=sys.stderr)
                    continue

                exported += 1
                index.record(
                    chat, paths, style=style.value, fmt=format.value, strip_thinking=not include_thinking
                )
                index.save()
                degraded = result.complete is not True or result.source != "raw"
                if degraded:
                    warnings.append(f"{_chat_label(chat)}: {result.summary()}")
                status = "WARN" if degraded else "OK  "
                files = ", ".join(p.name for p in paths)
                tqdm.write(
                    f"{status} {_chat_label(chat)}: {result.summary()} ({result.elapsed_s:.1f}s) -> {files}",
                    file=sys.stderr,
                )
                if verbose:
                    for note in result.notes:
                        tqdm.write(f"    note: {note}", file=sys.stderr)
    except NotLoggedInError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2) from None

    parts = [f"exported {exported}/{total}"]
    if skipped:
        parts.append(f"skipped {skipped} unchanged")
    if warnings:
        parts.append(f"{len(warnings)} with warnings")
    if failures:
        parts.append(f"{len(failures)} failed")
    typer.echo(f"Done: {', '.join(parts)} -> {output}/")
    if warnings:
        typer.echo("Warnings:", err=True)
        for line in warnings:
            typer.echo(f"  - {line}", err=True)
    if failures:
        typer.echo("Failed:", err=True)
        for line in failures:
            typer.echo(f"  - {line}", err=True)
        typer.echo(
            "Re-run a failed chat with `poe-bulk-export dump --chat-code CODE` to see what the page contained.",
            err=True,
        )
        raise typer.Exit(code=1)


@app.command("dump")
def dump_cmd(
    chat_code: str = typer.Option(..., "--chat-code", "-c", help="Chat code (or chat URL) to inspect."),
    token: str | None = typer.Option(None, "--token", "-t", help="Poe p-b cookie (or POE_TOKEN)."),
    lat: str | None = typer.Option(None, "--lat", help="Optional p-lat cookie (or POE_LAT)."),
    output: Path = typer.Option(Path("poe_debug"), "--output", "-o", help="Dump directory."),
    max_pages: int = typer.Option(200, "--max-pages", min=1, help="Max pages of older messages to load."),
    headless: bool = typer.Option(True, "--headless/--headed", help="Run Chromium headless."),
) -> None:
    """Save one chat's raw page data (page JSON, Relay records, GraphQL, DOM) for troubleshooting."""
    from poe_bulk_export.dump import write_dump

    codes = normalize_chat_codes([chat_code])
    if not codes:
        typer.echo("Error: --chat-code is empty", err=True)
        raise typer.Exit(code=1)
    code = codes[0]
    pb = _resolve_token(token)
    chat = Chat(chat_id=None, chat_code=code)
    log = lambda msg: typer.echo(f"  {msg}", err=True)
    try:
        with open_client(pb, lat=_resolve_lat(lat), headless=headless) as client:
            result = harvest_chat(client, chat, max_pages=max_pages, capture_raw=True, log=log)
    except NotLoggedInError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2) from None
    apply_chat_info(chat, result.chat, result)
    folder = output / code
    files = write_dump(result, chat, folder)
    typer.echo(f"{_chat_label(chat)}: {result.summary()}")
    typer.echo(f"Wrote {len(files)} file(s) to {folder}/ (no cookies; account fields redacted).")


if __name__ == "__main__":
    app()
