from poe_bulk_export.cleanup import (
    cleanup_messages,
    is_thinking_only,
    normalize_author,
    repair_markdown_fences,
    strip_thinking,
)
from poe_bulk_export.models import Message


def test_normalize_author():
    assert normalize_author("human") == "human"
    assert normalize_author("bot", bot_name="Claude") == "bot"
    assert normalize_author("Claude-Fable-5", bot_name="Claude-Fable-5") == "bot"
    assert normalize_author("claude_fable_5", bot_handle="Claude-Fable-5") == "bot"


def test_strip_thinking_block():
    text = (
        "*Thinking...*\n\n"
        "> I'm planning the answer\n"
        "> more notes\n\n"
        "Here's a complete beginner-friendly project."
    )
    out = strip_thinking(text)
    assert "Here's a complete beginner-friendly project." in out
    assert "I'm planning" not in out


def test_cleanup_drops_thinking_by_default():
    messages = [
        Message(author="human", text="Help me learn Python"),
        Message(author="bot", text="Thinking\n\nshort"),
        Message(
            author="bot",
            text=(
                "*Thinking...*\n\n> draft\n\n"
                "Here's a complete beginner-friendly project:\n\n```python\nprint(1)\n```"
            ),
        ),
    ]
    out = cleanup_messages(messages, bot_name="Claude-Fable-5")
    assert len(out) == 2
    assert out[0].author == "human"
    assert out[1].author == "bot"
    assert "```python" in out[1].text
    assert "Thinking" not in out[1].text


def test_include_thinking_keeps_content():
    messages = [
        Message(author="bot", text="*Thinking...*\n\n> notes\n\nFinal answer"),
    ]
    out = cleanup_messages(messages, include_thinking=True)
    assert "Thinking" in out[0].text


def test_is_thinking_only():
    assert is_thinking_only("Thinking")
    assert is_thinking_only("*Thinking...*")
    assert not is_thinking_only("Here is a real answer with details")


def test_repair_bare_bash_fences():
    raw = (
        "Configure your identity:\n\n"
        "bash\n"
        'git config --global user.name "Ada Lovelace"\n'
        'git config --global user.email "ada@acme.com"\n'
        "\n"
        "Here git config writes settings; --global stores them.\n"
    )
    out = repair_markdown_fences(raw)
    assert "```bash\n" in out
    assert out.count("```") >= 2
    assert "Here git config writes" in out
    # Prose must stay outside the fence
    fence_end = out.index("```", out.index("```bash"))
    assert "Here git config writes" in out[fence_end:]


def test_repair_gitignore_with_internal_blank_lines():
    raw = (
        "The .gitignore:\n\n"
        "gitignore\n"
        "# Environments\n"
        ".venv/\n"
        ".env\n"
        "\n"
        "# Bytecode\n"
        "__pycache__/\n"
        "\n"
        "Two of these lines are security-critical and must never be committed.\n"
    )
    out = repair_markdown_fences(raw)
    assert "```gitignore\n" in out
    assert ".venv/" in out
    assert "__pycache__/" in out
    assert "Two of these lines" in out
    # Closing fence before prose
    assert out.index("```\n", out.index("```gitignore")) < out.index(
        "Two of these lines"
    )


def test_repair_leaves_existing_fences_alone():
    raw = "Example:\n\n```bash\ngit status\n```\n\nDone.\n"
    assert repair_markdown_fences(raw) == raw


def test_cleanup_repairs_dom_fences():
    messages = [
        Message(
            author="bot",
            text=(
                "Run this:\n\nbash\ngit switch main\ngit pull origin main\n\n"
                "git switch moves your working directory."
            ),
            source="dom",
        )
    ]
    out = cleanup_messages(messages, bot_name="Claude-Fable-5")
    assert len(out) == 1
    assert "```bash" in out[0].text
    assert "git switch moves" in out[0].text
