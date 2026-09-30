"""Scoring pipeline, ported from state_events.lua:evaluate_play (~571-1035).

Per played hand:
  1. Resolve best hand (get_poker_hand_info) -> hand_key/name + scoring cards.
  2. Base mult/chips from HAND_LEVELS; `mod_mult`/`mod_chips` (identity in v1).
  3. Level scaling: shown = base + s_*(level-1).
  4. Blind modify_hand (boss modifications; identity for v1).
  5. Per scoring card: fold enhancement + edition (chips / mult / Xmult).
  6. Held-hand effects (Steel cards still in hand -> Xmult).
  7. Jokers (before / Xmult / after phases folded in aggregate).
  8. chip_total = floor(chips * mult); blind win check.

Returns a structured ScoreResult for the render layer to print as one compact
line (covert = aggregate, not per-card spam).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .. import config
from ..data import loader
from .card import Card, rank_nominal
from .hand import evaluate_poker_hand, JokerFlags

# enhancement key -> (label, kind, value)
ENHANCEMENTS = {
    "m_bonus":  ("Bonus", "chips", lambda cfg: cfg.get("bonus", 30)),
    "m_mult":   ("Mult", "mult", lambda cfg: cfg.get("mult", 4)),
    "m_glass":  ("Glass", "x_mult", lambda cfg: cfg.get("Xmult", 2)),
    "m_lucky":  ("Lucky", "mult", lambda cfg: cfg.get("mult", 20)),
    "m_stone":  ("Stone", "chips", lambda cfg: cfg.get("bonus", 50)),
    "m_steel":  ("Steel", "held_x_mult", lambda cfg: cfg.get("h_x_mult", 1.5)),
    "m_gold":   ("Gold", "held_money", lambda cfg: cfg.get("h_dollars", 3)),
    "m_wild":   ("Wild", "none", lambda cfg: 0),
}
EDITIONS = {
    "e_foil":        ("Foil", "chips", lambda cfg: cfg.get("extra", 50)),
    "e_holo":        ("Holo", "mult", lambda cfg: cfg.get("extra", 10)),
    "e_polychrome":  ("Poly", "x_mult", lambda cfg: cfg.get("extra", 1.5)),
}


@dataclass
class CardDelta:
    card: Card
    chips: int = 0
    mult: int = 0
    x_mult: float = 1.0


@dataclass
class JokerDelta:
    key: str
    name: str
    chips: int = 0
    mult: int = 0
    x_mult: float = 1.0


@dataclass
class ScoreResult:
    hand_key: str
    scoring_cards: list[Card]
    base_chips: int
    base_mult: int
    level: int
    card_deltas: list[CardDelta] = field(default_factory=list)
    joker_deltas: list[JokerDelta] = field(default_factory=list)
    held_x_mult: float = 1.0
    total_chips: int = 0
    total_mult: float = 0.0
    score: int = 0
    blind_chips: int = 0


def _card_chip_base(c: Card) -> int:
    if c.enhancement == "m_stone":
        return 0  # stone contributes only its ability bonus
    return rank_nominal(c.rank)


def mod_chips(v): return v
def mod_mult(v): return v


def score_play(played: list[Card], held: list[Card], level: dict,
               blind, jokers: list[Any] | None = None,
               flags: JokerFlags | None = None) -> ScoreResult:
    """Evaluate one played hand and produce an aggregate ScoreResult.

    `level` is the resolved {mult, chips, s_mult, s_chips, level} for the hand.
    """
    flags = flags or JokerFlags()
    jokers = jokers or []
    results = evaluate_poker_hand(played, flags)
    hand_key = results["top_key"]
    scoring_cards = results["top"] or []

    chips = mod_chips(level["chips"])
    mult = mod_mult(level["mult"])

    # blind boss modifications (identity in v1)
    mult, chips, _modded = blind.modify_hand(played, results, hand_key, mult, chips)
    mult, chips = mod_mult(mult), mod_chips(chips)

    card_deltas: list[CardDelta] = []
    for c in scoring_cards:
        delta = CardDelta(c)
        delta.chips += _card_chip_base(c)
        # enhancement
        enh = ENHANCEMENTS.get(c.enhancement)
        if enh:
            _label, kind, val = enh
            v = val({})
            if kind == "chips":
                delta.chips += v
            elif kind == "mult":
                delta.mult += v
            elif kind == "x_mult":
                delta.x_mult *= v
        # edition
        ed = EDITIONS.get(c.edition)
        if ed:
            _label, kind, val = ed
            v = val({})
            if kind == "chips":
                delta.chips += v
            elif kind == "mult":
                delta.mult += v
            elif kind == "x_mult":
                delta.x_mult *= v
        chips += delta.chips
        mult += delta.mult
        mult *= delta.x_mult
        card_deltas.append(delta)

    # held-hand Steel cards -> Xmult
    held_x_mult = 1.0
    for c in held:
        if c.enhancement == "m_steel" and not c.debuffed:
            held_x_mult *= 1.5
    mult *= held_x_mult

    # jokers (aggregate; see joker.py dispatch)
    joker_deltas = []
    for j in jokers:
        eff = _joker_effect(j, hand_key, played, scoring_cards, flags)
        if eff:
            mult, chips = _apply_effect(mult, chips, eff)
            joker_deltas.append(JokerDelta(
                key=j, name=_joker_name(j),
                chips=eff.get("chips", 0), mult=eff.get("mult", 0),
                x_mult=eff.get("x_mult", 1.0)))

    total_chips = int(chips)
    total_mult = mult
    score = int(chips * mult)

    return ScoreResult(
        hand_key=hand_key,
        scoring_cards=scoring_cards,
        base_chips=level["chips"], base_mult=level["mult"],
        level=level.get("level", 1),
        card_deltas=card_deltas,
        joker_deltas=joker_deltas,
        held_x_mult=held_x_mult,
        total_chips=total_chips, total_mult=total_mult,
        score=score, blind_chips=blind.chips,
    )


def _apply_effect(mult: int | float, chips: int, eff) -> tuple:
    chips += eff.get("chips", 0)
    mult += eff.get("mult", 0)
    mult *= eff.get("x_mult", 1.0)
    return mult, chips


def _joker_effect(j, hand_key, played, scoring_cards, flags):
    """Dispatch a joker effect; `j` is a centers key (string)."""
    from . import joker as joker_mod
    return joker_mod.calculate(j, hand_key, played, scoring_cards, flags)


def _joker_name(j) -> str:
    if isinstance(j, str):
        c = loader.centers().get(j)
        return (c or {}).get("name", j)
    return getattr(j, "name", str(j))