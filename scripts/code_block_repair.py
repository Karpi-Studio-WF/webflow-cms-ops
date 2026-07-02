"""
code_block_repair.py — multi-language code-block normalization for Webflow RichText.

Pure, importable transforms (no I/O, no API calls, no collection IDs, no article
content). Use it as a library, like `compact.py` — not as a standalone command.

This is the pre-upload transform referenced by `SKILL.md` ("Code block
formatting in rich text"): it promotes legacy `<p><code>` blocks to
root-level `<pre><code>`, assigns a `language-` class by inspecting the
code content, and relabels a confidently-wrong class. The `language-X` class is
what a highlighter (e.g. highlight.js) hooks, so a missing or wrong class means
no highlighting.

Three operations (see `references/content-repair-pattern.md` and
`references/fix-pass-pattern.md`):

    A  legacy multi-line <p><code> ........... -> <pre><code class="language-X">CONTENT\n</code></pre>
    B  bare <pre><code> (no language class) .. -> add class="language-X" (inner untouched)
    D  mislabeled classed <pre><code> ........ -> relabel class only, and ONLY on a confident
                                                 STRONG-language mismatch (inner untouched)

Left untouched: correctly-classed blocks, inline `<code>` pills, prose, and
`{{wf}}` bindings.

Language detection is a deliberately small heuristic, not a parser. It recognizes
html, python, javascript, json, sql, bash, and plaintext from content shape, and
returns `confident=False` (with language "unknown"/"ambig") when it cannot tell.
The transforms here never guess a class on a non-confident result:
  - `fix_precode_classes` leaves an unsure bare block bare (adds no class).
  - `convert_legacy_blocks` must emit *some* class, so it uses `fallback`
    (default "plaintext", which renders as an un-highlighted code block) rather
    than ever writing the meaningless `language-unknown`.

`overrides` lets a caller pin the language for blocks the heuristic can't infer
from content alone (e.g. a prompt-text block that reads like prose). Pass a list
of `(substring, language)` pairs; if `substring` appears in the decoded block,
that language wins. Defaults to empty, so the module is fully generic.

Typical use inside a fix pass (the audit/stage harness lives in
`scripts/repair_template.py`; drop one of these in as its `transform()`):

    from code_block_repair import repair_code_blocks, code_block_markers

    new_html = repair_code_blocks(old_html)                  # generic
    new_html = repair_code_blocks(old_html, overrides=[      # pin a stubborn block
        ("You are a helpful assistant", "plaintext"),
    ])

Run this file directly to execute its smoke test: `python3 scripts/code_block_repair.py`.
"""
import re
from html import unescape

# Languages confident enough to act on a *relabel* (operation D). A weak guess
# (e.g. a one-line snippet that merely looks bash-ish) never overrides an
# existing class.
STRONG = {"json", "html", "python", "javascript", "bash", "sql"}

_BR = re.compile(r'<br\s*/?>', re.I)
_NBSP = re.compile(r'&nbsp;')
_ZWJ = chr(0x200D)
_PCODE_BLOCK = re.compile(r'<p>\s*<code>(.*?)</code>\s*</p>', re.S)
_PRECODE = re.compile(r'(<pre\b[^>]*>\s*<code\b)([^>]*?)(>)(.*?)(</code>\s*</pre>)', re.S)


def decode_inner(inner: str) -> str:
    """The plain code text the detector sees: <br> -> newline, &nbsp; -> space,
    tags stripped, entities unescaped."""
    s = _BR.sub('\n', inner)
    s = _NBSP.sub(' ', s)
    return unescape(re.sub(r'<[^>]+>', '', s)).strip()


