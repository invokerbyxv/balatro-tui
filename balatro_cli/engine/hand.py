"""Poker-hand detection, a faithful port of misc_functions.lua.

- `evaluate_poker_hand`  (~376) — the 12-tier hand table + top resolution.
- `get_flush`            (~522) — 4-card threshold under Four Fingers.
- `get_straight`         (~548) — 4-card under Four Fingers, rank-skip under
                                  Shortcut, Ace-low via `j==1 and 14`.
- `get_X_same`           (~592) — N-of-a-kind.
- `get_highest`          (~613) — High Card (by nominal).

Joker flags (Four Fingers / Shortcut / Smeared Joker) are passed in since the
Lua reads them via `find_joker(...)`. Empty-list emptiness replaces Lua's
`next() == nil` checks; truthiness of a list stays faithful.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable
from .card import Card

HAND_NAMES = [
    "Flush Five", "Flush House", "Five of a Kind", "Straight Flush",
    "Four of a Kind", "Full House", "Flush", "Straight", "Three of a Kind",
    "Two Pair", "Pair", "High Card",
]


@dataclass
class JokerFlags:
    four_fingers: bool = False
    shortcut: bool = False
    smeared: bool = False
    pareidolia: bool = False   # every card counts as a face card (card.lua:964)


def get_X_same(num: int, hand: list[Card]) -> list[list[Card]]:
    groups: dict[int, list[Card]] = {}
    for i in range(len(hand) - 1, -1, -1):
        curr = [hand[i]]
        for j in range(len(hand)):
            if i != j and hand[i].id == hand[j].id:
                curr.append(hand[j])
        if len(curr) == num:
            groups[hand[i].id] = curr  # last (lowest index) assignment wins, as in Lua
    return [groups[g] for g in sorted(groups, reverse=True)]


def get_flush(hand: list[Card], flags: JokerFlags) -> list[list[Card]]:
    threshold = 5 if not flags.four_fingers else 4
    if len(hand) > 5 or len(hand) < threshold:
        return []
    for suit in ("S", "H", "C", "D"):
        t = [c for c in hand if _is_suit(c, suit, flags, flush_calc=True)]
        if len(t) >= threshold:
            return [t]
    return []


def get_straight(hand: list[Card], flags: JokerFlags) -> list[list[Card]]:
    threshold = 5 if not flags.four_fingers else 4
    if len(hand) > 5 or len(hand) < threshold:
        return []
    ids: dict[int, list[Card]] = {}
    for c in hand:
        if 1 < c.id < 15:  # skip stone (-1) and sentinels
            ids.setdefault(c.id, []).append(c)

    straight_length = 0
    found = False
    skipped = False
    t: list[Card] = []
    for j in range(1, 15):
        pid = 14 if j == 1 else j  # Ace-low
        if pid in ids:
            straight_length += 1
            skipped = False
            t.extend(ids[pid])
        elif flags.shortcut and not skipped and j != 14:
            skipped = True
        else:
            straight_length = 0
            skipped = False
            if not found:
                t = []
            else:
                break
        if straight_length >= threshold:
            found = True
    if not found:
        return []
    return [t]


def _is_suit(card: Card, suit: str, flags: JokerFlags, flush_calc: bool) -> bool:
    """Mirror Card:is_suit flush_calc path (stone never; wild always; smeared group).

    `suit` is the single letter (S/H/C/D); card.suit is likewise a letter.
    """
    if card.enhancement == "m_stone":
        return False
    if card.enhancement == "m_wild" and not card.debuffed:
        return True
    if flags.smeared:
        red = ("H", "D")
        if (card.suit in red) == (suit in red):
            return True
    return card.suit == suit


def get_highest(hand: list[Card]) -> list[list[Card]]:
    if not hand:
        return []
    return [[max(hand, key=lambda c: c.nominal())]]


def evaluate_poker_hand(hand: list[Card], flags: JokerFlags | None = None) -> dict:
    flags = flags or JokerFlags()
    results: dict[str, list[Card]] = {name: [] for name in HAND_NAMES}
    top: list[Card] | None = None
    top_key: str | None = None

    _5 = get_X_same(5, hand)
    _4 = get_X_same(4, hand)
    _3 = get_X_same(3, hand)
    _2 = get_X_same(2, hand)
    _flush = get_flush(hand, flags)
    _straight = get_straight(hand, flags)
    _highest = get_highest(hand)

    def place(name: str, groups: list[list[Card]]) -> None:
        nonlocal top, top_key
        if not groups:
            return
        results[name] = groups[0]
        if top is None:
            top, top_key = groups[0], name

    if _5 and _flush:
        place("Flush Five", _5)
    if _3 and _2 and _flush:
        place("Flush House", [_3[0] + _2[0]])
    if _5:
        place("Five of a Kind", _5)
    if _flush and _straight:
        fset = set(_flush[0])
        s = list(_straight[0])
        combined = list(_flush[0]) + [c for c in s if c not in fset]
        place("Straight Flush", [combined])
    if _4:
        place("Four of a Kind", _4)
    if _3 and _2:
        place("Full House", [_3[0] + _2[0]])
    if _flush:
        place("Flush", _flush)
    if _straight:
        place("Straight", _straight)
    if _3:
        place("Three of a Kind", _3)
    if len(_2) >= 2 or (len(_3) == 1 and len(_2) == 1):
        parts_a = _2[0]
        parts_b = _2[1] if len(_2) >= 2 else _3[0]
        place("Two Pair", [parts_a + parts_b])
    if _2:
        place("Pair", _2)
    if _highest:
        place("High Card", _highest)

    # downgrade block (5oak -> 4oak -> 3oak -> pair; 4oak -> 3oak -> pair)
    if results["Five of a Kind"]:
        results["Four of a Kind"] = results["Five of a Kind"][:4]
    if results["Four of a Kind"]:
        results["Three of a Kind"] = results["Four of a Kind"][:3]
    if results["Three of a Kind"]:
        results["Pair"] = results["Three of a Kind"][:2]

    results["top"], results["top_key"] = top, top_key
    return results


def get_poker_hand_info(hand: list[Card], flags: JokerFlags | None = None):
    """Return (hand_name, scoring_hand) for the best poker hand in `hand`."""
    results = evaluate_poker_hand(hand, flags)
    return results["top_key"], results["top"]