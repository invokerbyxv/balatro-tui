"""Blind model + boss mechanics, ported from blind.lua and misc_functions.lua.

Ported surface (Lua line refs in blind.lua unless noted):

    get_blind_amount        misc_functions.lua:919 (ante table + endless formula)
    Blind.set_chips         blind.lua:107  chips = amount * mult * ante_scaling
    Blind.set_blind         blind.lua:78   (incl. The Eye/Mouth/Fish/Water/
                                           Needle/Manacle/Amber Acorn prep and
                                           the initial debuff pass)
    Blind.debuff_card       blind.lua:624
    Blind.debuff_hand       blind.lua:519
    Blind.modify_hand       blind.lua:510  (The Flint)
    Blind.press_play        blind.lua:464  (Hook / Tooth / Crimson Heart / Fish)
    Blind.stay_flipped      blind.lua:605  (Wheel / House / Mark / Fish)
    Blind.drawn_to_hand     blind.lua:572  (Cerulean Bell / Crimson Heart)
    Blind.defeat            blind.lua:276
    Blind.disable           blind.lua:356  (Chicot / Verdant Leaf joker sold)
    Blind.get_type          blind.lua:346

Key-driven effects
------------------
Every implemented mechanic has a stable *tag* (``TAG_EYE``, ``TAG_HOOK``, ...)
in :data:`BLIND_EFFECT_TAGS`; a :class:`Blind` exposes the tag set as
``blind.effects`` and the predicates :meth:`Blind.has_effect` /
:meth:`Blind.is_key`, so engine code asks ``blind.has_effect(TAG_EYE)`` instead
of comparing localized names.  Tags are resolved from the blind *key* first and
fall back to the blind *name* (``key_for``), because ``game_state._boss_offer``
currently hands every boss the placeholder key ``"bl_boss"``.  Data-driven
debuffs (``debuff.suit`` / ``is_face`` / ``hand`` / ``h_size_*`` / ``value`` /
``nominal``) additionally contribute tags, so new blind data keeps working
without touching the tag table.

:data:`BOSS_EFFECTS` holds one short plain-text line list per blind key and
:func:`describe` renders ``"<name>: <effects>"`` for the transcript.

Run state
---------
blind.py must not import ``game_state`` (circular), so methods that need run
state take an optional ``run=None`` and read it defensively with ``getattr``
(the PORTING.md duck type).  Methods whose Lua body only reads
``G.GAME.current_round`` / ``G.GAME.probabilities.normal`` also accept those
values as plain keyword arguments, so they stay pure and testable:

    blind.stay_flipped("hand", card, rng=rng, hands_played=0, discards_used=0)
    blind.debuff_hand(cards, poker_hands, "Flush", level=2, most_played="Pair")
    blind.modify_hand(cards, poker_hands, "Flush", 8, 35)
    blind.press_play(run=run)          # or cards=[...] + rng=...
    blind.drawn_to_hand(run=run)

RNG comes from ``run.rng`` (engine.rng.RNG) and mirrors the Lua pseudoseeds
('wheel', 'hook', 'cerulean_bell', 'crimson_heart', 'amber_acorn').

Fidelity notes
--------------
* Lua tables are truthy, so ``if self.debuff then`` on an *empty* table still
  runs the block; the port therefore tests ``self.debuff is not None``.
* ``Card:flip()`` only changes ``facing`` (visual) in the Lua - nothing skips a
  face-down joker when scoring - so Amber Acorn records ``ability['facing']``
  and shuffles the joker list, and ``defeat``/``disable`` flip them back.
* The Lua reads ``card.area == G.jokers``; we derive that from
  ``card.is_joker`` / :class:`~balatro_cli.engine.card.JokerCard`.
"""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Any

from .card import JokerCard, rank_nominal
from .hand import HAND_NAMES

# ---------------------------------------------------------------------------
# Effect tags (stable identifiers for "is this boss The Eye?")
# ---------------------------------------------------------------------------

TAG_DEBUFF_SUIT = "debuff_suit"          # debuff.suit
TAG_DEBUFF_FACE = "debuff_face"          # debuff.is_face == 'face'
TAG_DEBUFF_HAND = "debuff_hand"          # debuff.hand
TAG_DEBUFF_H_SIZE_GE = "debuff_h_size_ge"
TAG_DEBUFF_H_SIZE_LE = "debuff_h_size_le"
TAG_DEBUFF_VALUE = "debuff_value"
TAG_DEBUFF_NOMINAL = "debuff_nominal"
TAG_PILLAR = "pillar"                    # The Pillar
TAG_CRIMSON_HEART = "crimson_heart"
TAG_VERDANT_LEAF = "verdant_leaf"
TAG_EYE = "eye"
TAG_MOUTH = "mouth"
TAG_ARM = "arm"
TAG_OX = "ox"
TAG_HOOK = "hook"
TAG_TOOTH = "tooth"
TAG_FISH = "fish"
TAG_WHEEL = "wheel"
TAG_HOUSE = "house"
TAG_MARK = "mark"
TAG_FLINT = "flint"
TAG_MANACLE = "manacle"
TAG_WATER = "water"
TAG_NEEDLE = "needle"
TAG_CERULEAN_BELL = "cerulean_bell"
TAG_AMBER_ACORN = "amber_acorn"
TAG_WALL = "wall"
TAG_VIOLET_VESSEL = "violet_vessel"
TAG_SERPENT = "serpent"