def detect(decoded: str, overrides=()) -> tuple[str, bool]:
    """Classify decoded code text. Returns (language, confident).

    `decoded` is plain code (see `decode_inner`). When the content is too sparse
    or ambiguous to call, returns confident=False with language in
    {"unknown", "ambig", "plaintext"}; callers must not assign a class then."""
    s = decoded.strip()
    for sub, lang in overrides:
        if sub in s:
            return lang, True
    if not s:
        return "plaintext", False
    if re.search(r'[├└│]', s):  # box-drawing -> a directory/tree dump
        return "plaintext", True
    if re.match(r'<(!--|!doctype|html|head|body|div|span|script|style|ul|ol|li|table|tr|td|th|h[1-6]|img|section|nav|header|footer|main|button|form|input|label|meta|link|a\b|p\b|svg|path|iframe|figure|video|source)', s, re.I):
        return "html", True
    js_imp = bool(re.search(r'\bimport\b.*\bfrom\b|\brequire\s*\(', s))
    py_imp = bool(re.search(r'^\s*import\s+\w|^\s*from\s+[\w.]+\s+import\b', s, re.M))
    py_compr = bool(re.search(r'[\[{][^\]}]*\bfor\s+\w+\s+in\b', s, re.S)) and not re.search(r'\bdo\b', s)
    js = bool(re.search(r'\b(const|let|var)\s+[\w{]|\bfunction\b|=>|\bconsole\.\w|\bdocument\.\w|\bwindow\.\w|\bexport\b|`|(?<!:)//', s)) or js_imp
    py = bool(re.search(r'\bdef\s+\w+\s*\(|\bprint\s*\(|\bself\b|\belif\b|\b__\w+__\b|(?<![\w$])f["\']|\bNone\b|\bTrue\b|\bFalse\b|\.append\(', s, re.M)) or (py_imp and not js_imp) or py_compr
    bash = bool(re.search(r'(^|\n)\s*(\$\s|#!/|cd\s|ls\s|npm\s|npx\s|pip3?\s|python3?\s|node\s|bash\s|sh\s|source\s|git\s|curl\s|wget\s|chmod\s|mkdir\s|sudo\s|brew\s|sips\s|file\s)', s)) or bool(re.search(r'\bfor\s+\w+\s+in\b.*?\bdo\b', s, re.S)) or bool(re.search(r'(^|\n)\s*done\s*$', s, re.M))
    sql = bool(re.search(r'\b(SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|CREATE\s+TABLE|ALTER\s+TABLE|DROP\s+TABLE)\b', s, re.I))
    jsonl = (s[:1] in '{[' or bool(re.match(r'"[\w@$-]+"\s*:', s))) and bool(re.search(r'"[\w@$-]+"\s*:', s)) and not re.search(r'(?<!:)//', s)
    if py and js:
        return "ambig", False
    if py:
        return "python", True
    if js:
        return "javascript", True
    if jsonl:
        return "json", True
    if sql:
        return "sql", True
    if bash:
        return "bash", True
    return "unknown", False


def convert_legacy_blocks(html: str, overrides=(), fallback: str = "plaintext") -> str:
    """Operation A. Rewrite legacy multi-line `<p><code>...</code></p>` (carrying
    <br>/&nbsp;/newlines, or simply long) to the round-trip-safe
    `<pre><code class="language-X">CONTENT\\n</code></pre>` shape.

    Idempotent: a `<p><code>` that is a short single-line inline reference is left
    alone, and existing `<pre><code>` is not matched. When detection is not
    confident, uses `fallback` for the class rather than emitting language-unknown."""
    def repl(m):
        inner = m.group(1)
        if not (_BR.search(inner) or _NBSP.search(inner) or '\n' in inner or len(decode_inner(inner)) > 80):
            return m.group(0)  # short inline <code>, leave as a pill
        lang, conf = detect(decode_inner(inner), overrides)
        if not conf:
            lang = fallback
        body = _BR.sub("\n", inner)
        body = _NBSP.sub(" ", body)
        body = body.replace(_ZWJ, "").rstrip().replace('"', '&quot;')
        return f'<pre><code class="language-{lang}">{body}\n</code></pre>'
    return _PCODE_BLOCK.sub(repl, html)


