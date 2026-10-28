from poe_bulk_export.dom_fallback import html_to_markdown, messages_from_dom


def test_rendered_html_converts_back_to_markdown():
    html = (
        "<h2>Branching</h2>"
        "<p>Create a branch with <code>git switch -c feature/x</code> before you start.</p>"
        '<pre><code class="language-bash">git switch -c feature/x\ngit push -u origin feature/x\n</code></pre>'
        "<p>Then open a <em>pull request</em> for my_module.</p>"
        "<ul><li><strong>Review</strong> first</li><li>merge</li></ul>"
    )
    assert html_to_markdown(html) == (
        "## Branching\n\n"
        "Create a branch with `git switch -c feature/x` before you start.\n\n"
        "```bash\ngit switch -c feature/x\ngit push -u origin feature/x\n```\n\n"
        "Then open a *pull request* for my_module.\n\n"
        "- **Review** first\n- merge"
    )


def test_messages_from_dom_roles_and_empty_items():
    items = [
        {"role": "human", "html": "<p>hi</p>"},
        {"role": "sidebar", "html": "<p>x</p>"},
        {"role": "bot", "html": ""},
        "junk",
    ]
    messages = messages_from_dom(items)
    assert [(m.author, m.text, m.source) for m in messages] == [("human", "hi", "dom"), ("unknown", "x", "dom")]
