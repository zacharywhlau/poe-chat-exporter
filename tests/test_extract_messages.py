from poe_bulk_export.client import (
    _assemble_from_dom_and_network,
    _chat_urls,
    _collapse_duplicate_turns,
    _dedupe_messages,
    _looks_like_ui_chrome,
    _merge_dom_windows,
    _normalize_for_dedupe,
    _overlap_score,
    _walk_message_nodes,
)
from poe_bulk_export.cleanup import cleanup_messages
from poe_bulk_export.models import Chat, Message


def test_chat_prefers_chat_path_over_c():
    chat = Chat(
        chat_id=1,
        chat_code="abc123",
        node_id="id",
        title="T",
        bot="Claude",
        bot_handle="Claude-Fable-5",
    )
    urls = _chat_urls(chat)
    assert urls[0] == "https://poe.com/chat/abc123"
    assert "https://poe.com/c/abc123" in urls


def test_ui_chrome_filter():
    assert _looks_like_ui_chrome("View all")
    assert _looks_like_ui_chrome("Thinking")
    assert not _looks_like_ui_chrome("Hello, please help me learn Python")


def test_dedupe_prefers_longer_complete_copy():
    short = Message(author="bot", text="partial answer about expense tracker")
    full = Message(
        author="bot",
        text="Here's the full partial answer about expense tracker\n\n```python\nprint(1)\n```",
    )
    out = _dedupe_messages([short, full])
    assert len(out) == 1
    assert "```python" in out[0].text


def test_walk_nested_messages():
    data = {
        "data": {
            "node": {
                "messagesConnection": {
                    "edges": [
                        {
                            "node": {
                                "messageId": 1,
                                "author": "human",
                                "text": "hi",
                            }
                        }
                    ]
                }
            },
            "extra": {
                "nested": {
                    "messageId": 2,
                    "author": "bot",
                    "text": "yo",
                    "contentType": "text/plain",
                }
            },
        }
    }
    nodes = _walk_message_nodes(data)
    ids = sorted(n["messageId"] for n in nodes)
    assert ids == [1, 2]


def test_chat_urls_include_handle_variants():
    chat = Chat(
        chat_id=1,
        chat_code="abc123",
        node_id="id",
        title="T",
        bot="Claude",
        bot_handle="Claude-Fable-5",
    )
    urls = _chat_urls(chat)
    assert "https://poe.com/Claude-Fable-5/abc123" in urls


def test_normalize_strips_fences_for_dedupe():
    with_fences = "```bash\ngit status\n```\nExplain status."
    bare = "bash\ngit status\n\nExplain status."
    assert _normalize_for_dedupe(with_fences) == _normalize_for_dedupe(bare)


def test_dedupe_merges_fenced_and_bare_bot_copies():
    network = Message(
        author="bot",
        text=(
            "# Guide\n\n```bash\ngit config --global user.name Ada\n```\n\n"
            "Here git config writes settings."
        ),
        message_id=99,
        source="network",
    )
    dom = Message(
        author="bot",
        text=(
            "Guide\n\nbash\ngit config --global user.name Ada\n\n"
            "Here git config writes settings."
        ),
        source="dom",
    )
    out = _dedupe_messages([network, dom])
    assert len(out) == 1
    assert "```bash" in out[0].text
    assert out[0].source == "network"


def test_assemble_workflow_guide_order_and_fences():
    """Reproduce Workflow Guide export: network bot + DOM You + bare DOM bot."""
    prompt = (
        "Draft git and GitHub workflow for teamwork developing python projects, "
        "make sure the procedure are clear with explanations to the syntax"
    )
    good_bot = (
        "# Git & GitHub Team Workflow for Python Projects\n\n"
        "## 4. One-Time Setup\n\n"
        "```bash\n"
        'git config --global user.name "Ada Lovelace"\n'
        'git config --global user.email "ada@acme.com"\n'
        "```\n\n"
        "Here git config writes settings."
    )
    bare_bot = (
        "Git & GitHub Team Workflow for Python Projects\n\n"
        "4. One-Time Setup\n\n"
        "bash\n"
        'git config --global user.name "Ada Lovelace"\n'
        'git config --global user.email "ada@acme.com"\n'
        "\n"
        "Here git config writes settings."
    )
    # Insertion order that previously produced bot → You → bot duplicate
    network = [
        Message(
            author="bot",
            text=good_bot,
            message_id=1,
            creation_time_us=1_700_000_000_000_000,
            source="network",
        )
    ]
    dom = [
        Message(author="human", text=prompt, source="dom"),
        Message(author="bot", text=bare_bot, source="dom"),
    ]
    assembled = _assemble_from_dom_and_network(dom, network)
    messages = cleanup_messages(
        _dedupe_messages(assembled),
        bot_name="Claude-Fable-5",
    )
    assert len(messages) == 2
    assert messages[0].author == "human"
    assert "Draft git and GitHub workflow" in messages[0].text
    assert messages[1].author == "bot"
    assert "```bash" in messages[1].text
    assert messages[1].text.count("```bash") >= 1
    # No duplicate bot answer
    assert sum(1 for m in messages if m.author == "bot") == 1