#: blind key -> semantic effect tags implemented by this module
BLIND_EFFECT_TAGS: dict[str, tuple[str, ...]] = {
    "bl_small": (),
    "bl_big": (),
    "bl_ox": (TAG_OX,),
    "bl_hook": (TAG_HOOK,),
    "bl_mouth": (TAG_MOUTH,),
    "bl_fish": (TAG_FISH,),
    "bl_club": (TAG_DEBUFF_SUIT,),
    "bl_manacle": (TAG_MANACLE,),
    "bl_tooth": (TAG_TOOTH,),
    "bl_wall": (TAG_WALL,),
    "bl_house": (TAG_HOUSE,),
    "bl_mark": (TAG_MARK,),
    "bl_final_bell": (TAG_CERULEAN_BELL,),
    "bl_wheel": (TAG_WHEEL,),
    "bl_arm": (TAG_ARM,),
    "bl_psychic": (TAG_DEBUFF_H_SIZE_GE,),
    "bl_goad": (TAG_DEBUFF_SUIT,),
    "bl_water": (TAG_WATER,),
    "bl_eye": (TAG_EYE,),
    "bl_plant": (TAG_DEBUFF_FACE,),
    "bl_needle": (TAG_NEEDLE,),
    "bl_head": (TAG_DEBUFF_SUIT,),
    "bl_final_leaf": (TAG_VERDANT_LEAF,),
    "bl_final_vessel": (TAG_VIOLET_VESSEL,),
    "bl_window": (TAG_DEBUFF_SUIT,),
    "bl_serpent": (TAG_SERPENT,),
    "bl_pillar": (TAG_PILLAR,),
    "bl_flint": (TAG_FLINT,),
    "bl_final_acorn": (TAG_AMBER_ACORN,),
    "bl_final_heart": (TAG_CRIMSON_HEART,),
}

#: blind key -> short plain-text effect summaries (the transcript line)
BOSS_EFFECTS: dict[str, list[str]] = {
    "bl_small": ["standard blind, no debuff"],
    "bl_big": ["standard blind, no debuff"],
    "bl_ox": ["playing your most-played poker hand sets money to $0"],
    "bl_hook": ["discards 2 random cards after each hand played"],
    "bl_mouth": ["play only 1 hand type this round"],
    "bl_fish": ["cards drawn after each hand played are face down"],
    "bl_club": ["all Club cards are debuffed"],
    "bl_manacle": ["-1 hand size"],
    "bl_tooth": ["lose $1 per card played"],
    "bl_wall": ["extra large blind (4x chips)"],
    "bl_house": ["first hand is drawn face down"],
    "bl_mark": ["all face cards are drawn face down"],
    "bl_final_bell": ["forces 1 card to always be selected"],
    "bl_wheel": ["1 in 7 cards is drawn face down"],
    "bl_arm": ["decrease level of played poker hand"],
    "bl_psychic": ["must play 5 cards"],
    "bl_goad": ["all Spade cards are debuffed"],
    "bl_water": ["start with 0 discards"],
    "bl_eye": ["no repeat hand types this round"],
    "bl_plant": ["all face cards are debuffed"],
    "bl_needle": ["play only 1 hand"],
    "bl_head": ["all Heart cards are debuffed"],
    "bl_final_leaf": ["all cards debuffed until 1 Joker is sold"],
    "bl_final_vessel": ["very large blind (6x chips)"],
    "bl_window": ["all Diamond cards are debuffed"],
    "bl_serpent": ["after each Play or Discard, always draw 3 cards"],
    "bl_pillar": ["cards played previously this Ante are debuffed"],
    "bl_flint": ["base Chips and Mult are halved"],
    "bl_final_acorn": ["flips and shuffles all Joker cards"],
    "bl_final_heart": ["one random Joker is disabled every hand"],
}


# ---------------------------------------------------------------------------
# blind.lua:set_blind / ante scaling
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# blind data access + key/name lookup
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _all_blinds() -> dict:
    """`assets/blinds.json` (empty when the assets are unavailable)."""
    try:
        from ..data import loader
        return dict(loader.blinds() or {})
    except Exception:                       # pragma: no cover - assets missing
        return {}


