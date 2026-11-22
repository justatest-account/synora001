"""Persian/Arabic text shaping for Kivy (Kivy itself does not shape or reorder RTL text).

shape()        - for short labels
layout_text()  - word-wraps the *logical* text first, then shapes every line,
                 so long Persian messages wrap correctly in chat bubbles.
"""
import re

try:
    import arabic_reshaper
except Exception:                      # pragma: no cover
    arabic_reshaper = None
try:
    from bidi.algorithm import get_display
except Exception:                      # pragma: no cover
    try:
        from bidi import get_display
    except Exception:
        get_display = None

_RTL = re.compile("[\u0590-\u08FF\uFB1D-\uFDFF\uFE70-\uFEFF]")


def has_rtl(s: str) -> bool:
    return bool(_RTL.search(s))


def para_rtl(s: str) -> bool:
    """First strong character decides the paragraph direction."""
    for ch in s:
        if _RTL.match(ch):
            return True
        if ch.isalpha():
            return False
    return False


def reshape(s: str) -> str:
    if not s or arabic_reshaper is None or not has_rtl(s):
        return s
    # ZWNJ is removed AFTER shaping: letters stay unjoined but fonts never draw a box
    return arabic_reshaper.reshape(s).replace("\u200c", "")


def _bidi(s: str, rtl: bool) -> str:
    if get_display is None or not has_rtl(s):
        return s
    return get_display(s, base_dir="R" if rtl else "L")


def shape_line(s: str, rtl=None) -> str:
    if rtl is None:
        rtl = para_rtl(s)
    return _bidi(reshape(s), rtl)


def shape(s: str) -> str:
    if not s or not has_rtl(s):
        return s
    return "\n".join(shape_line(line) for line in s.split("\n"))


def _break_long(word, measure, max_w):
    parts = []
    while len(word) > 1 and measure(reshape(word)) > max_w:
        k = len(word) - 1
        while k > 1 and measure(reshape(word[:k])) > max_w:
            k -= 1
        parts.append(word[:k])
        word = word[k:]
    return parts, word


def layout_text(text: str, measure, max_w: float):
    """-> (display_text, is_rtl). `measure(str) -> pixel width`."""
    rtl = para_rtl(text)
    lines = []
    for para in text.split("\n"):
        cur = ""
        for w in para.split(" "):
            cand = w if not cur else cur + " " + w
            if not cur or measure(reshape(cand)) <= max_w:
                cur = cand
            else:
                lines.append(cur)
                cur = w
            if " " not in cur and measure(reshape(cur)) > max_w:
                parts, cur = _break_long(cur, measure, max_w)
                lines.extend(parts)
        lines.append(cur)
    return "\n".join(shape_line(ln, rtl) for ln in lines), rtl
