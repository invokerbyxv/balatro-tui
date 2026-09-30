"""Text helpers: card glyphs + localization rich-text -> plain ASCII.

The covert line-transcript format stays plain. The only permitted ANSI is an
optional dim (SGR 2) for secondary info; everything else is monochrome text.
"""

from __future__ import annotations

import re
from typing import Iterable

from ..engine.card import Card

SUIT_GLYPH = {"S": "♠", "H": "♥", "D": "♦", "C": "♣"}
SUIT_ASCII = {"S": "S", "H": "H", "D": "D", "C": "C"}

# rich-text markup in descriptions: {C:red}, {s:0.8}, {X:mult,C:white}, ... {}
_RICH = re.compile(r"\{[^{}]*\}")


def card_str(card: Card, glyphs: bool = False) -> str:
    suit = SUIT_GLYPH if glyphs else SUIT_ASCII
    s = f"{card.rank}{suit[card.suit]}"
    if card.enhancement:
        s += f"({card.enhancement[2:] if card.enhancement.startswith('e_') or card.enhancement.startswith('m_') else card.enhancement})"
    elif card.edition:
        s += f"({card.edition[2:]})"
    return s


def hand_str(cards: Iterable[Card], glyphs: bool = False) -> str:
    return " ".join(card_str(c, glyphs) for c in cards)


def strip_rich(text: str) -> str:
    """Remove all {C:...} markup, leaving plain ASCII text."""
    return _RICH.sub("", text).strip()


def render_loc_text(lines: list[str] | None, vars_: dict | None = None) -> str:
    """Join description lines -> one plain string, stripping markup + filling #N#."""
    text = " ".join(lines or []) if lines else ""
    text = strip_rich(text)
    if vars_:
        for i in range(1, len(vars_) + 1):
            text = text.replace(f"#{i}#", str(vars_.get(i, "")))
    return text


def number_format(num: int) -> str:
    """Compact ~MiscFns.number_format: commas up to 1e11, then e-notation."""
    if not isinstance(num, (int, float)):
        return ""
    num = int(num)
    if num >= 10 ** 11:
        # %.4g then mantissa with exponent
        x = float(f"{num:.4g}")
        fac = int(x) and len(str(int(x))) - 1 or 0
        return f"{x / (10 ** fac):.3f}e{fac}"
    return f"{num:,}"