@lru_cache(maxsize=1)
def _name_index() -> dict[str, str]:
    out: dict[str, str] = {}
    for key, data in _all_blinds().items():
        if isinstance(data, dict) and data.get("name"):
            out.setdefault(data["name"], key)
    return out


def blind_data(key: str | None) -> dict:
    """Asset dict for a blind key (``{}`` when unknown)."""
    return _all_blinds().get(key or "") or {}


def key_for(key_or_name: str | None) -> str:
    """Resolve a blind key *or* display name ("The Eye") to its asset key.

    Needed because ``game_state._boss_offer`` builds every boss with the
    placeholder key ``"bl_boss"`` - the display name is then the only
    trustworthy identity on the object.
    """
    if not key_or_name:
        return ""
    if key_or_name in _all_blinds():
        return key_or_name
    return _name_index().get(key_or_name, key_or_name)


def blind_name(key_or_name: str | None) -> str:
    data = blind_data(key_for(key_or_name)) or blind_data(key_or_name)
    return data.get("name") or str(key_or_name or "")


def boss_keys() -> list[str]:
    """Every key in blinds.json carrying a `boss` table (28 of them)."""
    return [k for k, v in _all_blinds().items()
            if isinstance(v, dict) and v.get("boss")]


def eligible_boss_keys(ante: int, used: list[str] | tuple[str, ...] = ()) -> list[str]:
    """Boss keys legal for `ante` - the pool ``_boss_offer`` wants.

    ``game_state._boss_offer`` reads ``b["key"]``, which blinds.json does not
    carry, so it cannot exclude used bosses; this helper derives the key from
    the asset dict itself.  Showdown bosses (min 10) join the pool from ante 8.
    """
    used_keys = set(used or ())
    pool, showdown = [], []
    for key, data in _all_blinds().items():
        boss = data.get("boss") if isinstance(data, dict) else None
        if not boss or key in used_keys:
            continue
        (showdown if boss.get("showdown") else pool).append(key)
    out = [k for k in pool
           if int(blind_data(k)["boss"].get("min") or 1) <= ante
           <= int(blind_data(k)["boss"].get("max") or 10)]
    if ante >= 8:
        out.extend(showdown)
    return out or pool or boss_keys()


def _debuff_tags(debuff: dict | None) -> set[str]:
    d = debuff or {}
    tags: set[str] = set()
    if d.get("suit"):
        tags.add(TAG_DEBUFF_SUIT)
    if d.get("is_face") == "face":
        tags.add(TAG_DEBUFF_FACE)
    if d.get("hand"):
        tags.add(TAG_DEBUFF_HAND)
    if d.get("h_size_ge"):
        tags.add(TAG_DEBUFF_H_SIZE_GE)
    if d.get("h_size_le"):
        tags.add(TAG_DEBUFF_H_SIZE_LE)
    if "value" in d:
        tags.add(TAG_DEBUFF_VALUE)
    if "nominal" in d:
        tags.add(TAG_DEBUFF_NOMINAL)
    return tags


def effects_for(key_or_name: str | None, debuff: dict | None = None) -> frozenset[str]:
    """Effect tags for a blind key/name plus any data-driven debuff it carries."""
    key = key_for(key_or_name)
    tags = set(BLIND_EFFECT_TAGS.get(key, ()))
    tags |= _debuff_tags(blind_data(key).get("debuff"))
    tags |= _debuff_tags(debuff)
    return frozenset(tags)


def describe(key_or_name: str | None) -> str:
    """One transcript line for a blind: `"The Eye: no repeat hand types ..."`."""
    key = key_for(key_or_name)
    name = blind_name(key) or str(key_or_name or "?")
    effects = BOSS_EFFECTS.get(key) or []
    return f"{name}: {'; '.join(effects)}" if effects else name


# ---------------------------------------------------------------------------
# card predicates (Card:is_suit / Card:is_face with the boss bypasses)
# ---------------------------------------------------------------------------

def SUIT_LETTER(name: str) -> str:
    return {"Spades": "S", "Hearts": "H", "Diamonds": "D", "Clubs": "C"}.get(name, "S")


def _in_jokers(card) -> bool:
    """`card.area == G.jokers` for a model without card areas."""
    area = getattr(card, "area", None)
    if area is not None:
        return area == "jokers" or area == "joker"
    return bool(getattr(card, "is_joker", False)) or isinstance(card, JokerCard)


def _is_face(card, flags=None) -> bool:
    """`Card:is_face(true)` - face-ness *including* debuffed cards."""
    if getattr(flags, "pareidolia", False):
        return True
    try:
        return card.id in (11, 12, 13)
    except Exception:                       # pragma: no cover - exotic duck type
        return getattr(card, "rank", "") in ("J", "Q", "K")


