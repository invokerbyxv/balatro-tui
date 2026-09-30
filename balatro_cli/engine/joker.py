"""Joker effects, ported from joker.lua:calculate + common_events.lua.

v1 implements the common scoring subset of ~35 jokers (flat chips/mult and
hand-keyed bonuses); the rest are data-only — the shop still offers them and
their effects are no-ops. `calculate` mirrors the Balatro hook model and is
called from scoring.py's aggregate path.
"""

from __future__ import annotations

# keys whose ability is data-only in v1 (tracked for provenance only)
_DATA_ONLY: set[str] = set()


def calculate(key: str, hand_key: str | None, played, scoring, flags) -> dict | None:
    """Return an effect dict {chips/mult/x_mult} for `key`, or None."""
    fn = _CALCULATORS.get(key)
    if fn is None:
        _DATA_ONLY.add(key)
        return None
    return fn(hand_key, played, scoring, flags)


# -- predicates -------------------------------------------------------------
def _is_suit(ch, suit: str) -> bool:
    return ch.is_suit(suit)


def _has_suit(played, suit: str) -> bool:
    return any(_is_suit(c, suit) for c in played)


def _faces(played):
    return [(i, c) for i, c in enumerate(played) if c.is_face]


def _face_count(played) -> int:
    return len(_faces(played))


def _is_straight_sufficient(hand_key: str) -> bool:
    return hand_key in ("Straight", "Straight Flush")


# -- builders ---------------------------------------------------------------
def _chips(amt: int):
    return lambda hk, played, scoring, flags: {"chips": amt} if hk else None


def _mult(amt: int):
    return lambda hk, played, scoring, flags: {"mult": amt} if hk else None


def _on_hand(hand: str, amt: int, kind: str = "mult"):
    def fn(hk, played, scoring, flags):
        if hk != hand:
            return None
        return {kind: amt}
    return fn


def _on_suit(suit: str, amt: int):
    def fn(hk, played, scoring, flags):
        if not played:
            return None
        if not any(_is_suit(c, suit) for c in played):
            return None
        return {"chips": amt}
    return fn


def _per_face(amt: int):
    def fn(hk, played, scoring, flags):
        n = _face_count(played)
        if not n:
            return None
        return {"mult": amt * n}
    return fn


def _discard_power(price: int):
    def fn(hk, played, scoring, flags):
        # scoring-context discard trigger is handled elsewhere in v1
        return None
    return fn


def _on_hands(hands, amt: int, kind: str = "mult"):
    hands = set(hands)
    def fn(hk, played, scoring, flags):
        if hk not in hands:
            return None
        return {kind: amt}
    return fn


def _xmult_for_hand(ctx_hand, amt: float):
    def fn(hk, played, scoring, flags):
        if hk != ctx_hand:
            return None
        return {"x_mult": amt}
    return fn


_CALCULATORS = {
    # -- flat scoring jokers (always active when a hand is scored) ---------
    "j_joker":      lambda hk, p, s, f: {"mult": 4} if hk else None,
    "j_greedy_joker": _on_suit("D", 30),
    "j_lusty_joker":  _on_suit("H", 30),
    "j_wicked_joker": _on_suit("C", 30),
    "j_sly_joker":    _on_suit("S", 50),

    # -- hand-keyed mult ----------------------------------------------------
    "j_jolly":       _on_hand("Full House", 8),
    "j_zany":        _on_hand("Five of a Kind", 12),
    "j_mad":         _on_hands(("Straight", "Straight Flush"), 10),
    "j_clever":      _on_hand("Four of a Kind", 8),
    "j_hibiscus":    _on_hand("Flush House", 12),
    "j_business":    _on_hand("Flush", 12),
    "j_sly":         _on_hand("Three of a Kind", 6),
    "j_trio":        _on_hand("Two Pair", 9),
    "j_fibonacci":   _on_hand("Straight", 8),
    "j_mystic_summit": _on_hands(("Straight Flush", "Flush House"), 15),

    # -- face-cards ---------------------------------------------------------
    "j_face_joker":  _per_face(6),

    # -- chips --------------------------------------------------------------
    "j_listing":     _on_hand("Pair", 45, "chips"),
    "j_drunkard":    _on_hands(("High Card", "Pair", "Three of a Kind"), 42, "chips"),

    # -- steel / held helpers (no direct scoring in v1) ---------------------
    "j_steel_joker": _discard_power(6),
    "j_popcorn":     _on_hand("High Card", 15),
    "j_eight_ball":  lambda hk, p, s, f: None,  # gambling money trigger, out of v1
}


def name_for(key: str) -> str:
    """Localized display name (fallback to key)."""
    from ..data import loader
    c = loader.centers().get(key)
    if c and c.get("name"):
        return c["name"]
    return key or "?"