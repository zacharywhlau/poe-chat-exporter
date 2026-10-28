"""Live check against a public Poe share page (no account needed).

Opt-in because it needs network access and Playwright's Chromium:

    POE_LIVE=1 pytest tests/test_live_share.py
"""

from __future__ import annotations

import os

import pytest
from helpers import SHARE_CODE

pytestmark = pytest.mark.skipif(os.environ.get("POE_LIVE") != "1", reason="set POE_LIVE=1 to run against poe.com")

SHARE_URL = f"https://poe.com/s/{SHARE_CODE}"


@pytest.fixture(scope="module")
def client():
    from poe_bulk_export.client import open_client

    with open_client(token=None, warmup=False) as session:
        yield session


def test_harvest_public_share_page(client):
    from poe_bulk_export.extract import ChatTarget

    result = client.harvest(ChatTarget(share_code=SHARE_CODE), [SHARE_URL])
    assert result.source == "raw"
    assert result.complete is True
    assert result.counts["store"] == 2
    assert result.counts["next_data"] == 2
    assert [m.message_id for m in result.messages] == [13692479, 13692480]
    assert [m.author for m in result.messages] == ["human", "bot"]
    assert result.messages[0].text == "Who is Louis Cha?"
    assert result.messages[1].author_name == "Gemini-1.0-Pro"
    assert "Jin Yong" in result.messages[1].text
    assert "Headless" not in client.user_agent


def test_dom_fallback_script_reads_the_real_page(client):
    from poe_bulk_export import page_scripts
    from poe_bulk_export.dom_fallback import messages_from_dom

    client.page.goto(SHARE_URL, wait_until="domcontentloaded")
    client.page.wait_for_selector('[class*="Markdown_markdownContainer"]')
    messages = messages_from_dom(client.page.evaluate(page_scripts.DOM_MESSAGES_JS))
    assert [m.author for m in messages] == ["human", "bot"]
    assert messages[0].text == "Who is Louis Cha?"
    assert "**Key Facts:**" in messages[1].text