def fix_precode_classes(html: str, overrides=()) -> str:
    """Operations B and D. Add a `language-X` class to a bare `<pre><code>`, and
    relabel a classed `<pre><code>` only on a confident STRONG-language mismatch.
    Never guesses a class when detection is not confident; never touches the inner
    text. Idempotent."""
    def repl(m):
        open_, attrs, gt, inner, close = m.groups()
        cm = re.search(r'class\s*=\s*"([^"]*)"', attrs)
        dec = decode_inner(inner)
        lang, conf = detect(dec, overrides)
        if not cm or 'language-' not in cm.group(1):
            # B: add a class, but only if we actually know the language
            if not conf and lang in ("unknown", "ambig"):
                return m.group(0)
            if cm:
                newattrs = re.sub(r'class\s*=\s*"([^"]*)"', lambda c: f'class="{c.group(1)} language-{lang}"', attrs)
            else:
                newattrs = attrs + f' class="language-{lang}"'
            return open_ + newattrs + gt + inner + close
        # D: relabel an existing language-* class, conservatively
        existing = re.search(r'language-([a-z0-9]+)', cm.group(1)).group(1)
        norm = {"js": "javascript", "py": "python", "sh": "bash", "shell": "bash", "text": "plaintext"}.get(existing, existing)
        if conf and lang in STRONG and lang != norm:
            newcls = cm.group(1).replace(f'language-{existing}', f'language-{lang}')
            return open_ + re.sub(r'class\s*=\s*"[^"]*"', f'class="{newcls}"', attrs) + gt + inner + close
        return m.group(0)
    return _PRECODE.sub(repl, html)


def repair_code_blocks(html: str, overrides=(), fallback: str = "plaintext") -> str:
    """Compose A then B/D: convert legacy `<p><code>` blocks, then add/fix
    `language-` classes on `<pre><code>`. Pure and idempotent."""
    return fix_precode_classes(convert_legacy_blocks(html, overrides, fallback), overrides)


def code_block_languages(html: str) -> list:
    """The `language-X` value of each `<pre><code>` in document order; None for a
    block that carries no language class. Useful for before/after verification."""
    out = []
    for m in _PRECODE.finditer(html):
        mm = re.search(r'language-([a-z0-9]+)', m.group(2))
        out.append(mm.group(1) if mm else None)
    return out


def code_block_markers(html: str) -> dict:
    """Structural counts for pre/post verification in a fix pass (see
    `references/content-repair-pattern.md`). After a repair, `legacy` and
    `bare_pre` should be 0, while `h2`/`h3`/`pills`/`wf` must be unchanged."""
    return {
        "h2": len(re.findall(r"<h2[^>]*>", html)),
        "h3": len(re.findall(r"<h3[^>]*>", html)),
        "pre": len(re.findall(r"<pre[^>]*>", html)),
        "bare_pre": sum(1 for m in _PRECODE.finditer(html) if 'language-' not in m.group(2)),
        "legacy": sum(
            1 for m in _PCODE_BLOCK.finditer(html)
            if _BR.search(m.group(1)) or _NBSP.search(m.group(1)) or '\n' in m.group(1) or len(decode_inner(m.group(1))) > 80
        ),
        "pills": len(re.findall(r'<code\b', _PCODE_BLOCK.sub('', re.sub(r'<pre\b.*?</pre>', '', html, flags=re.S)))),
        "wf": html.count('{{wf'),
    }


if __name__ == "__main__":
    # Smoke test: pure transforms, no network. `python3 scripts/code_block_repair.py`.
    sql_legacy = "<p><code>SELECT *<br>FROM users<br>WHERE id = 1;</code></p>"
    out = repair_code_blocks(sql_legacy)
    assert '<pre><code class="language-sql">' in out, out
    assert "<p><code>" not in out

    bare_py = "<pre><code>def f():\n    return None</code></pre>"
    out2 = repair_code_blocks(bare_py)
    assert 'class="language-python"' in out2, out2

    inline = "<p>Install it with <code>npm i</code> first.</p>"
    assert repair_code_blocks(inline) == inline  # inline pill left alone

    # idempotency
    assert repair_code_blocks(out) == out
    assert repair_code_blocks(out2) == out2

    # non-confident legacy falls back instead of writing language-unknown
    mystery = "<p><code>aaa<br>bbb<br>ccc ddd eee fff</code></p>"
    out3 = repair_code_blocks(mystery)
    assert 'class="language-plaintext"' in out3, out3
    assert "language-unknown" not in out3

    # override pins a block the heuristic would call prose
    pinned = repair_code_blocks(mystery, overrides=[("bbb", "yaml")])
    assert 'class="language-yaml"' in pinned, pinned

    print("code_block_repair smoke test: OK")
