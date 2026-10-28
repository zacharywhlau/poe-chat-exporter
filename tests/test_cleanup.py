from poe_bulk_export.cleanup import (
    cleanup_messages,
    is_thinking_only,
    normalize_author,
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
