from __future__ import annotations

import re

from aiogram.utils.text_decorations import html_decoration as hd


# ملخص: يبني نصاً منسقاً حسب النمط أو علامات الهاشتاغ.
class StyledText:
    def __init__(self, raw: str, style: str):
        self.raw = raw
        self.style = style

    def render(self) -> str:
        # First, attempt hashtag-based inline styling
        rendered = render_hashtag_markup(self.raw)
        if rendered is not None:
            return rendered
        # Fallback: legacy single-style handling
        text = hd.quote(self.raw)
        if self.style == "bold":
            return hd.bold(text)
        if self.style == "italic":
            return hd.italic(text)
        if self.style == "spoiler":
            return hd.spoiler(text)
        if self.style == "quote":
            return f"<blockquote>{text}</blockquote>"
        return text


STYLE_TAGS_MAP = {
    "تشويش": "spoiler",
    "عريض": "bold",
    "مائل": "italic",
    "اقتباس": "quote",
}


# Precompile alternation for tags
_TAG_ALT = "|".join(map(re.escape, STYLE_TAGS_MAP.keys()))
# Expanded whitespace to include NBSP/thin spaces often inserted by mobile keyboards
_WS = r"(?:\s|\u00A0|\u202F|\u2007)*"
# Regex over cleaned lines (no control marks). Allows spaces around text and after closing tag
_HASHTAG_RE = re.compile(
    r"#" + _WS + r"(" + _TAG_ALT + r")" + _WS + r"(.*?)" + _WS + r"#" + _WS + r"\1"
)
# Control/invisible marks to strip for matching (RTL/embedding/override/isolate)
_CF_CHARS = "".join(
    [
        "\u200c",  # ZWNJ
        "\u200d",  # ZWJ
        "\u200e",  # LRM
        "\u200f",  # RLM
        "\u061c",  # ALM
        "\u202a",  # LRE
        "\u202b",  # RLE
        "\u202c",  # PDF
        "\u202d",  # LRO
        "\u202e",  # RLO
        "\u2066",  # LRI
        "\u2067",  # RLI
        "\u2068",  # FSI
        "\u2069",  # PDI
    ]
)
_CF_RE = re.compile("[%s]" % _CF_CHARS)


# ملخص: يستنتج النمط العام من النص إذا كان محاطاً بعلامة نمط واحدة.
def parse_style_from_text(text: str) -> tuple[str, str]:
    # Keep backward-compat parse for whole-text wrapping (rare now)
    clean = text.strip()
    style = "plain"
    for tag_word, sty in STYLE_TAGS_MAP.items():
        tag = f"#{tag_word}"
        if clean.startswith(tag) and clean.endswith(tag):
            inner = clean[len(tag) : -len(tag)].strip()
            return inner, sty
    return clean, style


# ملخص: يحوّل أزواج الوسوم إلى HTML ويعيد None إن لم يوجد تغيير.
def render_hashtag_markup(text: str) -> str | None:
    """Render text by converting pairs of hashtag tags into HTML decorations.

    Returns rendered HTML string if any pair is found; otherwise returns None to allow fallback.
    """
    lines = text.splitlines()
    any_changed = False
    processed_lines: list[str] = []
    for line in lines:
        # Escape HTML first
        escaped = hd.quote(line)
        # Remove invisible marks for matching simplicity
        cleaned = _CF_RE.sub("", escaped)
        changed = cleaned
        # Replace multiple pairs per line
        while True:
            m = _HASHTAG_RE.search(changed)
            if not m:
                break
            tag_word = m.group(1)
            inner = m.group(2)
            sty = STYLE_TAGS_MAP.get(tag_word)
            if sty == "bold":
                repl = hd.bold(inner)
            elif sty == "italic":
                repl = hd.italic(inner)
            elif sty == "spoiler":
                repl = hd.spoiler(inner)
            elif sty == "quote":
                repl = f"<blockquote>{inner}</blockquote>"
            else:
                repl = inner
            changed = changed[: m.start()] + repl + changed[m.end() :]
            any_changed = True
        processed_lines.append(changed)
    if any_changed:
        return "\n".join(processed_lines)
    return None
