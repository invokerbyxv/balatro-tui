"""Deck construction, mirroring the 52-card base deck in game.lua P_CARDS.

Ranks use CLI glyphs; suits are letters. The base deck is one card per
rank/suit combo. `no_faces` (Abandoned Deck) removes J/Q/K.
"""

from __future__ import annotations

from .card import Card

RANKS = ["A", "K", "Q", "J", "T", "9", "8", "7", "6", "5", "4", "3", "2"]
SUITS = ["S", "H", "C", "D"]


def build_standard_deck(no_faces: bool = False) -> list[Card]:
    deck = []
    for r in RANKS:
        if no_faces and r in ("J", "Q", "K"):
            continue
        for s in SUITS:
            deck.append(Card(r, s))
    return deck