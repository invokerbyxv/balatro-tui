"""Playing-card model, ported from balatro_source_code/card.lua.

Covers the subset of Card needed for hand evaluation + scoring:
rank->id/nominal (set_base ~97), get_id (~957), get_nominal (~950),
is_suit(~4064), enhancement/edition data.

A card's rank is one of 2-9, T, J, Q, K, A; suit one of S,H,D,C.
Stone cards (from Marble Joker / Stone enhancement) have a non-rank id so they
never combine into same-of-kind or straights.
"""

from __future__ import annotations

RANK_IDS = {"2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8,
            "9": 9, "T": 10, "J": 11, "Q": 12, "K": 13, "A": 14}
RANK_RANKUPS = {"10": "T", **{r: r for r in RANK_IDS}}
ID_RANKS = {v: k for k, v in RANK_IDS.items()}

SUIT_NAME = {"S": "Spades", "H": "Hearts", "D": "Diamonds", "C": "Clubs"}
SUIT_NOMINAL = {"D": 0.01, "C": 0.02, "H": 0.03, "S": 0.04}
FACE_NOMINAL = {"J": 0.1, "Q": 0.2, "K": 0.3, "A": 0.4}
STONE_ID = -1  # non-rank sentinel


def rank_nominal(rank: str) -> int:
    """Card nominal (2-10 numeric, faces=10, Ace=11) — the scoring chip base."""
    return RANK_IDS[rank] if rank not in ("J", "Q", "K", "A") else (10 if rank != "A" else 11)


class Card:
    __slots__ = ("rank", "suit", "enhancement", "edition", "seal", "debuffed")

    def __init__(self, rank: str, suit: str, enhancement: str | None = None,
                 edition: str | None = None, seal: str | None = None):
        self.rank = rank
        self.suit = suit
        # enhancement: 'm_bonus', 'm_mult', 'm_glass', ... (Enhanced set key)
        self.enhancement = enhancement
        # edition: 'e_foil', 'e_holo', 'e_polychrome', 'e_negative', 'e_eternal'
        self.edition = edition
        # seal: 's_red', 's_blue', 's_gold', 's_purple'
        self.seal = seal
        self.debuffed = False

    # -- identity -------------------------------------------------------------
    @property
    def id(self) -> int:
        if self.enhancement == "m_stone":
            return STONE_ID
        return RANK_IDS[self.rank]

    @property
    def is_face(self) -> bool:
        return self.id in (11, 12, 13)

    def nominal(self) -> float:
        base = rank_nominal(self.rank)
        base = -1000 if self.enhancement == "m_stone" else base
        return base + SUIT_NOMINAL[self.suit] + FACE_NOMINAL.get(self.rank, 0.0)

    def is_suit(self, suit: str, wild_beats_double: bool = False) -> bool:
        """Mirror is_suit(flush_calc): stone is never a suit; Wild counts for all."""
        if self.enhancement == "m_stone":
            return False
        if self.enhancement == "m_wild" and not self.debuffed:
            return True
        return self.suit == suit

    # -- economy --------------------------------------------------------------
    @property
    def sell_cost(self) -> int:
        return max(1, 0 if self.enhancement else 1)

    def __repr__(self) -> str:
        return f"{self.rank}{self.suit}"


def card_id(rank: str) -> int:
    return RANK_IDS[rank]