def test_merge_dom_windows_keeps_both_ends_of_virtualized_chat():
    """Bottom scrape has newest turns; top scrape has the opening prompt."""
    prompt = "Draft git and GitHub workflow for teamwork developing python projects"
    guide = (
        "Git & GitHub Team Workflow for Python Projects\n\n"
        "1. Purpose and Scope\n\n"
        "This document defines how our team uses Git and GitHub.\n" + ("more " * 80)
    )
    recap_q = "recap"
    recap_a = (
        "# Recap: Git & GitHub Team Workflow\n\n"
        "**The workflow:** GitHub Flow — main stays stable.\n"
    )
    bottom = [
        Message(author="bot", text=guide, source="dom"),
        Message(author="human", text=recap_q, source="dom"),
        Message(author="bot", text=recap_a, source="dom"),
    ]
    top = [
        Message(author="human", text=prompt, source="dom"),
        Message(author="bot", text=guide, source="dom"),
    ]
    merged = _merge_dom_windows([bottom, top])
    assert len(merged) == 4
    assert merged[0].author == "human"
    assert "Draft git" in merged[0].text
    assert merged[2].text == "recap"
    assert "Recap" in merged[3].text


def test_assemble_continued_chat_uses_timed_network_backbone():
    """After a follow-up, DOM may miss the opening prompt; network still has it."""
    prompt = "Draft git and GitHub workflow for teamwork developing python projects"
    guide = (
        "# Git & GitHub Team Workflow for Python Projects\n\n"
        "## 1. Purpose and Scope\n\n"
        "This document defines how our team uses Git and GitHub.\n"
        + ("detail " * 100)
    )
    recap_a = "# Recap\n\n**The workflow:** GitHub Flow.\n"
    # Incomplete DOM like export -4 (bot guide, you recap, bot recap)
    dom = [
        Message(author="bot", text=guide.replace("# ", "").replace("## ", ""), source="dom"),
        Message(author="human", text="recap", source="dom"),
        Message(author="bot", text=recap_a, source="dom"),
    ]
    network = [
        Message(
            author="human",
            text=prompt,
            message_id=1,
            creation_time_us=100,
            source="network",
        ),
        Message(
            author="bot",
            text=guide,
            message_id=2,
            creation_time_us=200,
            source="network",
        ),
        Message(
            author="human",
            text="recap",
            message_id=3,
            creation_time_us=300,
            source="network",
        ),
        Message(
            author="bot",
            text=recap_a,
            message_id=4,
            creation_time_us=400,
            source="network",
        ),
    ]
    assembled = _assemble_from_dom_and_network(dom, network)
    messages = cleanup_messages(
        _dedupe_messages(assembled), bot_name="Claude-Fable-5"
    )
    assert len(messages) == 4
    assert messages[0].author == "human"
    assert "Draft git" in messages[0].text
    assert messages[2].text.strip() == "recap"
    assert "Recap" in messages[3].text


def test_collapse_plain_and_markdown_bot_duplicates():
    """Regression: export -2 had You + plain DOM bot + markdown network bot."""
    plain = (
        "Git & GitHub Team Workflow for Python Projects\n\n"
        "A professional team guideline — clear procedures, syntax explanations, "
        "and rationale\n\n"
        "1. Purpose and Scope\n\n"
        "This document defines how our team uses Git and GitHub to collaborate "
        "on Python projects. It covers naming conventions, the day-to-day "
        "development cycle, pull requests and code review, merging strategy, "
        "releases, and Python-specific repository hygiene. Every command is "
        "explained so that new team members can follow the procedure.\n\n"
        "```bash\n"
        'git config --global user.name "Ada Lovelace"\n'
        "```\n\n"
        "Here git config writes settings for all repositories on this machine "
        "and that is why we prefer the global scope for identity setup.\n"
    )
    markdown = (
        "# Git & GitHub Team Workflow for Python Projects\n\n"
        "**A professional team guideline — clear procedures, syntax explanations, "
        "and rationale**\n\n"
        "---\n\n"
        "## 1. Purpose and Scope\n\n"
        "This document defines how our team uses Git and GitHub to collaborate "
        "on Python projects. It covers naming conventions, the day-to-day "
        "development cycle, pull requests and code review, merging strategy, "
        "releases, and Python-specific repository hygiene. Every command is "
        "explained so that new team members can follow the procedure.\n\n"
        "```bash\n"
        'git config --global user.name "Ada Lovelace"\n'
        "```\n\n"
        "Here `git config` writes settings for all repositories on this machine "
        "and that is why we prefer the global scope for identity setup.\n"
    )
    assert _overlap_score(plain, markdown) >= 0.5
    msgs = [
        Message(author="human", text="Draft the workflow guide", source="dom"),
        Message(author="bot", text=plain, source="dom"),
        Message(
            author="bot",
            text=markdown,
            message_id=9,
            creation_time_us=1,
            source="network",
        ),
    ]
    out = _collapse_duplicate_turns(cleanup_messages(msgs, bot_name="Claude-Fable-5"))
    assert len(out) == 2
    assert out[0].author == "human"
    assert out[1].author == "bot"
    assert out[1].source == "network"
    assert "## 1. Purpose" in out[1].text
