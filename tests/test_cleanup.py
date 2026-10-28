from poe_bulk_export.cleanup import cleanup_messages, strip_thinking, tidy_text
from poe_bulk_export.models import Attachment, Message

THINKING = """*Thinking...*

> The user wants a recap.
>
> Keep it short.

> Second quoted paragraph.

## Recap

- point one"""


def test_strip_thinking_removes_exact_header_and_quote_block():
    assert strip_thinking(THINKING) == "## Recap\n\n- point one"


def test_strip_thinking_accepts_bold_and_unicode_ellipsis():
    assert strip_thinking("**Thinking...**\n\n> plan\n\nAnswer") == "Answer"
    assert strip_thinking("*Thinking…*\n> plan\nAnswer") == "Answer"


def test_strip_thinking_leaves_everything_else_alone():
    untouched = [
        "I'm thinking about how to explain rebasing.\n\nHere's the answer.",
        "*Thinking...*\n\nNo quote block follows, so this stays.",
        "Intro first.\n\n*Thinking...*\n\n> not leading\n\nrest",
        "*Thinking...*\n\n> only reasoning, no answer",
        "> A quote that is the answer itself",
        "",
    ]
    for text in untouched:
        assert strip_thinking(text) == text


def test_tidy_text_trims_only_the_edges():
    assert tidy_text("\n\n  indented first line\nhouse rules  such\n\n  ") == "  indented first line\nhouse rules  such"


def test_cleanup_messages():
    messages = [
        Message(author="human", text="*Thinking...*\n\n> user typed this\n\nreal question"),
        Message(author="bot", text=THINKING),
        Message(author="bot", text="   "),
        Message(author="human", text="", attachments=[Attachment(url="https://pfst.cf2.poecdn.net/a.png", kind="image")]),
        Message(author="chat_break", text=""),
    ]
    out = cleanup_messages(messages)
    assert [m.author for m in out] == ["human", "bot", "human", "chat_break"]
    assert out[0].text == messages[0].text  # human text is never rewritten
    assert out[1].text == "## Recap\n\n- point one"

    kept = cleanup_messages(messages, include_thinking=True)
    assert kept[1].text == THINKING