def _is_suit(card, suit_letter: str, flags=None) -> bool:
    """`Card:is_suit(suit, true)` - debuff-bypassing suit test (flush_calc off)."""
    if getattr(card, "enhancement", None) == "m_stone":
        return False
    if getattr(card, "enhancement", None) == "m_wild":
        return True
    if getattr(flags, "smeared", False):
        red = ("H", "D")
        if (getattr(card, "suit", None) in red) == (suit_letter in red):
            return True
    return getattr(card, "suit", None) == suit_letter


def _rank_value(card) -> str:
    """Lua `card.base.value` (the rank string; ten is spelled '10')."""
    rank = getattr(card, "rank", "")
    return "10" if rank == "T" else str(rank)


def _ability(card) -> dict:
    ability = getattr(card, "ability", None)
    return ability if isinstance(ability, dict) else {}


# ---------------------------------------------------------------------------
# run helpers (duck-typed, defensive)
# ---------------------------------------------------------------------------

def _run_int(run, name: str, default: int = 0) -> int:
    if run is None:
        return default
    value = getattr(run, name, None)
    if value is None:
        cr = getattr(run, "current_round", None)
        if isinstance(cr, dict):
            value = cr.get(name)
    try:
        return default if value is None else int(value)
    except (TypeError, ValueError):
        return default


def _run_add(run, name: str, delta: int) -> None:
    if run is None or not hasattr(run, name):
        return
    try:
        setattr(run, name, int(getattr(run, name) or 0) + int(delta))
    except (TypeError, ValueError):         # pragma: no cover - exotic duck type
        pass


def _playing_cards(run) -> list:
    """`G.playing_cards` (deck + hand + played)."""
    fn = getattr(run, "playing_cards", None)
    if callable(fn):
        try:
            return list(fn() or [])
        except TypeError:                   # pragma: no cover - exotic signature
            pass
    out: list = []
    for name in ("deck", "hand", "played"):
        value = getattr(run, name, None)
        if isinstance(value, list):
            out.extend(value)
    return out


def _jokers(run) -> list:
    value = getattr(run, "jokers", None)
    return list(value) if isinstance(value, list) else []


def _hand_cards(run) -> list:
    value = getattr(run, "hand", None)
    return value if isinstance(value, list) else []


def _draw_to_hand(run, count: int = 1) -> None:
    """`G.FUNCS.draw_from_deck_to_hand(n)` (game_state helper when available)."""
    if run is None or count <= 0:
        return
    fn = getattr(run, "_draw_to_handsize", None)
    if callable(fn):
        fn()
        return
    hand, deck = getattr(run, "hand", None), getattr(run, "deck", None)
    if isinstance(hand, list) and isinstance(deck, list):
        for _ in range(count):
            if deck:
                hand.append(deck.pop())


