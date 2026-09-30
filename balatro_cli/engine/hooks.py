"""Hook + effect model.

Balatro drives every card/joker/blind behaviour through *one* method,
``Card:calculate_joker(context)`` (card.lua:2291), where ``context`` is a plain
table of flags.  A single giant ``if`` chain keys off those flags::

    if context.joker_main then ... end
    if context.individual and context.cardarea == G.play then ... end
    if context.end_of_round and context.game_over == false then ... end

This module mirrors that model in Python:

* :class:`Context` - the flags passed to an effect handler.
* :class:`Effect`  - the value a handler may return (``Xmult_mod``, ``mult_mod``,
  ``chip_mod``, ``dollars``, ``repetitions``, ...); ``None`` means "no effect",
  exactly like the Lua returning nothing.
* :func:`merge` - fold a list of effects into one aggregate.

Effect handlers live in :mod:`balatro_cli.engine.jokers` (jokers),
:mod:`balatro_cli.engine.consumables`, :mod:`balatro_cli.engine.tags`,
:mod:`balatro_cli.engine.vouchers`, :mod:`balatro_cli.engine.backs` and
:mod:`balatro_cli.engine.blind`.

Naming: the hook names below are the Python spelling of the Lua context flags
(``joker_main`` for the main scoring pass, ``individual`` for per-scored-card
joker effects, ``repetition`` for retrigger queries, ...).  ``Context.simple``
builds the common cases so callers do not have to fill every field.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

# ---------------------------------------------------------------------------
# Hook names (Python spelling of the Lua context flags)
# ---------------------------------------------------------------------------
HOOK_JOKER_MAIN = "joker_main"          # main scoring pass (context.joker_main)
HOOK_BEFORE = "before"                  # before scoring (context.before)
HOOK_AFTER = "after"                    # after scoring (context.after)
HOOK_INDIVIDUAL = "individual"          # per scored card (context.individual)
HOOK_OTHER_JOKER = "other_joker"        # joker-on-joker pass (context.other_joker)
HOOK_REPETITION = "repetition"          # retrigger query (context.repetition)
HOOK_DISCARD = "discard"                # a card is being discarded
HOOK_DISCARD_HAND = "discard_hand"      # a discard action finished
HOOK_END_OF_ROUND = "end_of_round"      # round defeated (context.end_of_round)
HOOK_SETTING_BLIND = "setting_blind"    # blind chosen (context.setting_blind)
HOOK_HAND_DRAWN = "hand_drawn"          # hand drawn (context.hand_drawn)
HOOK_FIRST_HAND_DRAWN = "first_hand_drawn"
HOOK_OPEN_BOOSTER = "open_booster"      # booster pack opened
HOOK_SKIP_BLIND = "skip_blind"          # blind skipped
HOOK_SHOP_START = "shop_start"          # shop entered (context.shop_start)
HOOK_SHOP_FINAL_PASS = "shop_final_pass"
HOOK_REROLL_SHOP = "reroll_shop"
HOOK_BUYING_CARD = "buying_card"
HOOK_SELLING_CARD = "selling_card"
HOOK_SELLING_SELF = "selling_self"
HOOK_USE_CONSUMABLE = "use_consumeable"
HOOK_CARD_ADDED = "card_added"          # playing card added to deck
HOOK_CARD_REMOVED = "card_removed"
HOOK_PLAYING_CARD_ADDED = "playing_card_added"
HOOK_REMOVE_PLAYING_CARDS = "remove_playing_cards"
HOOK_DESTROYING_CARD = "destroying_card"
HOOK_ROUND_START = "round_start"
HOOK_BLIND_DEFEATED = "blind_defeated"
HOOK_DEBUFFED_HAND = "debuffed_hand"
HOOK_POST_DISCARD = "post_discard"
HOOK_PRE_DISCARD = "pre_discard"        # before a discard is removed (Burnt Joker)
HOOK_ENDING_SHOP = "ending_shop"        # leaving the shop (Perkeo)
HOOK_SKIPPING_BOOSTER = "skipping_booster"  # pack skipped (Red Card)
HOOK_EVAL = "eval"                      # end-of-round dollar evaluation
HOOK_OTHER = "other"
HOOK_HAND_LEVEL_UP = "hand_level_up"

ALL_HOOKS = frozenset({
    HOOK_JOKER_MAIN, HOOK_BEFORE, HOOK_AFTER, HOOK_INDIVIDUAL, HOOK_REPETITION,
    HOOK_OTHER_JOKER,
    HOOK_DISCARD, HOOK_DISCARD_HAND, HOOK_END_OF_ROUND, HOOK_SETTING_BLIND,
    HOOK_HAND_DRAWN, HOOK_FIRST_HAND_DRAWN, HOOK_OPEN_BOOSTER, HOOK_SKIP_BLIND,
    HOOK_SHOP_START, HOOK_SHOP_FINAL_PASS, HOOK_REROLL_SHOP, HOOK_BUYING_CARD,
    HOOK_SELLING_CARD, HOOK_SELLING_SELF, HOOK_USE_CONSUMABLE, HOOK_CARD_ADDED,
    HOOK_CARD_REMOVED, HOOK_PLAYING_CARD_ADDED, HOOK_REMOVE_PLAYING_CARDS,
    HOOK_DESTROYING_CARD, HOOK_ROUND_START, HOOK_BLIND_DEFEATED,
    HOOK_DEBUFFED_HAND, HOOK_POST_DISCARD, HOOK_PRE_DISCARD,
    HOOK_ENDING_SHOP, HOOK_SKIPPING_BOOSTER, HOOK_EVAL, HOOK_OTHER,
    HOOK_HAND_LEVEL_UP,
})

# Card area names (G.play / G.hand / G.jokers / G.consumeables)
AREA_PLAY = "play"
AREA_HAND = "hand"
AREA_JOKERS = "jokers"
AREA_CONSUMEABLES = "consumeables"


@dataclass
class Context:
    """One `calculate_joker` context (see module docstring)."""

    event: str = HOOK_OTHER
    run: Any = None                      # GameState
    cardarea: str | None = None
    other_card: Any = None               # Card
    other_joker: Any = None              # joker to the right (Blueprint/Brainstorm)
    full_hand: list = field(default_factory=list)      # the cards played
    scoring_hand: list = field(default_factory=list)   # cards that score
    held: list = field(default_factory=list)           # cards kept in hand
    scoring_name: str | None = None      # resolved poker-hand name
    poker_hands: dict = field(default_factory=dict)    # evaluate_poker_hand() output
    hands: dict = field(default_factory=dict)          # run.hand_levels
    blind: Any = None
    check: bool = False                  # "count only, do not apply" probe
    game_over: bool = False
    blueprint: bool = False              # this evaluation came from a copy
    repetition_only: bool = False
    hook: bool = False                   # The Hook blind is active
    skipped_blind: bool = False
    joker: Any = None                    # the JokerCard being evaluated
    pack: Any = None
    consumable: Any = None
    area: Any = None
    dollars: int = 0
    extra: dict = field(default_factory=dict)

    # -- convenience ---------------------------------------------------------
    def with_(self, **kwargs) -> "Context":
        return replace(self, **kwargs)

    @property
    def played(self) -> list:
        return self.full_hand

    def is_event(self, *events: str) -> bool:
        return self.event in events


@dataclass
class Effect:
    """Aggregate of one effect handler's return value.

    ``None`` from a handler means "no effect"; an :class:`Effect` with
    :meth:`is_empty` true is likewise ignored.  Fields mirror the Lua table keys
    used across ``calculate_joker`` / ``calculate_seal`` / ``use_consumeable``.
    """

    chips: int = 0                 # chip_mod
    mult: float = 0                # mult_mod
    x_mult: float = 1.0            # Xmult_mod
    dollars: int = 0               # dollar / h_dollars
    h_dollars: int = 0
    p_dollars: int = 0
    repetitions: int = 0           # extra scoring repetitions
    level_up: list = field(default_factory=list)   # [(hand_key, amount)]
    destroy: bool = False          # destroy the triggering card
    create: list = field(default_factory=list)     # [CreateSpec-like dicts]
    message: str = ""
    saved: bool = False            # Mr. Bones / Luchador: survive a loss
    debuff: bool = False           # debuff a card
    stay_flipped: bool = False     # blind face-down effects
    disabled_blind: bool = False   # Chicot
    swap: bool = False
    remove_played: bool = False
    retrigger_self: int = 0
    extra: dict = field(default_factory=dict)
    source: Any = None              # the joker that produced this effect

    # -- arithmetic ----------------------------------------------------------
    def is_empty(self) -> bool:
        return not (self.chips or self.mult or self.x_mult != 1.0 or self.dollars
                    or self.h_dollars or self.p_dollars or self.repetitions
                    or self.level_up or self.destroy or self.create
                    or self.saved or self.debuff or self.stay_flipped
                    or self.disabled_blind or self.swap or self.remove_played
                    or self.retrigger_self or self.extra)

    def __bool__(self) -> bool:
        return not self.is_empty()

    def merge(self, other: "Effect | None") -> "Effect":
        """Fold `other` into this effect (additive chips/mult, multiplicative x)."""
        if other is None:
            return self
        self.chips += other.chips
        self.mult += other.mult
        self.x_mult *= other.x_mult
        self.dollars += other.dollars
        self.h_dollars += other.h_dollars
        self.p_dollars += other.p_dollars
        self.repetitions += other.repetitions
        self.level_up.extend(other.level_up)
        self.destroy = self.destroy or other.destroy
        self.create.extend(other.create)
        if other.message:
            self.message = other.message
        self.saved = self.saved or other.saved
        self.debuff = self.debuff or other.debuff
        self.stay_flipped = self.stay_flipped or other.stay_flipped
        self.disabled_blind = self.disabled_blind or other.disabled_blind
        self.swap = self.swap or other.swap
        self.remove_played = self.remove_played or other.remove_played
        self.retrigger_self += other.retrigger_self
        if other.extra:
            self.extra.update(other.extra)
        return self


def merge(effects) -> Effect:
    """Fold an iterable of effects/None into one :class:`Effect`."""
    out = Effect()
    for e in effects:
        out.merge(e)
    return out


# -- small shared helpers used by effect tables ------------------------------

def cards_of_suit(cards, suit: str) -> list:
    return [c for c in cards if c.is_suit(suit)]


def has_suit(cards, suit: str) -> bool:
    return any(c.is_suit(suit) for c in cards)


def faces(cards) -> list:
    return [c for c in cards if c.is_face]


def contains_rank(cards, rank: str) -> bool:
    return any(c.rank == rank for c in cards)


def contains_id(cards, card_id) -> bool:
    return any(c.id == card_id for c in cards)


def scored_names(ctx) -> set[str]:
    """All poker-hand names present in the played hand's evaluation."""
    names = set()
    for name, group in (ctx.poker_hands or {}).items():
        if name in ("top", "top_key"):
            continue
        if group:
            names.add(name)
    return names


def joker_key(j) -> str:
    if isinstance(j, str):
        return j
    return getattr(j, "key", "") or ""


def joker_name(j) -> str:
    if isinstance(j, str):
        from ..data import loader
        c = loader.centers().get(j) or {}
        return c.get("name", j)
    return (getattr(j, "ability", {}) or {}).get("name") or getattr(j, "key", "?")


def joker_ability(j) -> dict:
    """The mutable ability table of a joker (centre config + runtime counters)."""
    if isinstance(j, str):
        return {}
    return getattr(j, "ability", {}) or {}


def get_extra(ability: dict, default=None):
    return ability.get("extra", default)
