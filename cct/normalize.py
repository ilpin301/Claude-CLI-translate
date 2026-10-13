"""Pure text normalisation for terminal selections (no Windows/Qt imports).

Pipeline (see PLAN.md step 4):
1. Unify line endings, drop NUL / zero-width chars, map NBSP-like spaces to ' ', rstrip every row
   (UIA pads each terminal row with trailing spaces).
2. Table detection runs on the ORIGINAL rows, before decoration is stripped: a row whose content
   (after peeling the outer border) still has a box-drawing char inside, or a pure border row with a
   junction char (┬ ┼ ├ ...), marks the text as a table. A plain bordered text box ("│ prose │") is
   not a table.
3. Claude Code TUI decoration is stripped from each row: leading box-drawing chars, bullets (● ⏺ ⎿ •)
   and prompt markers (> ❯), each with one following space, plus a trailing border. Rows that are
   only decoration become blank.
4. Code/block mode (newlines kept verbatim, inner spacing kept) if ANY of: table (above), a tab,
   4+ leading spaces (checked AFTER decoration stripping), a ``` fence, or >= 3 non-blank rows
   whose lengths are all within 2 chars of each other and >= 20 chars (typical of a block/columnar
   selection). Table mode keeps the original rows (borders included); other code modes keep the
   decoration-stripped rows.
5. Prose mode: single hard line breaks are joined with a space, blank-line paragraph breaks are kept
   (one blank line), runs of 2+ spaces collapse to one.
6. Cap at max_chars; the second return value says whether the cap cut the text.
"""
import re
from typing import List, Tuple

_BOX = "".join(chr(c) for c in range(0x2500, 0x2580))  # U+2500..U+257F box drawing
_JUNCTION_ONLY = "┬┴┼├┤╦╩╬╠╣╤╧╪╟╢╫╥╨╞╡"
_BULLETS = "●⏺⎿•"

_NOISE = re.compile("[\x00​‌‍﻿]")
_SPACES = re.compile("[      ]")
_LEAD_BOX = re.compile("^ *[%s]+ ?" % re.escape(_BOX))
_LEAD_BULLET = re.compile("^ *[%s](?: |$)" % re.escape(_BULLETS))
_LEAD_PROMPT = re.compile("^[>❯](?: |$)")
_TRAIL_BOX = re.compile("[ ]*[%s]+$" % re.escape(_BOX))
_INNER_BOX = re.compile("[%s]" % re.escape(_BOX))
_MULTI_SPACE = re.compile(" {2,}")

MIN_BLOCK_LEN = 20
MAX_BLOCK_SPREAD = 2


def _strip_decoration(row: str) -> str:
    while True:
        new = _LEAD_BOX.sub("", row, count=1)
        new = _LEAD_BULLET.sub("", new, count=1)
        new = _LEAD_PROMPT.sub("", new, count=1)
        if new == row:
            break
        row = new
    return _TRAIL_BOX.sub("", row).rstrip()


def _row_is_table(row: str) -> bool:
    body = _strip_decoration(row)
    if not body:  # pure border row: only a junction marks a table
        return any(c in _JUNCTION_ONLY for c in row)
    return bool(_INNER_BOX.search(body))


def _trim_blank_edges(rows: List[str]) -> List[str]:
    start, end = 0, len(rows)
    while start < end and not rows[start]:
        start += 1
    while end > start and not rows[end - 1]:
        end -= 1
    return rows[start:end]


def _is_block(rows: List[str]) -> bool:
    if any("\t" in r or r.startswith("    ") or r.lstrip().startswith("```") for r in rows):
        return True
    lengths = [len(r) for r in rows if r]
    return (len(lengths) >= 3 and min(lengths) >= MIN_BLOCK_LEN
            and max(lengths) - min(lengths) <= MAX_BLOCK_SPREAD)


def _join_prose(rows: List[str]) -> str:
    paragraphs, cur = [], []
    for r in rows:
        if r:
            cur.append(r.strip())
        elif cur:
            paragraphs.append(" ".join(cur))
            cur = []
    if cur:
        paragraphs.append(" ".join(cur))
    return _MULTI_SPACE.sub(" ", "\n\n".join(paragraphs))


def normalize(text: str, max_chars: int = 5000) -> Tuple[str, bool]:
    """Return (normalised text, truncated). Empty/whitespace-only input gives ("", False)."""
    if not text or not text.strip():
        return "", False
    text = _SPACES.sub(" ", _NOISE.sub("", text))
    original = [r.rstrip() for r in re.split(r"\r\n|\r|\n", text)]
    table = any(_row_is_table(r) for r in original if r)
    if table:
        rows = _trim_blank_edges(original)
        out = "\n".join(rows)
    else:
        rows = _trim_blank_edges([_strip_decoration(r) for r in original])
        out = "\n".join(rows) if _is_block(rows) else _join_prose(rows)
    if len(out) > max_chars:
        return out[:max_chars].rstrip(), True
    return out, False
