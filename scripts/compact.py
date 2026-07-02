"""
compact.py — strip whitespace between block tags while preserving <pre> blocks.

Webflow's RichText parser silently drops list children when whitespace separates
<ul>, <li>, and </ul> tags. The Python markdown library outputs HTML with newlines
between block tags by default. Every push to Webflow RichText must go through this
compact helper or lists will vanish in the CMS editor and on rendered pages.

The API GET returns the HTML as-pushed, so this bug is invisible through automated
response checks — it only shows up when you look at the editor or a live page.

Usage:
    from compact import compact, to_compact_html

    # If you already have HTML:
    compact_html = compact(existing_html)

    # If you have markdown:
    compact_html = to_compact_html(markdown_string)
"""

import re

try:
    import markdown as _markdown
except ImportError:
    _markdown = None


# Whitespace between two tags is stripped only when at least one of them is a
# block-level tag. Between two inline tags (`</strong> <em>`) the space is real
# rendered text — deleting it would join the surrounding words. Webflow's parser
# bug only concerns whitespace between block tags, so inline gaps are safe to keep.
_BLOCK_TAG = re.compile(
    r'</?(?:p|div|ul|ol|li|h[1-6]|table|thead|tbody|tfoot|tr|td|th|caption|'
    r'blockquote|pre|figure|figcaption|hr|br|section|article|header|footer|nav|main)\b',
    re.IGNORECASE,
)
_TAG_GAP = re.compile(r'(<[^>]+>)\s+(?=(<[^>]+>))')


def _strip_block_whitespace(prose: str) -> str:
    return _TAG_GAP.sub(
        lambda m: m.group(1)
        if _BLOCK_TAG.match(m.group(1)) or _BLOCK_TAG.match(m.group(2))
        else m.group(0),
        prose,
    )


def compact(html: str) -> str:
    """
    Strip whitespace between block tags while preserving content inside <pre> blocks.

    This is required before pushing HTML to a Webflow RichText field. Content inside
    <pre>...</pre> (typically JSON-LD or code examples) is left untouched so formatting
    stays readable in rendered output. Whitespace between two inline tags
    (e.g. `</strong> <em>`) is meaningful rendered text and is also preserved.

    Args:
        html: HTML string to compact.

    Returns:
        HTML with whitespace between block tags stripped, except within <pre> blocks.
    """
    out = []
    i = 0
    while i < len(html):
        pre_match = re.search(r'<pre[^>]*>[\s\S]*?</pre>', html[i:])
        if pre_match:
            prose = _strip_block_whitespace(html[i:i + pre_match.start()])
            # <pre> is block-level, so a tag-to-tag gap on either side of the
            # block is stripped too (the segment loop would otherwise miss both).
            prose = re.sub(r'>\s+\Z', '>', prose)
            out.append(prose)
            out.append(pre_match.group(0))
            i += pre_match.end()
            trailing_gap = re.match(r'\s+(?=<)', html[i:])
            if trailing_gap:
                i += trailing_gap.end()
        else:
            out.append(_strip_block_whitespace(html[i:]))
            break
    return ''.join(out)


def to_compact_html(md: str) -> str:
    """
    Render markdown to HTML and apply the compact() helper.

    Strips leading YAML frontmatter if present. Uses the 'tables' and 'fenced_code'
    markdown extensions. Tables are rendered as <table>, but a bare <table> renders
    broken in Webflow RichText (flattened, or surviving but unstyled). Wrap tables in a
    <div data-rt-embed-type="true">...</div> Rich Text HTML-Embed AND style them via
    site CSS scoped to the rich-text wrapper (see references/webflow-richtext-tables.md).
    Bullet lists remain a fine fallback.

    Args:
        md: Markdown source. May include leading YAML frontmatter.

    Returns:
        Compact HTML ready for Webflow RichText push.

    Raises:
        ImportError: if the `markdown` package is not installed.
    """
    if _markdown is None:
        raise ImportError(
            "The `markdown` package is required. Install with: pip3 install markdown"
        )
    # Frontmatter must open at the very start of the document and close with a
    # `---` on its own line. A document that merely starts with a horizontal
    # rule (`---` followed by a blank line and prose, no closing delimiter)
    # is left intact.
    md_clean = re.sub(r'\A---[^\S\n]*\n[\s\S]*?\n---[^\S\n]*(?:\n|\Z)', '', md, count=1).strip()
    html = _markdown.markdown(md_clean, extensions=['tables', 'fenced_code'])
    return compact(html)


if __name__ == '__main__':
    # Smoke test: `python3 scripts/compact.py` (also run by CI).

    # Block-tag whitespace is stripped (the Webflow list-drop bug)
    assert compact("<ul>\n<li>a</li>\n<li>b</li>\n</ul>") == "<ul><li>a</li><li>b</li></ul>"

    # Whitespace between inline tags is meaningful text and survives
    inline = "<p><strong>bold</strong> <em>italic</em></p>"
    assert compact(inline) == inline, compact(inline)

    # Mixed: block gap collapses, inline gap survives, in the same document
    mixed = "<p><code>a</code> <code>b</code></p>\n<p>next</p>"
    assert compact(mixed) == "<p><code>a</code> <code>b</code></p><p>next</p>", compact(mixed)

    # <pre> content is preserved verbatim
    pre = "<pre><code>line1\n  line2</code></pre>\n<p>after</p>"
    assert compact(pre) == "<pre><code>line1\n  line2</code></pre><p>after</p>", compact(pre)

    if _markdown is not None:
        # Real frontmatter is stripped
        fm = "---\ntitle: X\n---\n\n# Head\n\nBody."
        assert "title" not in to_compact_html(fm)
        assert "<h1>Head</h1>" in to_compact_html(fm)

        # A document that merely starts with a horizontal rule is NOT truncated
        hr = "---\n\nOpening paragraph stays."
        assert "Opening paragraph stays." in to_compact_html(hr)

        sample_md = """# Sample

A paragraph.

- **first** — with a dash separator
- **second** — another item

```json
{"@type": "Example"}
```
"""
        out = to_compact_html(sample_md)
        assert "<ul><li>" in out and "\n<li>" not in out
        print(out)

    print("compact smoke test: OK")
