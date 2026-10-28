"""Last resort: convert rendered message HTML to Markdown.

Only used when a page exposes no raw message data at all. Output is flagged as
degraded because rendered HTML loses some source formatting.
"""

from __future__ import annotations

import re
from typing import Any

from poe_bulk_export.models import Message


def _code_language(element: Any) -> str | None:
    code = element.find("code") if hasattr(element, "find") else None
    for node in (code, element):
        if node is None:
            continue
        for cls in node.get("class") or []:
            if cls.startswith("language-"):
                return cls[len("language-") :]
    return None


def html_to_markdown(html: str) -> str:
    from markdownify import markdownify

    markdown = markdownify(
        html or "",
        heading_style="ATX",
        bullets="-",
        code_language_callback=_code_language,
        escape_asterisks=False,
        escape_underscores=False,
        escape_misc=False,
    )
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    return markdown.strip()


def messages_from_dom(items: list[dict[str, Any]]) -> list[Message]:
    messages: list[Message] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        text = html_to_markdown(item.get("html") or "")
        if not text:
            continue
        role = item.get("role")
        messages.append(
            Message(
                author=role if role in ("human", "bot") else "unknown",
                text=text,
                source="dom",
            )
        )
    return messages
