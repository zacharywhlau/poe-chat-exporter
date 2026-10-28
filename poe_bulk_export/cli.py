from __future__ import annotations

import os
import sys
from enum import Enum
from pathlib import Path
from typing import Optional

import typer
from tqdm import tqdm

from poe_bulk_export import __version__
from poe_bulk_export.attachments import download_chat_attachments
from poe_bulk_export.client import fetch_messages, list_chats, open_client
from poe_bulk_export.json_export import write_json
from poe_bulk_export.markdown import write_markdown

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Export all Poe.com chats to Archive Markdown (and optional JSON).",
)


class ExportFormat(str, Enum):
    markdown = "markdown"
    json = "json"
    both = "both"


class MarkdownStyle(str, Enum):
    archive = "archive"
    export_chat = "export-chat"


def _resolve_token(token: Optional[str]) -> str:
    value = token or os.environ.get("POE_TOKEN")
    if not value:
        typer.echo(
            "Error: Poe token required. Pass --token or set POE_TOKEN "
            "(p-b cookie from poe.com).",
            err=True,
        )
        raise typer.Exit(code=1)
    return value


def _resolve_lat(lat: Optional[str]) -> Optional[str]:
    return lat or os.environ.get("POE_LAT") or None


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main_callback(
    version: Optional[bool] = typer.Option(
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
    token: Optional[str] = typer.Option(
        None, "--token", "-t", help="Poe p-b cookie (or POE_TOKEN)."
    ),
    lat: Optional[str] = typer.Option(
        None, "--lat", help="Optional p-lat cookie (or POE_LAT)."
    ),
    limit: Optional[int] = typer.Option(
        None, "--limit", "-l", help="Max conversations to list."
    ),
    headless: bool = typer.Option(
        True, "--headless/--headed", help="Run Chromium headless."
    ),
) -> None:
    """List conversations without exporting."""
    pb = _resolve_token(token)
    with open_client(pb, lat=_resolve_lat(lat), headless=headless) as client:
        chats = list_chats(client, limit=limit)
        typer.echo(f"Found {len(chats)} conversation(s)")
        for i, chat in enumerate(chats, 1):
            typer.echo(f"  {i}. [{chat.bot}] {chat.title} ({chat.chat_code})")


@app.command("export")
def export_cmd(
    token: Optional[str] = typer.Option(
        None, "--token", "-t", help="Poe p-b cookie (or POE_TOKEN)."
    ),
    lat: Optional[str] = typer.Option(
        None, "--lat", help="Optional p-lat cookie (or POE_LAT)."
    ),
    limit: Optional[int] = typer.Option(
        None, "--limit", "-l", help="Max conversations to export."
    ),
    format: ExportFormat = typer.Option(
        ExportFormat.markdown,
        "--format",
        "-f",
        help="Output format.",
    ),
    style: MarkdownStyle = typer.Option(
        MarkdownStyle.archive,
        "--style",
        help="Markdown layout: archive (default) or export-chat (User:/Bot: turns).",
    ),
    include_thinking: bool = typer.Option(
        False,
        "--include-thinking/--no-include-thinking",
        help="Keep model thinking/reasoning blocks (default: strip them).",
    ),
    output: Path = typer.Option(
        Path("poe_exports"),
        "--output",
        "-o",
        help="Output directory.",
    ),
    download_attachments: bool = typer.Option(
        False,
        "--download-attachments",
        help="Download media/files and rewrite Markdown links to local paths.",
    ),
    headless: bool = typer.Option(
        True, "--headless/--headed", help="Run Chromium headless."
    ),
) -> None:
    """Export conversations to Archive Markdown and/or JSON."""
    pb = _resolve_token(token)
    plat = _resolve_lat(lat)
    output.mkdir(parents=True, exist_ok=True)

    cookies = {"p-b": pb}
    if plat:
        cookies["p-lat"] = plat

    with open_client(pb, lat=plat, headless=headless) as client:
        typer.echo("Fetching conversation list…", err=True)
        chats = list_chats(client, limit=limit)
        typer.echo(f"Found {len(chats)} conversation(s)", err=True)

        if not chats:
            typer.echo("No conversations to export.")
            return

        ok = 0
        for chat in tqdm(chats, desc="Exporting", file=sys.stderr):
            try:
                chat.messages = fetch_messages(
                    client, chat, include_thinking=include_thinking
                )
                if download_attachments:
                    download_chat_attachments(chat, output, cookies=cookies)

                if format in (ExportFormat.markdown, ExportFormat.both):
                    write_markdown(chat, output, style=style.value)
                if format in (ExportFormat.json, ExportFormat.both):
                    write_json(chat, output)
                ok += 1
            except Exception as exc:  # noqa: BLE001 — continue other chats
                tqdm.write(f"Error exporting '{chat.title}': {exc}", file=sys.stderr)

        typer.echo(f"Done. Exported {ok}/{len(chats)} chat(s) → {output}/")


if __name__ == "__main__":
    app()