class Blind:
    def __init__(self, key: str, data: dict, ante: int, scaling: int = 1,
                 ante_scaling: int = 1):
        data = data or {}
        self.key = key
        self.name = data.get("name", key)
        self.mult = data.get("mult", 1)
        self.dollars = data.get("dollars", 3)
        self.debuff: dict = dict(data.get("debuff") or {})
        self.is_boss = bool(data.get("boss"))
        self.boss = self.is_boss            # Lua's `self.boss` (jokers.py reads it)
        self.ante = ante
        # `scaling` picks the blind-amount table (stake), `ante_scaling` is the
        # chip multiplier (Plasma Deck) - blind.lua:107 keeps them separate
        self.scaling = scaling
        self.ante_scaling = ante_scaling
        self.chips = 0
        # runtime state (blind.lua Blind:init / set_blind defaults)
        self.disabled = False
        self.discards_sub: int | None = None
        self.hands_sub: int | None = None
        self.triggered: bool | None = None
        self.prepped: bool | None = True
        self.hands: dict | None = None      # The Eye bookkeeping
        self.only_hand: str | None = None   # The Mouth bookkeeping
        self.blind_set = False
        self.canonical_key = key_for(key)
        self.effects: frozenset[str] = frozenset()
        self.set_blind(data, ante=ante, scaling=scaling, silent=True)

    # -- construction helpers ------------------------------------------------
    @classmethod
    def from_key(cls, key: str, ante: int = 1, scaling: int = 1, run=None,
                 ante_scaling: int = 1) -> "Blind":
        """Build a blind straight from `assets/blinds.json` (data wins nothing)."""
        blind = cls(key, dict(blind_data(key)), ante, scaling, ante_scaling)
        if run is not None:
            blind.apply_start_effects(run)
        return blind

    # -- identity -------------------------------------------------------------
    @property
    def kind(self) -> str:
        return "boss" if self.is_boss else ("big" if self.mult >= 1.5 else "small")

    def get_type(self) -> str | None:
        """blind.lua:346 - 'Small' | 'Big' | 'Boss' (None for an unnamed blind)."""
        name = self.name or ""
        if self.canonical_key == "bl_small" or name == "Small Blind":
            return "Small"
        if self.canonical_key == "bl_big" or name == "Big Blind":
            return "Big"
        if self.is_boss or name not in ("", self.key):
            return "Boss"
        return None

    @property
    def description(self) -> str:
        return describe(self.key)

    def is_key(self, key_or_name: str) -> bool:
        key = key_for(key_or_name)
        return self.canonical_key == key or self.key == key

    def has_effect(self, effect: str) -> bool:
        """True when this blind carries `effect` (see BLIND_EFFECT_TAGS)."""
        return effect in self.effects

    def debuffs_suit(self, suit: str) -> bool:
        return self.debuff.get("suit") == suit

    def debuffs_faces(self) -> bool:
        return self.debuff.get("is_face") == "face"

    def is_defeated(self, chips: int) -> bool:
        return chips >= self.chips

    # -- chips ----------------------------------------------------------------
    def set_chips(self, ante: int, scaling: int = 1, ante_scaling: int | None = None) -> None:
        mult = self.ante_scaling if ante_scaling is None else ante_scaling
        self.chips = int(get_blind_amount(ante, scaling) * self.mult * mult)

    # -- configuration --------------------------------------------------------
    def _backfill_debuff(self) -> None:
        """Adopt the asset debuff when the caller passed an empty one.

        `game_state.select_blind` resolves `debuff` through the *offer key*
        (always "bl_boss" today), so suit/face debuffs would otherwise be lost.
        """
        if self.debuff:
            return
        data_debuff = blind_data(self.canonical_key).get("debuff") or {}
        if data_debuff:
            self.debuff = dict(data_debuff)

    def set_blind(self, data: dict | None = None, reset: bool = False,
                  silent: bool = False, ante: int | None = None,
                  scaling: int | None = None, run=None) -> None:
        """blind.lua:78 `Blind:set_blind(blind, reset, silent)`.

        `silent` is accepted for signature parity (no audio/UI here).  Passing
        `run` also applies the run-facing half of the Lua body; without it the
        constructor stays side-effect free and the caller should invoke
        :meth:`apply_start_effects` once the round counters exist.
        """
        if not reset:
            data = data or {}
            if data.get("name"):
                self.name = data["name"]
            if data.get("mult") is not None:
                self.mult = data["mult"]
            if data.get("dollars") is not None:
                self.dollars = data["dollars"]
            if data.get("debuff"):
                self.debuff = dict(data["debuff"])
            if data.get("boss") is not None:
                self.is_boss = bool(data["boss"])
            self.boss = self.is_boss
            if ante is not None:
                self.ante = ante
            if scaling is not None:
                self.scaling = scaling

            self.disabled = False
            self.discards_sub = None
            self.hands_sub = None
            self.blind_set = False
            self.triggered = None
            self.prepped = True
            self.hands = None
            self.only_hand = None

            canonical = key_for(self.key)
            if canonical not in _all_blinds() and self.name:
                canonical = key_for(self.name)
            self.canonical_key = canonical
            self._backfill_debuff()
            self.effects = effects_for(self.canonical_key, self.debuff)
            self.set_chips(self.ante, self.scaling)

            # blind-local prep (blind.lua:157-189)
            if self.has_effect(TAG_EYE):
                self.hands = {name: False for name in HAND_NAMES}
            if self.has_effect(TAG_MOUTH):
                self.only_hand = False
            if self.has_effect(TAG_FISH):
                self.prepped = None

        if run is not None:
            self.apply_start_effects(run)

    def apply_start_effects(self, run) -> None:
        """Run-facing half of `set_blind` (blind.lua:179-215) - call once per round.

        Applies The Water (discards -> 0), The Needle (hands = 1), The Manacle
        (hand size -1), Amber Acorn (flip + shuffle jokers) and the initial
        :meth:`debuff_card` pass over every playing card and joker.  It must run
        *after* the round counters are initialised, because Water/Needle snapshot
        the values they later restore in :meth:`disable`.
        """
        self._apply_start_effects(run)

    def _apply_start_effects(self, run) -> None:
        if run is None:
            return
        if self.has_effect(TAG_WATER):
            # blind.lua:180 `self.discards_sub = G.GAME.current_round.discards_left`
            current = _run_int(run, "discards_left", 0)
            self.discards_sub = current
            if hasattr(run, "discards_left"):
                run.discards_left = max(0, int(getattr(run, "discards_left") or 0) - current)
        if self.has_effect(TAG_NEEDLE):
            # blind.lua:184 `G.GAME.round_resets.hands - 1`
            params = getattr(run, "params", None) or {}
            start = params.get("hands") if isinstance(params, dict) else None
            if start is None:
                start = _run_int(run, "hands_left", 0)
            self.hands_sub = max(0, int(start) - 1)
            _run_add(run, "hands_left", -self.hands_sub)
        if self.has_effect(TAG_MANACLE):
            if hasattr(run, "hand_size"):
                run.hand_size = int(getattr(run, "hand_size") or 0) - 1
        if self.has_effect(TAG_AMBER_ACORN):
            self._flip_and_shuffle_jokers(run)
        # "add new debuffs" (blind.lua:207-213)
        for card in _playing_cards(run):
            self.debuff_card(card, run=run)
        for joker in _jokers(run):
            self.debuff_card(joker, True, run=run)

    # -- RNG / joker helpers --------------------------------------------------
    @staticmethod
    def _rng(run, rng=None):
        return rng if rng is not None else getattr(run, "rng", None)

    @staticmethod
    def _unflip_jokers(run) -> None:
        for joker in _jokers(run):
            ability = _ability(joker)
            if ability.get("facing") == "back":
                ability["facing"] = "front"

    def _flip_and_shuffle_jokers(self, run) -> None:
        """Amber Acorn: `Card:flip()` every joker, then shuffle the area."""
        jokers = _jokers(run)
        if not jokers:
            return
        for joker in jokers:
            ability = _ability(joker)
            if ability:
                ability["facing"] = "back"
        rng = self._rng(run)
        if rng is not None and len(jokers) > 1:
            shuffled = rng.shuffle("amber_acorn", jokers)
            live = getattr(run, "jokers", None)
            if isinstance(live, list):
                live[:] = shuffled
        self.triggered = True

    # -- debuffs --------------------------------------------------------------
    def debuff_card(self, card, from_blind: bool = False, run=None, flags=None) -> bool:
        """blind.lua:624 - (re)compute `card`'s debuff for this blind.

        Returns the card's resulting `debuffed` state.  `from_blind` is the Lua
        parameter (unused there, kept for parity); `run`/`flags` only supply the
        Pareidolia / Smeared Joker flags read by `is_face(true)` /`is_suit(_, true)`.
        """
        flags = flags if flags is not None else getattr(run, "joker_flags", None)
        joker_area = _in_jokers(card)
        if self.debuff is not None and not self.disabled and not joker_area:
            suit = self.debuff.get("suit")
            if suit and _is_suit(card, SUIT_LETTER(suit), flags):
                card.set_debuff(True)
                return True
            if self.debuff.get("is_face") == "face" and _is_face(card, flags):
                card.set_debuff(True)
                return True
            if self.has_effect(TAG_PILLAR) and _ability(card).get("played_this_ante"):
                card.set_debuff(True)
                return True
            if "value" in self.debuff and self.debuff["value"] == _rank_value(card):
                card.set_debuff(True)
                return True
            if "nominal" in self.debuff and self.debuff["nominal"] == rank_nominal(card.rank):
                card.set_debuff(True)
                return True
        if self.has_effect(TAG_CRIMSON_HEART) and not self.disabled and joker_area:
            return bool(getattr(card, "debuffed", False))
        if self.has_effect(TAG_VERDANT_LEAF) and not self.disabled and not joker_area:
            card.set_debuff(True)
            return True
        card.set_debuff(False)
        return False

    # -- hand modification / debuff -------------------------------------------
    def modify_hand(self, cards, poker_hands, handname, mult, chips, run=None):
        """blind.lua:510 - The Flint halves base mult and chips (round half up).

        Returns the 3-tuple `(mult, chips, modified)`.
        """
        if self.disabled:
            return mult, chips, False
        if self.has_effect(TAG_FLINT):
            self.triggered = True
            return (max(math.floor(mult * 0.5 + 0.5), 1),
                    max(math.floor(chips * 0.5 + 0.5), 0), True)
        return mult, chips, False

    def debuff_hand(self, cards, poker_hands, handname, check: bool = False,
                    run=None, level: int | None = None,
                    most_played: str | None = None) -> bool:
        """blind.lua:519 - True when the boss refuses the whole played hand.

        `check=True` is the UI probe (`CardArea:parse_highlighted`): nothing is
        recorded and no level is lost.  The Eye/Mouth state lives on the blind;
        The Arm reads the hand level and The Ox the run's most-played hand, both
        overridable with `level=` / `most_played=` for a pure call.
        """
        if self.disabled:
            return False
        # Lua tables are truthy even when empty - test `is not None`, not truth.
        if self.debuff is not None:
            self.triggered = False
            debuff = self.debuff
            debuff_hand_key = debuff.get("hand")
            if debuff_hand_key and (poker_hands or {}).get(debuff_hand_key):
                self.triggered = True
                return True
            size_ge = debuff.get("h_size_ge")
            if size_ge and len(cards) < size_ge:
                self.triggered = True
                return True
            size_le = debuff.get("h_size_le")
            if size_le and len(cards) > size_le:
                self.triggered = True
                return True
            if self.has_effect(TAG_EYE):
                hands = self.hands if isinstance(self.hands, dict) else {}
                if handname and hands.get(handname):
                    self.triggered = True
                    return True
                if not check and handname:
                    hands[handname] = True
                    self.hands = hands
            if self.has_effect(TAG_MOUTH):
                if self.only_hand and self.only_hand != handname:
                    self.triggered = True
                    return True
                if not check:
                    self.only_hand = handname
        if self.has_effect(TAG_ARM):
            self.triggered = False
            current = level if level is not None else self._hand_level(run, handname)
            if current > 1:
                self.triggered = True
                if not check:
                    self._level_down(run, handname)
        if self.has_effect(TAG_OX):
            self.triggered = False
            most = most_played if most_played is not None else _most_played(run)
            if most and handname == most:
                self.triggered = True
                if not check and run is not None and hasattr(run, "dollars"):
                    run.dollars = 0
        return False

    @staticmethod
    def _hand_level(run, handname) -> int:
        levels = getattr(run, "hand_levels", None)
        entry = (levels or {}).get(handname) if isinstance(levels, dict) else None
        if isinstance(entry, dict):
            return int(entry.get("level", 1) or 1)
        return 1

    @staticmethod
    def _level_down(run, handname) -> None:
        """`level_up_hand(..., -1)` - prefer the run method, else the level dict."""
        fn = getattr(run, "level_up_hand", None) if run is not None else None
        if callable(fn):
            fn(handname, -1)
            return
        levels = getattr(run, "hand_levels", None)
        entry = (levels or {}).get(handname) if isinstance(levels, dict) else None
        if isinstance(entry, dict) and int(entry.get("level", 1) or 1) > 1:
            entry["level"] = int(entry["level"]) - 1

    # -- play / draw hooks ----------------------------------------------------
    def press_play(self, run=None, cards=None, rng=None) -> dict:
        """blind.lua:464 - fired after a hand is played.

        Returns `{"hook_discarded": [...], "dollars_lost": n, "triggered": bool}`.
        The Hook moves 2 random cards from `run.hand` to the discard pile (it
        does *not* spend a discard, matching `discard_cards_from_highlighted`),
        The Tooth charges $1 per card played (`cards=`, else `run.last_played`).
        """
        out = {"hook_discarded": [], "dollars_lost": 0, "triggered": False}
        if self.disabled:
            return out
        if self.has_effect(TAG_HOOK):
            self.triggered = True
            out["triggered"] = True
            hand = _hand_cards(run)
            if hand:
                picker = self._rng(run, rng)
                pool = list(hand)
                picked = []
                for _ in range(2):
                    if not pool:
                        break
                    if picker is not None:
                        card = pool.pop(picker.pick_index("hook", pool))
                    else:
                        card = pool.pop(0)
                    picked.append(card)
                for card in picked:
                    if card in hand:
                        hand.remove(card)
                played = getattr(run, "played", None)
                if isinstance(played, list):
                    played.extend(picked)
                out["hook_discarded"] = picked
            return out
        if self.has_effect(TAG_CRIMSON_HEART) and _jokers(run):
            self.triggered = True
            self.prepped = True
            out["triggered"] = True
        if self.has_effect(TAG_FISH):
            self.prepped = True
        if self.has_effect(TAG_TOOTH):
            played = cards if cards is not None else getattr(run, "last_played", None)
            count = len(played or [])
            if count:
                _run_add(run, "dollars", -count)
                out["dollars_lost"] = count
            self.triggered = True
            out["triggered"] = True
        return out

    def stay_flipped(self, area, card, run=None, rng=None,
                     hands_played: int | None = None,
                     discards_used: int | None = None) -> bool:
        """blind.lua:605 - True when a card drawn into `area` stays face down.

        `area` is `hooks.AREA_HAND` ("hand") or the run's hand list.  The Wheel
        rolls `pseudorandom('wheel') < normal/7`; The House applies until the
        first hand/discard; The Mark flips face cards; The Fish applies while
        `prepped`.  On True the caller's `emplace` equivalent is mirrored here by
        setting `card.ability['wheel_flipped']` (cardarea.lua:41).
        """
        if self.disabled:
            return False
        if not self._is_hand_area(area, run):
            return False
        flipped = False
        if self.has_effect(TAG_WHEEL):
            picker = self._rng(run, rng)
            if picker is not None and picker.chance("wheel", 7):
                flipped = True
        if not flipped and self.has_effect(TAG_HOUSE):
            played = hands_played if hands_played is not None else _run_int(run, "hands_played", 0)
            used = discards_used if discards_used is not None else _run_int(run, "discards_used", 0)
            if played == 0 and used == 0:
                flipped = True
        if not flipped and self.has_effect(TAG_MARK):
            flags = getattr(run, "joker_flags", None)
            if _is_face(card, flags):
                flipped = True
        if not flipped and self.has_effect(TAG_FISH) and self.prepped:
            flipped = True
        if flipped:
            ability = _ability(card)
            if ability is not None:
                ability["wheel_flipped"] = True
        return flipped

    @staticmethod
    def _is_hand_area(area, run) -> bool:
        if area is None:
            return False
        if isinstance(area, str):
            return area in ("hand", "h")
        return area is getattr(run, "hand", None)

    def drawn_to_hand(self, run=None, rng=None) -> dict:
        """blind.lua:572 - after cards are drawn: Cerulean Bell / Crimson Heart.

        Returns `{"forced": card|None, "debuffed_joker": card|None}`.  Clears
        `prepped` at the end exactly like the Lua.
        """
        out: dict[str, Any] = {"forced": None, "debuffed_joker": None}
        if not self.disabled:
            if self.has_effect(TAG_CERULEAN_BELL):
                hand = _hand_cards(run)
                if hand and not any(_ability(c).get("forced_selection") for c in hand):
                    picker = self._rng(run, rng)
                    card = picker.pick("cerulean_bell", hand) if picker is not None else hand[0]
                    ability = _ability(card)
                    ability["forced_selection"] = True
                    highlighted = getattr(run, "highlighted", None)
                    if isinstance(highlighted, list) and card not in highlighted:
                        highlighted.append(card)
                    out["forced"] = card
            if self.has_effect(TAG_CRIMSON_HEART) and self.prepped:
                jokers = _jokers(run)
                if jokers:
                    candidates = []
                    for joker in jokers:
                        if not getattr(joker, "debuffed", False) or len(jokers) < 2:
                            candidates.append(joker)
                        joker.set_debuff(False)
                    picker = self._rng(run, rng)
                    if candidates:
                        card = (picker.pick("crimson_heart", candidates)
                                if picker is not None else candidates[0])
                        card.set_debuff(True)
                        out["debuffed_joker"] = card
                        self.triggered = True
        self.prepped = None
        return out

    # -- blind end ------------------------------------------------------------
    def defeat(self, silent: bool = True, run=None) -> None:
        """blind.lua:276 - the blind was beaten.

        Restores The Manacle's hand size, flips face-down jokers back, then
        `set_blind(nil, nil, true)`s: clears the config and every debuff.  The
        caller owns the reference afterwards (game_state drops it).
        """
        if self.has_effect(TAG_MANACLE) and not self.disabled and run is not None \
                and hasattr(run, "hand_size"):
            run.hand_size = int(getattr(run, "hand_size") or 0) + 1
        self._unflip_jokers(run)
        self.name = ""
        self.mult = 0
        self.dollars = 0
        self.debuff = {}
        self.is_boss = False
        self.boss = False
        self.chips = 0
        self.disabled = False
        self.discards_sub = None
        self.hands_sub = None
        self.triggered = None
        self.prepped = True
        self.hands = None
        self.only_hand = None
        self.effects = frozenset()
        for card in _playing_cards(run):
            self.debuff_card(card, run=run)
        for joker in _jokers(run):
            self.debuff_card(joker, run=run)

    def disable(self, run=None) -> None:
        """blind.lua:356 - Chicot (or selling a Joker vs Verdant Leaf).

        Undoes every run-facing effect the blind had established, then re-runs
        the debuff pass (with `disabled=True`, so everything is cleared).
        """
        self.disabled = True
        self._unflip_jokers(run)
        if self.has_effect(TAG_WATER) and self.discards_sub:
            _run_add(run, "discards_left", self.discards_sub)
        if (self.has_effect(TAG_WHEEL) or self.has_effect(TAG_HOUSE)
                or self.has_effect(TAG_MARK) or self.has_effect(TAG_FISH)):
            for card in _playing_cards(run):
                _ability(card).pop("wheel_flipped", None)
        if self.has_effect(TAG_NEEDLE) and self.hands_sub:
            _run_add(run, "hands_left", self.hands_sub)
        if self.has_effect(TAG_WALL):
            self.chips = int(self.chips / 2)
        if self.has_effect(TAG_CERULEAN_BELL):
            for card in _playing_cards(run):
                _ability(card).pop("forced_selection", None)
            highlighted = getattr(run, "highlighted", None)
            if isinstance(highlighted, list):
                highlighted.clear()
        if self.has_effect(TAG_MANACLE):
            if run is not None and hasattr(run, "hand_size"):
                run.hand_size = int(getattr(run, "hand_size") or 0) + 1
            _draw_to_hand(run, 1)
        if self.has_effect(TAG_VIOLET_VESSEL):
            self.chips = int(self.chips / 3)
        for card in _playing_cards(run):
            self.debuff_card(card, run=run)
        for joker in _jokers(run):
            self.debuff_card(joker, run=run)


def _most_played(run) -> str | None:
    """`G.GAME.current_round.most_played_poker_hand` (The Ox)."""
    cr = getattr(run, "current_round", None)
    if isinstance(cr, dict):
        return cr.get("most_played_poker_hand")
    return getattr(run, "most_played_poker_hand", None)
