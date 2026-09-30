"""Blind model + ante scaling, ported from blind.lua and misc_functions.lua.

- `get_blind_amount(ante, scaling)` — misc_functions:919 (table + endless).
- `Blind.set_chips` — blind.lua:107 `chips = get_blind_amount(ante)*mult*scaling`.

Boss blind mechanics are intentionally thin in v1: the core few are honored
(debuffing a suit / debuffing face cards), and the rest are represented as data
(name + description) with no mechanical effect yet.
"""

from __future__ import annotations

import math

from .card import Card


def get_blind_amount(ante: int, scaling: int = 1) -> int:
    amounts = {
        1: [300, 800, 2000, 5000, 11000, 20000, 35000, 50000],
        2: [300, 900, 2600, 8000, 20000, 36000, 60000, 100000],
        3: [300, 1000, 3200, 9000, 25000, 60000, 110000, 200000],
    }[scaling]
    if ante < 1:
        return 100
    if ante <= 8:
        return amounts[ante - 1]
    k = 0.75
    a, b, c, d = amounts[7], 1.6, ante - 8, 1 + 0.2 * (ante - 8)
    amount = int(a * (b + (k * c) ** d) ** c)
    # round down to 2 significant figures: amount - (amount % 10^(floor(log10(amount))-1))
    sig = 10 ** (int(math.log10(amount)) - 1) if amount > 0 else 1
    return amount - (amount % sig)


class Blind:
    def __init__(self, key: str, data: dict, ante: int, scaling: int = 1):
        self.key = key
        self.name = data.get("name", key)
        self.mult = data.get("mult", 1)
        self.dollars = data.get("dollars", 3)
        self.debuff = data.get("debuff", {}) or {}
        self.is_boss = bool(data.get("boss"))
        self.ante = ante
        self.chips = 0
        self.set_chips(ante, scaling)

    def set_chips(self, ante: int, scaling: int = 1) -> None:
        self.chips = int(get_blind_amount(ante, scaling) * self.mult * scaling)

    @property
    def kind(self) -> str:
        return "boss" if self.is_boss else ("big" if self.mult >= 1.5 else "small")

    def debuffs_suit(self, suit: str) -> bool:
        return self.debuff.get("suit") == suit

    def debuffs_faces(self) -> bool:
        return self.debuff.get("is_face") == "face"

    def debuff_card(self, card: Card) -> bool:
        """Return True if this blind debuffs `card` (suit debuff / face debuff)."""
        if card.debuffed:
            return True
        if self.debuff.get("suit") and card.suit == SUIT_LETTER(self.debuff["suit"]):
            return True
        if self.debuffs_faces() and card.is_face:
            return True
        return False

    def modify_hand(self, cards, poker_hands, handname, mult, chips):
        """Boss hand modification. v1: identity (returns modded=False)."""
        return mult, chips, False

    def is_defeated(self, chips: int) -> bool:
        return chips >= self.chips


def SUIT_LETTER(name: str) -> str:
    return {"Spades": "S", "Hearts": "H", "Diamonds": "D", "Clubs": "C"}.get(name, "S")