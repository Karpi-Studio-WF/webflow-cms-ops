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


def compact(html: str) -> str:
    """
    Strip whitespace between block tags while preserving content inside <pre> blocks.

    This is required before pushing HTML to a Webflow RichText field. Content inside
    <pre>...</pre> (typically JSON-LD or code examples) is left untouched so formatting
    stays readable in rendered output.

    Args:
        html: HTML string to compact.

    Returns:
        HTML with all whitespace between tags stripped, except within <pre> blocks.
    """
    out = []
    i = 0
    while i < len(html):
        pre_match = re.search(r'<pre[^>]*>[\s\S]*?</pre>', html[i:])
        if pre_match:
            prose = html[i:i + pre_match.start()]
            out.append(re.sub(r'>\s+<', '><', prose))
            out.append(pre_match.group(0))
            i += pre_match.end()
        else:
            out.append(re.sub(r'>\s+<', '><', html[i:]))
            break
    return ''.join(out)


def to_compact_html(md: str) -> str:
    """
    Render markdown to HTML and apply the compact() helper.

    Strips leading YAML frontmatter if present. Uses the 'tables' and 'fenced_code'
    markdown extensions. Tables are rendered as <table> — which Webflow RichText will
    strip — so convert tables to bullet lists in your markdown source before calling
    this function.

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
    md_clean = re.sub(r'^---[\s\S]*?---', '', md).strip()
    html = _markdown.markdown(md_clean, extensions=['tables', 'fenced_code'])
    return compact(html)


if __name__ == '__main__':
    # Demo / smoke test
    sample_md = """# Sample

A paragraph.

- **first** — with a dash separator
- **second** — another item

```json
{"@type": "Example"}
```
"""
    print(to_compact_html(sample_md))
