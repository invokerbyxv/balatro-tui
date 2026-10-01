"""Joker effects -- a faithful port of ``Card:calculate_joker`` (card.lua:2291-4061)
and ``Card:calculate_dollar_bonus`` (card.lua:1655-1679).

Dispatch
--------
Handlers are keyed by **centre key** (``j_jolly``, ``j_blueprint``, ...) -- never
by display name.  The Lua keys off ``self.ability.name`` in a giant linear
``if`` chain; we keep the same key names and the same branch *order* inside each
handler, but route to it through :data:`REGISTRY`.  :func:`_name` is the
``self.ability.name`` lookup for the handful of places that genuinely need the
display string (Blueprint/Brainstorm, Gift Card's ``set_cost`` probe, ...).

Contexts
--------
``hooks.Context`` maps 1:1 onto the Lua ``context`` table.  The events this
module answers are ``joker_main``, ``before``/``after`` (``cardarea == jokers``),
``individual`` (``cardarea == play``/``hand``), ``repetition``, ``discard``,
``end_of_round`` and the shop/round events (``selling_self``, ``selling_card``,
``reroll_shop``, ``ending_shop``, ``skip_blind``, ``playing_card_added``,
``first_hand_drawn``, ``setting_blind``, ``destroying_card``, ``cards_destroyed``,
``remove_playing_cards``, ``using_consumeable``, ``debuffed_hand``,
``pre_discard``, ``open_booster``, ``other_joker``).

State
-----
Per-joker mutable state lives in ``joker.ability`` -- exactly the Lua
``self.ability``.  Values the Lua seeds in ``Card:set_ability`` from the centre
config are read lazily from ``centers.json`` on first use (``_val``/``_extra``),
derived counters use ``setdefault`` (``stone_tally``, ``steel_tally``,
``nine_tally``, ``caino_xmult``, ``yorick_discards``, ``loyalty_remaining``,
``invis_rounds``, ``driver_tally``, ``to_do_poker_hand``, ...).

This module is stdlib-only, performs no I/O and never imports ``game_state``.
"""

from __future__ import annotations

from typing import Any, Callable

from . import hooks
from .card import RANK_IDS, rank_nominal
from .hooks import Context, Effect

__all__ = [
    "calculate", "dollar_bonus", "joker_flags", "copy_index", "has", "count",
    "REGISTRY", "HANDLERS", "UNIMPLEMENTED", "covered", "handlers_for",
    "JOKER_KEYS", "joker_keys",
]

# ---------------------------------------------------------------------------
# Centre data helpers
# ---------------------------------------------------------------------------

SUITS = ("Spades", "Hearts", "Clubs", "Diamonds")
_ID_RANKS = {v: k for k, v in RANK_IDS.items()}
_RANK_ALIASES = {
    "Ace": 14, "King": 13, "Queen": 12, "Jack": 11, "Ten": 10, "Nine": 9,
    "Eight": 8, "Seven": 7, "Six": 6, "Five": 5, "Four": 4, "Three": 3,
    "Two": 2,
}


def _centers() -> dict:
    from ..data import loader
    return loader.centers()


def _key(joker) -> str:
    if isinstance(joker, str):
        return joker
    return getattr(joker, "key", "") or ""


def _center(joker) -> dict:
    return _centers().get(_key(joker)) or {}


def _cfg(joker) -> dict:
    """The centre config (Lua ``center.config`` / ``self.ability`` seed)."""
    return dict(_center(joker).get("config") or {})


def _name(joker) -> str:
    """``self.ability.name`` -- the display name (centers[key]['name'])."""
    ab = getattr(joker, "ability", None)
    if isinstance(ab, dict) and ab.get("name"):
        return ab["name"]
    return _center(joker).get("name") or _key(joker)


def _ability(joker) -> dict:
    ab = getattr(joker, "ability", None)
    if isinstance(ab, dict):
        return ab
    return {}


def _val(joker, field, default=0):
    """``self.ability.<field>``, seeded lazily from the centre config."""
    ab = _ability(joker)
    if field in ab:
        return ab[field]
    cfg = _cfg(joker)
    if field in cfg:
        ab[field] = cfg[field]
        return cfg[field]
    ab[field] = default
    return default


def _extra(joker, default=None) -> dict:
    """``self.ability.extra`` as a dict (nested config, e.g. ``{s_mult = 3}``)."""
    if default is None:
        default = {}
    ab = _ability(joker)
    if "extra" not in ab:
        cfg = _cfg(joker)
        ab["extra"] = cfg.get("extra", {})
    extra = ab["extra"]
    if not isinstance(extra, dict):
        extra = {"value": extra}
    return extra


def _set_extra(joker, key, value):
    if isinstance(_ability(joker).get("extra"), dict):
        _ability(joker)["extra"][key] = value
    return value


def _ctx_blueprint(ctx: Context) -> bool:
    return bool(getattr(ctx, "blueprint", False))


def _eff(**kwargs) -> Effect:
    return Effect(**kwargs)


# ---------------------------------------------------------------------------
# run duck-type helpers (never import game_state)
# ---------------------------------------------------------------------------

def _run_attr(run, name, default=None):
    return getattr(run, name, default)


def _jokers(run) -> list:
    return list(_run_attr(run, "jokers", []) or [])


def _consumeables(run) -> list:
    return list(_run_attr(run, "consumeables", []) or [])


def _current_round(run) -> dict:
    return dict(_run_attr(run, "current_round", {}) or {})


def _cr(run, name, default=0):
    return _current_round(run).get(name, default)


def _modifiers(run) -> dict:
    return dict(_run_attr(run, "modifiers", {}) or {})


def _modifier(run, name, default=None):
    m = _modifiers(run)
    if name in m:
        return m[name]
    return default


def _param(run, name, default=0):
    params = _run_attr(run, "params", {}) or {}
    return params.get(name, default)


def _hand_size(run) -> int:
    v = _run_attr(run, "hand_size", None)
    if v is not None:
        return v
    return _param(run, "hand_size", 8)


def _joker_slots(run) -> int:
    return _param(run, "joker_slots", 5)


def _consumeable_slots(run) -> int:
    return _param(run, "consumable_slots", 2)


def _dollars(run) -> int:
    return int(_run_attr(run, "dollars", 0) or 0)


def _level(run, hand_key) -> dict:
    levels = _run_attr(run, "hand_levels", {}) or {}
    return levels.get(hand_key) or {}


def _played(run, hand_key) -> int:
    return int(_level(run, hand_key).get("played", 0) or 0)


def _playing_cards(run) -> list:
    fn = getattr(run, "playing_cards", None)
    if callable(fn):
        return list(fn() or [])
    return []


def _blind(run):
    return _run_attr(run, "the_blind", None)


def _blind_attr(run, name, default=None):
    b = _blind(run)
    if b is None:
        return default
    return getattr(b, name, default)


def _blind_is_boss(run) -> bool:
    b = _blind(run)
    if b is None:
        return False
    return bool(getattr(b, "is_boss", False) or getattr(b, "boss", False))


def _blind_chips(run) -> int:
    return int(_blind_attr(run, "chips", 0) or 0)


def _rng(run):
    return _run_attr(run, "rng", None)


def _chance(run, key, denom) -> bool:
    rng = _rng(run)
    if rng is None or not denom:
        return False
    return bool(rng.chance(key, denom))


def _roll_int(run, key, lo, hi) -> int:
    rng = _rng(run)
    if rng is None:
        return lo
    return int(rng.num(key, lo, hi))


def _pick(run, key, items):
    rng = _rng(run)
    if not items:
        return None
    if rng is None:
        return items[0]
    return rng.pick(key, list(items))


# -- card / hand predicates -------------------------------------------------

_CURRENT_FLAGS = None          # set by calculate(); Pareidolia face fallback


def _is_face(card, flags=None) -> bool:
    """`Card:is_face` - honors Pareidolia (card.lua:964)."""
    use_flags = flags if flags is not None else _CURRENT_FLAGS
    if getattr(use_flags, "pareidolia", False):
        return True
    return bool(getattr(card, "is_face", False))


def _card_id(card) -> int:
    return int(getattr(card, "id", 0) or 0)


def _nominal(card) -> float:
    fn = getattr(card, "nominal", None)
    if callable(fn):
        return fn()
    return float(_card_id(card))


_SUIT_LETTER = {"Spades": "S", "Hearts": "H", "Clubs": "C", "Diamonds": "D"}


def _is_suit(card, suit, flush_calc: bool = False) -> bool:
    """``Card:is_suit`` with full suit names normalised to the single letter
    the CLI's :meth:`Card.is_suit` compares against (card.lua:4064)."""
    fn = getattr(card, "is_suit", None)
    if not callable(fn):
        return False
    suit = _SUIT_LETTER.get(suit, suit)
    try:
        return bool(fn(suit, flush_calc=flush_calc))
    except TypeError:
        return bool(fn(suit))


def _card_name(card) -> str:
    return (getattr(card, "ability", {}) or {}).get("name") or ""


def _is_c_base(card) -> bool:
    """Lua: ``v.config.center ~= G.P_CENTERS.c_base`` (unenhanced)."""
    if bool(getattr(card, "debuffed", False)):
        return False
    return not getattr(card, "enhancement", None)


def _has_ranks(cards, ranks) -> bool:
    return any(c.rank in ranks for c in cards)


# -- context helpers --------------------------------------------------------

def _played_cards(ctx: Context) -> list:
    return list(ctx.full_hand or [])


def _scoring(ctx: Context) -> list:
    return list(ctx.scoring_hand or [])


def _held(ctx: Context) -> list:
    if ctx.held:
        return list(ctx.held)
    return list(_run_attr(ctx.run, "hand", []) or [])


def _hand_type_played(ctx: Context, hand_type: str) -> bool:
    """Lua ``next(context.poker_hands[type])``."""
    if not hand_type:
        return False
    return bool((ctx.poker_hands or {}).get(hand_type))


def _ctx_current_round(run, ctx: Context, name, default=0):
    """Read a ``current_round`` value, preferring the hook's own snapshot."""
    val = getattr(ctx, name, None)
    if val is not None:
        return val
    return _cr(run, name, default)


def _hands_left(run, ctx: Context) -> int:
    return int(_ctx_current_round(run, ctx, "hands_left", _run_attr(run, "hands_left", 0)) or 0)


def _discards_left(run, ctx: Context) -> int:
    return int(_ctx_current_round(run, ctx, "discards_left",
                                  _run_attr(run, "discards_left", 0)) or 0)


def _discards_used(run, ctx: Context) -> int:
    return int(_ctx_current_round(run, ctx, "discards_used", 0) or 0)


def _hands_played(run, ctx: Context) -> int:
    return int(_ctx_current_round(run, ctx, "hands_played", 0) or 0)


# ---------------------------------------------------------------------------
# Blueprint / Brainstorm (card.lua:2304-2334)
# ---------------------------------------------------------------------------

def copy_index(run, i: int) -> int:
    """The joker index Blueprint/Brainstorm at ``i`` would copy (-1 if none).

    Blueprint copies the joker to its right (``i + 1``); Brainstorm copies the
    leftmost joker (index 0).  Both must not copy themselves.
    """
    jokers = _jokers(run)
    if not (0 <= i < len(jokers)):
        return -1
    key = _key(jokers[i])
    if key == "j_blueprint":
        target = i + 1
        if target < len(jokers) and jokers[target] is not jokers[i]:
            return target
        return -1
    if key == "j_brainstorm":
        # The leftmost joker; a Brainstorm that *is* the leftmost copies
        # nothing (card.lua:2322-2323 requires other_joker ~= self).
        if jokers[0] is not jokers[i]:
            return 0
        return -1
    return -1


def _copy_handler(run, joker, ctx: Context):
    """Copy the target joker's effect -- the Lua ``context.blueprint`` recursion.

    ``ctx.blueprint`` true means "you are already a copy, do not copy again"
    (the Lua bumps ``context.blueprint`` and returns when it exceeds the joker
    count, which is exactly this guard plus a recursion bound).
    """
    if _ctx_blueprint(ctx):
        return None
    jokers = _jokers(run)
    try:
        me = jokers.index(joker)
    except ValueError:
        me = next((i for i, j in enumerate(jokers) if _key(j) == _key(joker)), -1)
    if me < 0:
        return None
    target_i = copy_index(run, me)
    if target_i < 0:
        return None
    target = jokers[target_i]
    # The Lua forwards the whole context with only `blueprint` bumped; the
    # `other_joker` flag belongs to the separate joker-on-joker pass and must
    # not be set here, or the target's scoring tail would refuse to run.
    sub = ctx.with_(blueprint=True, joker=target)
    return calculate(run, target, sub)


# ---------------------------------------------------------------------------
# calculate_joker -- the dispatch
# ---------------------------------------------------------------------------

def _score_branches(run, joker, ctx: Context):
    """The ``else`` tail of the Lua chain: the ``cardarea == G.jokers`` scoring pass.

    Note there is deliberately no ``ctx.blueprint`` guard here: the Lua's only
    blueprint guard in this branch is on the *stateful* before/end-of-round
    jokers (which check it locally), while Blueprint/Brainstorm deliberately
    forward the whole context including ``blueprint = true`` so that plain
    scoring jokers still fire.  Recursion is bounded by :func:`_copy_handler`.
    """
    name = _name(joker)

    # -- before the hand scores --------------------------------------------
    if ctx.event == hooks.HOOK_BEFORE:
        if name == "Spare Trousers":
            if (_hand_type_played(ctx, "Two Pair") or _hand_type_played(ctx, "Full House")) \
                    and not _ctx_blueprint(ctx):
                ab = _ability(joker)
                ab["mult"] = ab.get("mult", 0) + _val(joker, "extra", 2)
        elif name == "Space Joker":
            if _chance(run, "space", _val(joker, "extra", 4)):
                hand = ctx.scoring_name or "High Card"
                return _eff(level_up=True, message="Level Up!")
        elif name == "Square Joker":
            if len(_played_cards(ctx)) == 4 and not _ctx_blueprint(ctx):
                _set_extra(joker, "chips", _extra(joker).get("chips", 0)
                           + _extra(joker).get("chip_mod", 4))
        elif name == "Runner":
            if _hand_type_played(ctx, "Straight") and not _ctx_blueprint(ctx):
                _set_extra(joker, "chips", _extra(joker).get("chips", 0)
                           + _extra(joker).get("chip_mod", 15))
        elif name == "Midas Mask":
            if not _ctx_blueprint(ctx):
                for c in _scoring(ctx):
                    if _is_face(c):
                        _goldify(c)
        elif name == "Vampire":
            if not _ctx_blueprint(ctx):
                enhanced = []
                for c in _scoring(ctx):
                    if not _is_c_base(c) and not bool(getattr(c, "debuffed", False)):
                        enhanced.append(c)
                        _devamp(c)
                if enhanced:
                    ab = _ability(joker)
                    ab["x_mult"] = ab.get("x_mult", 1) + _val(joker, "extra", 0.1) * len(enhanced)
        elif name == "DNA":
            if _hands_played(run, ctx) == 0 and len(_played_cards(ctx)) == 1:
                return _eff(create=[{"kind": "copy", "card": _played_cards(ctx)[0],
                                     "count": 1}], extra={"playing_cards_created": [True]})
        elif name == "Ride the Bus":
            if not _ctx_blueprint(ctx):
                ab = _ability(joker)
                if any(_is_face(c) for c in _scoring(ctx)):
                    ab["mult"] = 0
                else:
                    ab["mult"] = ab.get("mult", 0) + _val(joker, "extra", 1)
        elif name == "Obelisk":
            if not _ctx_blueprint(ctx):
                # Grows while the played hand is the most-played hand (ties
                # count); resets to 1x when another visible hand has been
                # played strictly more often.  (The decompiled Lua's variable
                # naming is inverted relative to the in-game text; the
                # in-game behaviour -- and the tests -- follow the text.)
                mine = _played(run, ctx.scoring_name) if ctx.scoring_name else 0
                levels = _run_attr(run, "hand_levels", {}) or {}
                above = any(k != ctx.scoring_name and v.get("visible", True)
                            and int(v.get("played", 0) or 0) > mine
                            for k, v in levels.items())
                ab = _ability(joker)
                if above:
                    if ab.get("x_mult", 1) > 1:
                        ab["x_mult"] = 1
                else:
                    ab["x_mult"] = ab.get("x_mult", 1) + _val(joker, "extra", 0.2)
        elif name == "Green Joker":
            if not _ctx_blueprint(ctx):
                ab = _ability(joker)
                ab["mult"] = ab.get("mult", 0) + _extra(joker).get("hand_add", 1)
        return None

    # -- after the hand scores ---------------------------------------------
    if ctx.event == hooks.HOOK_AFTER:
        if name == "Ice Cream":
            if not _ctx_blueprint(ctx):
                extra = _extra(joker)
                if extra.get("chips", 0) - extra.get("chip_mod", 5) <= 0:
                    return _eff(extra={"destroy_self": True})
                _set_extra(joker, "chips", extra.get("chips", 0) - extra.get("chip_mod", 5))
        elif name == "Seltzer":
            if not _ctx_blueprint(ctx):
                ab = _ability(joker)
                ab["extra"] = ab.get("extra", 10) - 1
                if ab["extra"] <= 0:
                    return _eff(extra={"destroy_self": True})
        return None

    # -- the main scoring pass ---------------------------------------------
    if name == "Loyalty Card":
        extra = _extra(joker)
        every = extra.get("every", 5)
        ab = _ability(joker)
        played_at_create = int(ab.get("hands_played_at_create", 0) or 0)
        if "total_hands_played" in ab:
            total = int(ab["total_hands_played"])
        else:
            total = played_at_create + _played_total(run)
        ab["loyalty_remaining"] = (every - 1 - (total - played_at_create)) % (every + 1)
        if ab["loyalty_remaining"] == every:
            return _eff(x_mult=extra.get("Xmult", 4))

    if name != "Seeing Double":
        x = _val(joker, "x_mult", 1) or 1
        if x > 1 and (not _val(joker, "type", "") or _hand_type_played(ctx, _val(joker, "type", ""))):
            return _eff(x_mult=x)

    t_mult = _val(joker, "t_mult", 0)
    if t_mult and t_mult > 0 and _hand_type_played(ctx, _val(joker, "type", "")):
        return _eff(mult=t_mult)

    t_chips = _val(joker, "t_chips", 0)
    if t_chips and t_chips > 0 and _hand_type_played(ctx, _val(joker, "type", "")):
        return _eff(chips=t_chips)

    if name == "Half Joker":
        if len(_played_cards(ctx)) <= _extra(joker).get("size", 3):
            return _eff(mult=_extra(joker).get("mult", 20))
    elif name == "Abstract Joker":
        n = sum(1 for j in _jokers(run)
                if _ability(j).get("set", "Joker") == "Joker")
        m = n * _val(joker, "extra", 3)
        if m:
            return _eff(mult=m)
    elif name == "Acrobat":
        if _hands_left(run, ctx) == 0:
            return _eff(x_mult=_val(joker, "extra", 3))
    elif name == "Mystic Summit":
        extra = _extra(joker)
        if _discards_left(run, ctx) == extra.get("d_remaining", 0):
            return _eff(mult=extra.get("mult", 15))
    elif name == "Misprint":
        extra = _extra(joker)
        return _eff(mult=_roll_int(run, "misprint", extra.get("min", 0), extra.get("max", 23)))
    elif name == "Banner":
        left = _discards_left(run, ctx)
        if left > 0:
            return _eff(chips=left * _val(joker, "extra", 30))
    elif name == "Stuntman":
        return _eff(chips=_extra(joker).get("chip_mod", 250))
    elif name == "Matador":
        if bool(_blind_attr(run, "triggered", False)):
            return _eff(dollars=_val(joker, "extra", 8))
    elif name == "Supernova":
        if ctx.scoring_name:
            n = _played(run, ctx.scoring_name)
            if n:
                return _eff(mult=n)
    elif name == "Ceremonial Dagger":
        m = _ability(joker).get("mult", 0)
        if m > 0:
            return _eff(mult=m)
    elif name == "Vagabond":
        if _dollars(run) <= _val(joker, "extra", 4):
            return _eff(create=[{"kind": "Tarot", "count": 1}])
    elif name == "Superposition":
        if any(_card_id(c) == 14 for c in _scoring(ctx)) and _hand_type_played(ctx, "Straight"):
            return _eff(create=[{"kind": "Tarot", "count": 1}])
    elif name == "Seance":
        if _hand_type_played(ctx, _extra(joker).get("poker_hand", "Straight Flush")):
            return _eff(create=[{"kind": "Spectral", "count": 1}])
    elif name in ("Greedy Joker", "Lusty Joker", "Wrathful Joker",
                  "Gluttonous Joker"):
        # The per-card suit effect, aggregated for the main pass: any scoring
        # card of the suit grants the flat mult once.
        extra = _extra(joker)
        if any(_is_suit(c, extra.get("suit", "")) for c in _scoring(ctx)):
            return _eff(mult=extra.get("s_mult", 3))
    elif name == "Flower Pot":
        # The played hand (not just the scoring subset) must hold all four
        # suits -- a 5-card high-card hand can still trigger it.
        if _all_four_suits(_played_cards(ctx)):
            return _eff(x_mult=_val(joker, "extra", 3))
    elif name == "Seeing Double":
        if _seeing_double(_played_cards(ctx)):
            return _eff(x_mult=_val(joker, "extra", 2))
    elif name == "Wee Joker":
        chips = _extra(joker).get("chips", 0)
        if chips:
            return _eff(chips=chips)
    elif name == "Castle":
        chips = _extra(joker).get("chips", 0)
        if chips > 0:
            return _eff(chips=chips)
    elif name == "Blue Joker":
        n = len(_run_attr(run, "deck", []) or [])
        if n > 0:
            return _eff(chips=_val(joker, "extra", 2) * n)
    elif name == "Erosion":
        start = _run_attr(run, "starting_deck_size", None)
        if start is None:
            start = 52  # standard deck when the run object has no counter
        lost = int(start) - len(_playing_cards(run))
        if lost > 0:
            return _eff(mult=_val(joker, "extra", 4) * lost)
    elif name == "Square Joker":
        return _eff(chips=_extra(joker).get("chips", 0))
    elif name == "Runner":
        return _eff(chips=_extra(joker).get("chips", 0))
    elif name == "Ice Cream":
        return _eff(chips=_extra(joker).get("chips", 100))
    elif name == "Stone Joker":
        tally = _stone_tally(run, joker)
        if tally > 0:
            return _eff(chips=_val(joker, "extra", 25) * tally)
    elif name == "Steel Joker":
        tally = _steel_tally(run, joker)
        if tally > 0:
            return _eff(x_mult=1 + _val(joker, "extra", 0.2) * tally)
    elif name == "Bull":
        d = max(0, _dollars(run))
        if d > 0:
            return _eff(chips=_val(joker, "extra", 2) * d)
    elif name == "Driver's License":
        if int(_ability(joker).get("driver_tally", 0) or 0) >= 16:
            return _eff(x_mult=_val(joker, "extra", 3))
    elif name == "Blackboard":
        # Clubs/Spades count vs all held cards; debuffed cards still count as
        # cards but their suit check fails (card.lua:3951-3964)
        hand = list(_run_attr(run, "hand", []) or [])
        if hand and all(
                (not getattr(c, "debuffed", False))
                and (_is_suit(c, "Clubs", True) or _is_suit(c, "Spades", True))
                for c in hand):
            return _eff(x_mult=_val(joker, "extra", 3))
    elif name == "Joker Stencil":
        # Only while a joker slot is free (card.lua:3966).
        if _joker_slots(run) - len(_jokers(run)) > 0:
            x = _val(joker, "x_mult", 1) or 1
            if x > 1:
                return _eff(x_mult=x)
    elif name == "To Do List":
        # The dollar bonus is granted on the main scoring pass (the Lua keys
        # it off `context.before`; the CLI's core asks for it in joker_main).
        if ctx.scoring_name and ctx.scoring_name == _ability(joker).get("to_do_poker_hand"):
            extra = _extra(joker)
            return _eff(dollars=extra.get("dollars", 4))
    elif name == "Swashbuckler":
        # set_cost recomputes mult as the sell value of every other joker
        # (card.lua:4240-4248)
        m = 0
        for other in _jokers(run):
            if other is joker:
                continue
            m += _sell_cost(run, other)
        if m > 0:
            _ability(joker)["mult"] = m
            return _eff(mult=m)
        return None
    elif name == "Joker":
        return _eff(mult=_val(joker, "mult", 4))
    elif name in ("Spare Trousers", "Ride the Bus", "Flash Card", "Popcorn",
                  "Green Joker", "Red Card"):
        m = _ability(joker).get("mult", 0)
        if m > 0:
            return _eff(mult=m)
    elif name == "Fortune Teller":
        n = _consumeable_usage_total(run, "tarot")
        if n > 0:
            return _eff(mult=n)
    elif name == "Gros Michel":
        return _eff(mult=_extra(joker).get("mult", 15))
    elif name == "Cavendish":
        return _eff(x_mult=_extra(joker).get("Xmult", 3))
    elif name == "Card Sharp":
        if ctx.scoring_name and int(_level(run, ctx.scoring_name)
                                     .get("played_this_round", 0) or 0) > 1:
            return _eff(x_mult=_extra(joker).get("Xmult", 3))
    elif name == "Bootstraps":
        extra = _extra(joker)
        per = extra.get("dollars", 5)
        if per:
            n = _dollars(run) // per
            if n >= 1:
                return _eff(mult=extra.get("mult", 2) * n)
    elif name == "Caino":
        x = _val(joker, "caino_xmult", 1) or 1
        if x > 1:
            return _eff(x_mult=x)
    elif name == "Throwback":
        x = _val(joker, "x_mult", 1) or 1
        if x > 1:
            return _eff(x_mult=x)
    elif name == "Hit the Road":
        x = _ability(joker).get("x_mult", 1) or 1
        if x > 1:
            return _eff(x_mult=x)
    elif name == "Campfire":
        x = _ability(joker).get("x_mult", 1) or 1
        if x > 1:
            return _eff(x_mult=x)
    elif name == "Ramen":
        x = _ability(joker).get("x_mult", 2) or 2
        if x > 1:
            return _eff(x_mult=x)
    elif name == "Hologram":
        x = _ability(joker).get("x_mult", 1) or 1
        if x > 1:
            return _eff(x_mult=x)
    elif name == "Constellation":
        x = _ability(joker).get("x_mult", 1) or 1
        if x > 1:
            return _eff(x_mult=x)
    elif name == "Vampire":
        x = _ability(joker).get("x_mult", 1) or 1
        if x > 1:
            return _eff(x_mult=x)
    elif name == "Lucky Cat":
        x = _ability(joker).get("x_mult", 1) or 1
        if x > 1:
            return _eff(x_mult=x)
    elif name == "Obelisk":
        x = _ability(joker).get("x_mult", 1) or 1
        if x > 1:
            return _eff(x_mult=x)
    elif name == "Glass Joker":
        x = _ability(joker).get("x_mult", 1) or 1
        if x > 1:
            return _eff(x_mult=x)
    elif name == "Madness":
        x = _ability(joker).get("x_mult", 1) or 1
        if x > 1:
            return _eff(x_mult=x)
    elif name == "Yorick":
        x = _ability(joker).get("x_mult", 1) or 1
        if x > 1:
            return _eff(x_mult=x)
    return None


def _played_total(run) -> int:
    """``G.GAME.hands_played`` -- total hands played this run."""
    total = _run_attr(run, "hands_played_total", None)
    if total is not None:
        return int(total)
    return int(_cr(run, "hands_played", 0) or 0)


def _goldify(card):
    if hasattr(card, "enhancement"):
        card.enhancement = "m_gold"
        card.ability = {"name": "Gold Card", "effect": "Gold Card", "h_dollars": 3}


def _devamp(card):
    if hasattr(card, "enhancement"):
        card.enhancement = None
        card.ability = {}


def _all_four_suits(cards) -> bool:
    """Flower Pot's suit tally (card.lua:3807-3838, Wild Card second pass)."""
    suits = {s: 0 for s in SUITS}
    for c in cards:
        if _card_name(c) == "Wild Card":
            continue
        for s in SUITS:
            if suits[s] == 0 and _is_suit(c, s, True):
                suits[s] += 1
                break
    for c in cards:
        if _card_name(c) != "Wild Card":
            continue
        for s in SUITS:
            if suits[s] == 0 and _is_suit(c, s):
                suits[s] += 1
                break
    return all(v > 0 for v in suits.values())


def _seeing_double(cards) -> bool:
    """Seeing Double's suit tally (card.lua:3840-3872)."""
    suits = {s: 0 for s in SUITS}
    for c in cards:
        if _card_name(c) == "Wild Card":
            continue
        for s in SUITS:
            if _is_suit(c, s):
                suits[s] += 1
    for c in cards:
        if _card_name(c) != "Wild Card":
            continue
        for s in ("Clubs", "Diamonds", "Spades", "Hearts"):
            if suits[s] == 0 and _is_suit(c, s):
                suits[s] += 1
                break
    return (suits["Hearts"] > 0 or suits["Diamonds"] > 0 or suits["Spades"] > 0) \
        and suits["Clubs"] > 0


def _consumeable_usage_total(run, kind: str) -> int:
    usage = _run_attr(run, "consumeable_usage_total", None)
    if isinstance(usage, dict):
        return int(usage.get(kind, 0) or 0)
    return int(_cr(run, "consumeable_usage_total_" + kind, 0) or 0)


def _stone_tally(run, joker) -> int:
    ab = _ability(joker)
    if "stone_tally" not in ab:
        ab["stone_tally"] = sum(1 for c in _playing_cards(run)
                                if getattr(c, "enhancement", None) == "m_stone")
    return int(ab["stone_tally"] or 0)


def _steel_tally(run, joker) -> int:
    ab = _ability(joker)
    if "steel_tally" not in ab:
        ab["steel_tally"] = sum(1 for c in _playing_cards(run)
                                if getattr(c, "enhancement", None) == "m_steel")
    return int(ab["steel_tally"] or 0)


def _nine_tally(run, joker) -> int:
    ab = _ability(joker)
    if "nine_tally" not in ab:
        ab["nine_tally"] = sum(1 for c in _playing_cards(run) if _card_id(c) == 9)
    return int(ab["nine_tally"] or 0)


# -- individual (per scored / per held card) --------------------------------

def _individual(run, joker, ctx: Context):
    if ctx.event != hooks.HOOK_INDIVIDUAL:
        return None
    name = _name(joker)
    card = ctx.other_card
    if ctx.cardarea == hooks.AREA_PLAY:
        if card is None:
            return None
        if name == "Hiker":
            ab = getattr(card, "ability", None)
            if isinstance(ab, dict):
                ab["perma_bonus"] = ab.get("perma_bonus", 0) + _val(joker, "extra", 5)
            return _eff()
        if name == "Lucky Cat":
            if not _ctx_blueprint(ctx) and (getattr(card, "lucky_trigger", False)
                                            or _ability(card).get("lucky_trigger")):
                ab = _ability(joker)
                ab["x_mult"] = ab.get("x_mult", 1) + _val(joker, "extra", 0.25)
            return None
        if name == "Wee Joker":
            if _card_id(card) == 2 and not _ctx_blueprint(ctx):
                _set_extra(joker, "chips", _extra(joker).get("chips", 0)
                           + _extra(joker).get("chip_mod", 8))
            return None
        if name == "Photograph":
            first_face = next((c for c in _scoring(ctx) if _is_face(c)), None)
            if card is first_face:
                return _eff(x_mult=_val(joker, "extra", 2))
            return None
        if name == "8 Ball":
            if _card_id(card) == 8 and _chance(run, "8ball", _val(joker, "extra", 4)):
                return _eff(create=[{"kind": "Tarot", "count": 1}])
            return None
        if name == "The Idol":
            idol = _cr(run, "idol_card", {}) or {}
            if _card_id(card) == _rank_id(idol) and _is_suit(card, idol.get("suit", "")):
                return _eff(x_mult=_val(joker, "extra", 2))
            return None
        if name == "Scary Face":
            if _is_face(card):
                return _eff(chips=_val(joker, "extra", 30))
            return None
        if name == "Smiley Face":
            if _is_face(card):
                return _eff(mult=_val(joker, "extra", 5))
            return None
        if name == "Golden Ticket":
            if _card_name(card) == "Gold Card":
                return _eff(dollars=_val(joker, "extra", 4))
            return None
        if name == "Scholar":
            if _card_id(card) == 14:
                extra = _extra(joker)
                return _eff(chips=extra.get("chips", 20), mult=extra.get("mult", 4))
            return None
        if name == "Walkie Talkie":
            if _card_id(card) in (10, 4):
                extra = _extra(joker)
                return _eff(chips=extra.get("chips", 10), mult=extra.get("mult", 4))
            return None
        if name == "Business Card":
            if _is_face(card) and _chance(run, "business", _val(joker, "extra", 2)):
                return _eff(dollars=2)
            return None
        if name == "Fibonacci":
            if _card_id(card) in (2, 3, 5, 8, 14):
                return _eff(mult=_val(joker, "extra", 8))
            return None
        if name == "Even Steven":
            cid = _card_id(card)
            if 0 <= cid <= 10 and cid % 2 == 0:
                return _eff(mult=_val(joker, "extra", 4))
            return None
        if name == "Odd Todd":
            cid = _card_id(card)
            if (0 <= cid <= 10 and cid % 2 == 1) or cid == 14:
                return _eff(chips=_val(joker, "extra", 31))
            return None
        if _center(joker).get("effect") == "Suit Mult":
            if _is_suit(card, _extra(joker).get("suit", "")):
                return _eff(mult=_extra(joker).get("s_mult", 3))
            return None
        if name == "Rough Gem":
            if _is_suit(card, "Diamonds"):
                return _eff(dollars=_val(joker, "extra", 1))
            return None
        if name == "Onyx Agate":
            if _is_suit(card, "Clubs"):
                return _eff(mult=_val(joker, "extra", 7))
            return None
        if name == "Arrowhead":
            if _is_suit(card, "Spades"):
                return _eff(chips=_val(joker, "extra", 50))
            return None
        if name == "Bloodstone":
            extra = _extra(joker)
            if _is_suit(card, "Hearts") and _chance(run, "bloodstone", extra.get("odds", 2)):
                return _eff(x_mult=extra.get("Xmult", 1.5))
            return None
        if name == "Ancient Joker":
            if _is_suit(card, (_cr(run, "ancient_card", {}) or {}).get("suit", "")):
                return _eff(x_mult=_val(joker, "extra", 1.5))
            return None
        if name == "Triboulet":
            if _card_id(card) in (12, 13):
                return _eff(x_mult=_val(joker, "extra", 2))
            return None
        return None

    if ctx.cardarea == hooks.AREA_HAND:
        if card is None:
            return None
        if name == "Shoot the Moon":
            # Lua returns {h_mult = 13}; the CLI folds held flat mult into
            # Effect.mult (scoring._apply_held adds eff.mult to the held mult).
            if _card_id(card) == 12 and not bool(getattr(card, "debuffed", False)):
                return _eff(mult=13)
            return None
        if name == "Baron":
            if _card_id(card) == 13 and not bool(getattr(card, "debuffed", False)):
                return _eff(x_mult=_val(joker, "extra", 1.5))
            return None
        if name == "Reserved Parking":
            extra = _extra(joker)
            if _is_face(card) and _chance(run, "parking", extra.get("odds", 2)):
                if not bool(getattr(card, "debuffed", False)):
                    return _eff(dollars=extra.get("dollars", 1))
            return None
        if name == "Raised Fist":
            # Lua: h_mult = 2 * base.nominal (integer chip value, card.lua:3320).
            raised = _raised_fist_card(run)
            if raised is card and not bool(getattr(card, "debuffed", False)):
                return _eff(mult=2 * int(rank_nominal(card.rank)))
            return None
        return None
    return None


def _rank_id(spec) -> int:
    if not isinstance(spec, dict):
        return 0
    if spec.get("id"):
        return int(spec["id"])
    rank = spec.get("rank")
    if rank is None:
        return 0
    if rank in RANK_IDS:
        return RANK_IDS[rank]
    return _RANK_ALIASES.get(str(rank), 0)


def _raised_fist_card(run):
    """Raised Fist: the lowest-id non-stone card in hand (card.lua:3320-3325)."""
    best, best_id, best_card = 15, 15, None
    for c in (_run_attr(run, "hand", []) or []):
        cid = _card_id(c)
        if best_id >= cid and getattr(c, "enhancement", None) != "m_stone":
            best = _nominal(c)
            best_id = cid
            best_card = c
    return best_card


# -- repetition (retriggers) ------------------------------------------------

def _repetition(run, joker, ctx: Context):
    if ctx.event != hooks.HOOK_REPETITION:
        return None
    name = _name(joker)
    card = ctx.other_card
    if ctx.cardarea == hooks.AREA_PLAY:
        if name == "Sock and Buskin" and card is not None and _is_face(card):
            return _eff(repetitions=_val(joker, "extra", 1))
        if name == "Hanging Chad" and card is not None and _scoring(ctx) \
                and card is _scoring(ctx)[0]:
            return _eff(repetitions=_val(joker, "extra", 2))
        if name == "Dusk" and _hands_left(run, ctx) == 0:
            return _eff(repetitions=_val(joker, "extra", 1))
        if name == "Seltzer":
            return _eff(repetitions=1)
        if name == "Hack" and card is not None and _card_id(card) in (2, 3, 4, 5):
            return _eff(repetitions=_val(joker, "extra", 1))
        return None
    if ctx.cardarea == hooks.AREA_HAND:
        if name == "Mime" and _held_effects(ctx):
            return _eff(repetitions=_val(joker, "extra", 1))
        return None
    return None


def _held_effects(ctx: Context) -> bool:
    """Lua ``next(context.card_effects[1]) or #context.card_effects > 1``.

    The core only asks for a held-card retrigger when the card actually carries
    held effects (Steel / Gold / h_mult), so a context without an explicit
    ``card_effects`` list is treated as "there is one" -- otherwise Mime would
    never retrigger held cards.
    """
    effects = getattr(ctx, "card_effects", None)
    if effects is None:
        effects = (ctx.extra or {}).get("card_effects")
    if effects is None:
        return True
    return bool(effects)


# -- discard / pre_discard --------------------------------------------------

def _discard(run, joker, ctx: Context):
    if ctx.event != hooks.HOOK_DISCARD:
        return None
    name = _name(joker)
    card = ctx.other_card
    if name == "Ramen":
        if _ctx_blueprint(ctx):
            return None
        ab = _ability(joker)
        x = ab.get("x_mult", 2) or 2
        extra = _val(joker, "extra", 0.01)
        if x - extra <= 1:
            return _eff(extra={"destroy_self": True})
        ab["x_mult"] = x - extra
        return _eff()
    if name == "Yorick":
        if _ctx_blueprint(ctx):
            return None
        ab = _ability(joker)
        extra = _extra(joker)
        if "yorick_discards" not in ab:
            ab["yorick_discards"] = extra.get("discards", 23)
        if ab["yorick_discards"] <= 1:
            ab["yorick_discards"] = extra.get("discards", 23)
            ab["x_mult"] = ab.get("x_mult", 1) + extra.get("xmult", 1)
        else:
            ab["yorick_discards"] -= 1
        return None
    if name == "Trading Card":
        if not _ctx_blueprint(ctx) and _discards_used(run, ctx) <= 0 \
                and len(_played_cards(ctx)) == 1:
            return _eff(dollars=_val(joker, "extra", 3), remove_played=True)
        return None
    if name == "Castle":
        if _ctx_blueprint(ctx):
            return None
        castle = _cr(run, "castle_card", {}) or {}
        if card is not None and not bool(getattr(card, "debuffed", False)) \
                and _is_suit(card, castle.get("suit", "")):
            extra = _extra(joker)
            _set_extra(joker, "chips", extra.get("chips", 0) + extra.get("chip_mod", 3))
        return None
    if name == "Mail-In Rebate":
        if card is not None and not bool(getattr(card, "debuffed", False)) \
                and _card_id(card) == _rank_id(_cr(run, "mail_card", {}) or {}):
            return _eff(dollars=_val(joker, "extra", 5))
        return None
    if name == "Hit the Road":
        if not _ctx_blueprint(ctx) and card is not None \
                and not bool(getattr(card, "debuffed", False)) and _card_id(card) == 11:
            ab = _ability(joker)
            ab["x_mult"] = ab.get("x_mult", 1) + _val(joker, "extra", 0.5)
        return None
    if name == "Green Joker":
        full = _played_cards(ctx)
        if full and card is full[-1]:
            ab = _ability(joker)
            ab["mult"] = max(0, ab.get("mult", 0) - _extra(joker).get("discard_sub", 1))
        return None
    if name == "Faceless Joker":
        full = _played_cards(ctx)
        if full and card is full[-1]:
            if sum(1 for c in full if _is_face(c)) >= _extra(joker).get("faces", 3):
                return _eff(dollars=_extra(joker).get("dollars", 5))
        return None
    return None


def _pre_discard(run, joker, ctx: Context):
    """Burnt Joker: level the discarded hand up (card.lua:2748-2755)."""
    if ctx.event != "pre_discard":
        return None
    if _name(joker) == "Burnt Joker":
        if _discards_used(run, ctx) <= 0 and not ctx.hook:
            hand = ctx.scoring_name or ctx.extra.get("hand_name")
            if hand:
                return _eff(level_up=[(hand, 1)], message="Level Up!")
    return None


def _skipping_booster(run, joker, ctx: Context):
    """Red Card: +3 Mult per skipped Booster Pack (card.lua:2441-2455)."""
    if ctx.event != hooks.HOOK_SKIPPING_BOOSTER:
        return None
    if _name(joker) == "Red Card":
        ab = _ability(joker)
        ab["mult"] = (ab.get("mult", 0) or 0) + _val(joker, "extra", 3)
        return _eff(message="+3 Mult")
    return None


# -- end of round -----------------------------------------------------------

def _end_of_round(run, joker, ctx: Context):
    if ctx.event != hooks.HOOK_END_OF_ROUND:
        return None
    if _ctx_blueprint(ctx):
        return None
    name = _name(joker)
    if name == "Campfire":
        if _blind_is_boss(run) and (_ability(joker).get("x_mult", 1) or 1) > 1:
            _ability(joker)["x_mult"] = 1
            return _eff(message="Reset")
    elif name == "Rocket":
        if _blind_is_boss(run):
            extra = _extra(joker)
            _set_extra(joker, "dollars", extra.get("dollars", 1) + extra.get("increase", 2))
    elif name == "Turtle Bean":
        extra = _extra(joker)
        mod = extra.get("h_mod", 1)
        if extra.get("h_size", 5) - mod <= 0:
            return _eff(extra={"destroy_self": True})
        _set_extra(joker, "h_size", extra.get("h_size", 5) - mod)
        hs = _run_attr(run, "hand_size", None)
        if hs is not None:
            try:
                setattr(run, "hand_size", hs - mod)
            except Exception:
                pass
    elif name == "Invisible Joker":
        ab = _ability(joker)
        ab["invis_rounds"] = ab.get("invis_rounds", 0) + 1
        return _eff()
    elif name == "Popcorn":
        ab = _ability(joker)
        if ab.get("mult", 20) - _val(joker, "extra", 4) <= 0:
            return _eff(extra={"destroy_self": True})
        ab["mult"] = ab.get("mult", 20) - _val(joker, "extra", 4)
    elif name == "To Do List":
        _reroll_to_do(run, joker)
    elif name == "Egg":
        ab = _ability(joker)
        ab["extra_value"] = ab.get("extra_value", 0) + _val(joker, "extra", 3)
    elif name == "Gift Card":
        amount = _val(joker, "extra", 1)
        for other in _jokers(run) + _consumeables(run):
            ab = getattr(other, "ability", None)
            if isinstance(ab, dict):
                ab["extra_value"] = ab.get("extra_value", 0) + amount
    elif name == "Hit the Road":
        if (_ability(joker).get("x_mult", 1) or 1) > 1:
            _ability(joker)["x_mult"] = 1
            return _eff(message="Reset")
    elif name in ("Gros Michel", "Cavendish"):
        denom = _extra(joker).get("odds", 6 if name == "Gros Michel" else 1000)
        if _chance(run, "cavendish" if name == "Cavendish" else "gros_michel", denom):
            if name == "Gros Michel":
                flags = _run_attr(run, "pool_flags", None)
                if not isinstance(flags, dict):
                    flags = {}
                    try:
                        setattr(run, "pool_flags", flags)
                    except Exception:
                        pass
                flags["gros_michel_extinct"] = True
            return _eff(extra={"destroy_self": True})
        return _eff()
    elif name == "Mr. Bones":
        if ctx.game_over and _blind_chips(run) > 0 \
                and int(_run_attr(run, "chips", 0) or 0) / _blind_chips(run) >= 0.25:
            return _eff(saved=True)
    return None


def _reroll_to_do(run, joker):
    levels = _run_attr(run, "hand_levels", {}) or {}
    ab = _ability(joker)
    old = ab.get("to_do_poker_hand")
    pool = [k for k, v in levels.items() if v.get("visible", True) and k != old]
    pick = _pick(run, "to_do", pool)
    ab["to_do_poker_hand"] = pick or old


# -- shop / blind-setup / destruction events --------------------------------

def _selling_self(run, joker, ctx: Context):
    if ctx.event != hooks.HOOK_SELLING_SELF:
        return None
    name = _name(joker)
    if name == "Luchador":
        if _blind_is_boss(run) and not _blind_attr(run, "disabled", False):
            return _eff(disabled_blind=True)
    elif name == "Diet Cola":
        return _eff(extra={"add_tag": "tag_double"})
    elif name == "Invisible Joker":
        ab = _ability(joker)
        if ab.get("invis_rounds", 0) >= _val(joker, "extra", 2):
            others = [j for j in _jokers(run) if j is not joker]
            chosen = _pick(run, "invisible", others)
            if chosen is not None:
                ab["invis_rounds"] = 0
                return _eff(create=[{"kind": "copy_joker", "card": chosen, "count": 1}])
    return None


def _selling_card(run, joker, ctx: Context):
    if ctx.event != hooks.HOOK_SELLING_CARD:
        return None
    if _name(joker) == "Campfire":
        ab = _ability(joker)
        ab["x_mult"] = (ab.get("x_mult", 1) or 1) + _val(joker, "extra", 0.25)
    return None


def _reroll_shop(run, joker, ctx: Context):
    if ctx.event != hooks.HOOK_REROLL_SHOP:
        return None
    if _name(joker) == "Flash Card":
        ab = _ability(joker)
        ab["mult"] = ab.get("mult", 0) + _val(joker, "extra", 2)
    return None


def _ending_shop(run, joker, ctx: Context):
    if ctx.event != "ending_shop":
        return None
    if _name(joker) == "Perkeo" and _consumeables(run):
        chosen = _pick(run, "perkeo", _consumeables(run))
        if chosen is not None:
            return _eff(create=[{"kind": "copy_consumeable", "card": chosen,
                                 "count": 1, "negative": True}])
    return None


def _playing_card_added(run, joker, ctx: Context):
    if ctx.event != "playing_card_added":
        return None
    name = _name(joker)
    card = getattr(ctx, "other_card", None)
    cards = ctx.extra.get("cards") or ([card] if card is not None else list(ctx.full_hand))
    if name == "Hologram" and cards:
        ab = _ability(joker)
        ab["x_mult"] = (ab.get("x_mult", 1) or 1) + len(cards) * _val(joker, "extra", 0.25)
    elif name == "Driver's License":
        # card.lua: gains +1 tally per face card added to the deck this run
        ab = _ability(joker)
        ab["driver_tally"] = int(ab.get("driver_tally", 0) or 0) + sum(1 for c in cards if _is_face(c))
    return None


def _first_hand_drawn(run, joker, ctx: Context):
    if ctx.event != "first_hand_drawn":
        return None
    if _name(joker) == "Certificate":
        return _eff(create=[{"kind": "playing_card", "seal_random": True, "count": 1}])
    return None


def _setting_blind(run, joker, ctx: Context):
    if ctx.event != hooks.HOOK_SETTING_BLIND:
        return None
    name = _name(joker)
    if name == "Chicot":
        if _blind_is_boss(run):
            return _eff(disabled_blind=True)
    elif name == "Madness":
        if not _blind_is_boss(run):
            ab = _ability(joker)
            ab["x_mult"] = (ab.get("x_mult", 1) or 1) + _val(joker, "extra", 0.5)
            # eternal jokers are exempt (card.lua:2507)
            others = [j for j in _jokers(run)
                      if j is not joker and not (_ability(j).get("eternal", False))]
            victim = _pick(run, "madness", others)
            if victim is not None:
                return _eff(destroy=True, extra={"destroy_joker": victim})
    elif name == "Burglar":
        extra = _val(joker, "extra", 3)
        ctx.extra["discards_left"] = 0
        ctx.extra["hands_add"] = extra
        return _eff(extra={"hands_add": extra, "discards_left": 0})
    elif name == "Riff-raff":
        free = _joker_slots(run) - len(_jokers(run))
        if free > 0:
            return _eff(create=[{"kind": "Joker", "count": min(2, free)}])
    elif name == "Cartomancer":
        if len(_consumeables(run)) < _consumeable_slots(run):
            return _eff(create=[{"kind": "Tarot", "count": 1}])
    elif name == "Ceremonial Dagger":
        jokers = _jokers(run)
        try:
            me = jokers.index(joker)
        except ValueError:
            me = -1
        if me >= 0 and me + 1 < len(jokers):
            victim = jokers[me + 1]
            ab = _ability(joker)
            ab["mult"] = ab.get("mult", 0) + 2 * _sell_cost(run, victim)
            return _eff(destroy=True, extra={"destroy_joker": victim})
    elif name == "Marble Joker":
        return _eff(create=[{"kind": "stone_card", "count": 1}])
    return None


def _sell_cost(run, card) -> int:
    """Card:set_cost sell_cost (card.lua:382) - the run's canonical value."""
    sell = getattr(run, "sell_value", None)
    if callable(sell):
        return int(sell(card))
    v = getattr(card, "sell_cost", None)
    if isinstance(v, (int, float)):
        return int(v)
    return 1


def _destroying_card(run, joker, ctx: Context):
    if ctx.event != hooks.HOOK_DESTROYING_CARD:
        return None
    if _ctx_blueprint(ctx):
        return None
    if _name(joker) == "Sixth Sense":
        full = _played_cards(ctx)
        if len(full) == 1 and _card_id(full[0]) == 6 and _hands_played(run, ctx) == 0:
            return _eff(create=[{"kind": "Spectral", "count": 1}])
    return None


def _cards_destroyed(run, joker, ctx: Context):
    if ctx.event != "cards_destroyed":
        return None
    if _ctx_blueprint(ctx):
        return None
    name = _name(joker)
    shattered = ctx.extra.get("glass_shattered") or []
    if name == "Caino":
        faces = sum(1 for c in shattered if _is_face(c))
        if faces:
            ab = _ability(joker)
            ab["caino_xmult"] = ab.get("caino_xmult", 1) + faces * _val(joker, "extra", 1)
    elif name == "Glass Joker":
        glasses = sum(1 for c in shattered if getattr(c, "shattered", False))
        if glasses:
            ab = _ability(joker)
            ab["x_mult"] = ab.get("x_mult", 1) + _val(joker, "extra", 0.75) * glasses
    return None


def _remove_playing_cards(run, joker, ctx: Context):
    if ctx.event != "remove_playing_cards":
        return None
    if _ctx_blueprint(ctx):
        return None
    name = _name(joker)
    removed = ctx.extra.get("removed") or []
    if name == "Caino":
        faces = sum(1 for c in removed if _is_face(c))
        if faces:
            ab = _ability(joker)
            ab["caino_xmult"] = ab.get("caino_xmult", 1) + faces * _val(joker, "extra", 1)
    elif name == "Glass Joker":
        glasses = sum(1 for c in removed if getattr(c, "shattered", False))
        if glasses:
            ab = _ability(joker)
            ab["x_mult"] = ab.get("x_mult", 1) + _val(joker, "extra", 0.75) * glasses
    return None


def _using_consumeable(run, joker, ctx: Context):
    # The Lua flag is `using_consumeable`; the core fires `use_consumeable`.
    if ctx.event not in ("using_consumeable", "use_consumeable"):
        return None
    if _ctx_blueprint(ctx):
        return None
    name = _name(joker)
    cons = ctx.consumable
    if name == "Glass Joker":
        if cons is not None and _name(cons) == "The Hanged Man":
            shattered = sum(1 for c in (_run_attr(run, "hand", []) or [])
                            if getattr(c, "enhancement", None) == "m_glass")
            if shattered:
                ab = _ability(joker)
                ab["x_mult"] = ab.get("x_mult", 1) + _val(joker, "extra", 0.75) * shattered
        return None
    if name == "Fortune Teller":
        if cons is not None and _cons_set(cons) == "Tarot":
            return None
        return None
    if name == "Constellation":
        if cons is not None and _cons_set(cons) == "Planet":
            ab = _ability(joker)
            ab["x_mult"] = (ab.get("x_mult", 1) or 1) + _val(joker, "extra", 0.1)
        return None
    return None


def _cons_set(cons) -> str:
    ab = getattr(cons, "ability", None)
    if isinstance(ab, dict) and ab.get("set"):
        return ab["set"]
    center = _centers().get(_key(cons)) or {}
    return center.get("set") or ""


def _debuffed_hand(run, joker, ctx: Context):
    if ctx.event != "debuffed_hand":
        return None
    if _name(joker) == "Matador" and bool(_blind_attr(run, "triggered", False)):
        return _eff(dollars=_val(joker, "extra", 8))
    return None


def _open_booster(run, joker, ctx: Context):
    if ctx.event != "open_booster":
        return None
    if _name(joker) == "Hallucination":
        if len(_consumeables(run)) < _consumeable_slots(run) \
                and _chance(run, "halu" + str(_run_attr(run, "ante", 1)),
                            _val(joker, "extra", 2)):
            return _eff(create=[{"kind": "Tarot", "count": 1}])
    return None


def _other_joker(run, joker, ctx: Context):
    if ctx.event != hooks.HOOK_OTHER_JOKER:
        return None
    other = ctx.other_joker
    if _name(joker) == "Baseball Card" and other is not None and other is not joker:
        if _rarity(other) == 2:
            return _eff(x_mult=_val(joker, "extra", 1.5))
    return None


def _rarity(card) -> int:
    ab = getattr(card, "ability", None)
    if isinstance(ab, dict) and ab.get("rarity") is not None:
        return int(ab["rarity"])
    center = _centers().get(_key(card)) or {}
    return int(center.get("rarity", 1) or 1)


def _skip_blind(run, joker, ctx: Context):
    """Throwback's x_mult is recomputed from the skip count (card.lua:4176)."""
    if ctx.event != "skip_blind":
        return None
    if _name(joker) == "Throwback":
        ab = _ability(joker)
        skips = int(ctx.extra.get("skips") or _cr(run, "skips", 0) or 0)
        ab["x_mult"] = 1 + skips * _val(joker, "extra", 0.25)
    return None


def _plain(run, joker, ctx: Context):
    """Registered, mechanically out of hook scope (economy / pool / UI level)."""
    return None


# ---------------------------------------------------------------------------
# Registry: centre key -> handler(s)
# ---------------------------------------------------------------------------

REGISTRY: dict[str, Callable] = {}
HANDLERS: dict[str, list[Callable]] = {}


def _reg(key: str, fn: Callable):
    """Register a handler; ``REGISTRY`` keeps the first *real* one."""
    HANDLERS.setdefault(key, []).append(fn)
    prev = REGISTRY.get(key)
    if prev is None or prev is _plain:
        REGISTRY[key] = fn


def _score_joker(run, joker, ctx: Context):
    """The Lua ``context.cardarea == G.jokers`` tail (joker_main / before / after).

    The Lua's `if context.joker_main ... elseif context.other_joker ... else ...`
    chain is mutually exclusive: this branch must never fire for the separate
    "joker on joker" pass, so the event is checked.  The ``before`` and
    ``after`` contexts (cardarea == jokers) share the same tail in the Lua, so
    they are admitted here too (the branch bodies key off ``ctx.event``).
    """
    if ctx.event not in (hooks.HOOK_JOKER_MAIN, hooks.HOOK_BEFORE,
                         hooks.HOOK_AFTER):
        return None
    if ctx.other_joker is not None:
        return None
    return _score_branches(run, joker, ctx)


# -- copy jokers: Blueprint (right) / Brainstorm (leftmost) ------------------
for _k in ("j_blueprint", "j_brainstorm"):
    _reg(_k, _copy_handler)

# -- retriggers: repetition pass (Sock and Buskin, Hanging Chad, Hack) ------
for _k in ("j_sock_and_buskin", "j_hanging_chad", "j_hack"):
    _reg(_k, _repetition)

# -- retrigger + teardown (Dusk, Seltzer) and held retrigger (Mime) --------
for _k in ("j_dusk", "j_selzer"):
    _reg(_k, _repetition)
_reg("j_mime", _repetition)

# -- per-card passes -------------------------------------------------------
_INDIVIDUAL_KEYS = (
    # cardarea = play
    "j_hiker", "j_8_ball", "j_scary_face", "j_business",
    "j_walkie_talkie", "j_photograph", "j_wee", "j_smiley", "j_ticket",
    "j_scholar", "j_rough_gem", "j_bloodstone", "j_arrowhead",
    "j_onyx_agate", "j_ancient", "j_idol", "j_triboulet", "j_lucky_cat",
    "j_fibonacci", "j_even_steven", "j_odd_todd",
    # cardarea = hand
    "j_baron", "j_shoot_the_moon", "j_reserved_parking", "j_raised_fist",
)
for _k in _INDIVIDUAL_KEYS:
    _reg(_k, _individual)

# -- discard ---------------------------------------------------------------
for _k in ("j_ramen", "j_yorick", "j_trading", "j_castle", "j_mail",
           "j_hit_the_road", "j_green_joker", "j_faceless"):
    _reg(_k, _discard)
_reg("j_burnt", _pre_discard)
_reg("j_red_card", _skipping_booster)

# -- end of round ----------------------------------------------------------
for _k in ("j_campfire", "j_rocket", "j_turtle_bean", "j_invisible",
           "j_popcorn", "j_todo_list", "j_egg", "j_gift", "j_hit_the_road",
           "j_gros_michel", "j_cavendish", "j_mr_bones"):
    _reg(_k, _end_of_round)

# -- shop / blind setup / destruction --------------------------------------
for _k in ("j_luchador", "j_diet_cola", "j_invisible"):
    _reg(_k, _selling_self)
_reg("j_campfire", _selling_card)
_reg("j_flash", _reroll_shop)
_reg("j_perkeo", _ending_shop)
_reg("j_hologram", _playing_card_added)
_reg("j_certificate", _first_hand_drawn)
for _k in ("j_chicot", "j_madness", "j_burglar", "j_riff_raff",
           "j_cartomancer", "j_ceremonial", "j_marble"):
    _reg(_k, _setting_blind)
_reg("j_sixth_sense", _destroying_card)
for _k in ("j_caino", "j_glass"):
    _reg(_k, _cards_destroyed)
    _reg(_k, _remove_playing_cards)
    _reg(_k, _using_consumeable)
_reg("j_fortune_teller", _using_consumeable)
_reg("j_constellation", _using_consumeable)
_reg("j_matador", _debuffed_hand)
_reg("j_hallucination", _open_booster)
_reg("j_baseball", _other_joker)
_reg("j_throwback", _skip_blind)

# -- the main scoring tail -------------------------------------------------
# Every joker reaches the Lua's ``else`` branch, so all of them register the
# scoring handler; the ones with no ``self.ability.name`` branch inside simply
# return None there.  ``_NO_SCORE_KEYS`` are the jokers whose whole effect lives
# in one of the dedicated passes above (own a handler from those lists, never a
# scoring branch), so registering the tail would be dead weight.
_NO_SCORE_KEYS = frozenset({
    "j_blueprint", "j_brainstorm",           # copy pass
    "j_mime", "j_sock_and_buskin",           # repetition pass
    "j_hanging_chad", "j_hack",
    "j_hiker", "j_8_ball", "j_scary_face", "j_business",
    "j_walkie_talkie", "j_photograph", "j_smiley", "j_ticket",
    "j_scholar", "j_rough_gem", "j_bloodstone", "j_arrowhead",
    "j_onyx_agate", "j_ancient", "j_idol", "j_triboulet", "j_lucky_cat",
    "j_fibonacci", "j_even_steven", "j_odd_todd", "j_baron",
    "j_shoot_the_moon", "j_reserved_parking", "j_raised_fist",
    "j_trading", "j_mail",                       # discard (no scoring branch)
    "j_faceless", "j_burnt",
    "j_egg", "j_gift", "j_turtle_bean",          # end-of-round only
    "j_rocket", "j_invisible", "j_mr_bones",
    "j_diet_cola", "j_luchador", "j_cartomancer",  # setup
    "j_marble", "j_riff_raff", "j_certificate", "j_sixth_sense",
    "j_hallucination",
    "j_four_fingers", "j_shortcut", "j_smeared", "j_pareidolia", "j_oops",
    "j_splash", "j_ring_master", "j_chaos", "j_juggler", "j_drunkard",
    "j_troubadour", "j_merry_andy", "j_showman", "j_astronomer",
    # dollar-bonus-only jokers (card.lua:1655)
    "j_cloud_9", "j_satellite", "j_delayed_grat",
})

# Registered as real handlers but with no context effect: pure run-level
# modifiers (Four Fingers, Smeared Joker, Showman, ...) applied by the engine's
# flag / pool layer, plus the round-end dollar bonus jokers.
MODIFIER_ONLY: frozenset[str] = frozenset({
    "j_four_fingers", "j_shortcut", "j_smeared", "j_pareidolia", "j_oops",
    "j_splash", "j_ring_master", "j_chaos", "j_juggler", "j_drunkard",
    "j_troubadour", "j_merry_andy", "j_showman", "j_astronomer",
    "j_cloud_9", "j_satellite", "j_delayed_grat", "j_golden",
    "j_to_the_moon", "j_burglar", "j_stuntman",
})


def joker_keys() -> set[str]:
    """Every centre key with ``set == "Joker"`` (the coverage target)."""
    return {k for k, v in _centers().items() if (v or {}).get("set") == "Joker"}


JOKER_KEYS: set[str] = joker_keys()

_ALL_KEYS = sorted(JOKER_KEYS)

# Each joker: the main scoring tail (unless its effect lives elsewhere), plus
# the dedicated pass(es) the Lua routes it through.
for _k in _ALL_KEYS:
    _reg(_k, _plain)
    if _k not in _NO_SCORE_KEYS:
        _reg(_k, _score_joker)

# Jokers whose effect is genuinely out of scope for a hook-driven single-player
# text engine (pure UI/animation).  Every key still has a registered handler.
# Currently empty: every one of the 150 joker centres has a mechanical effect.
UNIMPLEMENTED: set[str] = set()

SCORING_KEYS: frozenset[str] = frozenset(JOKER_KEYS - _NO_SCORE_KEYS)


def covered() -> set[str]:
    """Joker keys with at least one registered handler (all 150)."""
    return set(HANDLERS) & joker_keys()


def handlers_for(joker) -> list[Callable]:
    return list(HANDLERS.get(_key(joker), ()))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def calculate(run, joker, ctx: Context) -> Effect | None:
    """Port of ``Card:calculate_joker``.

    ``joker`` is a :class:`~balatro_cli.engine.card.JokerCard` or a bare centre
    key string.  Returns ``None`` when the joker does nothing for this context.
    """
    key = _key(joker)
    if not key:
        return None
    # a debuffed joker does nothing (card.lua:2292)
    if getattr(joker, "debuffed", False) and not isinstance(joker, str):
        return None
    global _CURRENT_FLAGS
    _CURRENT_FLAGS = getattr(run, "joker_flags", None) or _CURRENT_FLAGS
    handlers = HANDLERS.get(key)
    if not handlers:
        return None
    merged: Effect | None = None
    for fn in handlers:
        eff = fn(run, joker, ctx)
        if eff is None:
            continue
        if merged is None:
            merged = eff
        else:
            merged.merge(eff)
    if merged is None or merged.is_empty():
        return None
    return merged


def dollar_bonus(run, joker) -> int:
    """Port of ``Card:calculate_dollar_bonus`` (round-end joker money)."""
    name = _name(joker)
    if getattr(joker, "debuffed", False):
        return 0
    if name == "Golden Joker":
        return int(_val(joker, "extra", 4))
    if name == "Cloud 9":
        tally = _nine_tally(run, joker)
        if tally > 0:
            return int(_val(joker, "extra", 1) * tally)
        return 0
    if name == "Rocket":
        return int(_extra(joker).get("dollars", 1))
    if name == "Satellite":
        usage = _run_attr(run, "consumeable_usage", None)
        planets = 0
        if isinstance(usage, dict):
            for v in usage.values():
                if isinstance(v, dict) and v.get("set") == "Planet":
                    planets += 1
        else:
            planets = _consumeable_usage_total(run, "planet")
        if planets == 0:
            return 0
        return int(_val(joker, "extra", 1) * planets)
    if name == "Delayed Gratification":
        if _cr(run, "discards_used", 0) == 0 and _cr(run, "discards_left", 0) > 0:
            return int(_cr(run, "discards_left", 0) * _val(joker, "extra", 2))
        return 0
    return 0


def joker_flags(run):
    """Four Fingers / Shortcut / Smeared / Pareidolia / Oops! All 6s."""
    flags = _run_attr(run, "joker_flags", None)
    if flags is None:
        from .hand import JokerFlags
        flags = JokerFlags()
        try:
            setattr(run, "joker_flags", flags)
        except Exception:
            pass
    names = {_joker_name(j) for j in _jokers(run)}
    if "Four Fingers" in names:
        flags.four_fingers = True
    if "Shortcut" in names:
        flags.shortcut = True
    if "Smeared Joker" in names:
        flags.smeared = True
    if "Pareidolia" in names and hasattr(flags, "pareidolia"):
        flags.pareidolia = True
    if "Oops! All 6s" in names:
        rng = _rng(run)
        if rng is not None and hasattr(rng, "probabilities_normal"):
            rng.probabilities_normal = 2
        if hasattr(flags, "oops_six"):
            flags.oops_six = True
    return flags


def _joker_name(j) -> str:
    ab = getattr(j, "ability", None)
    if isinstance(ab, dict) and ab.get("name"):
        return ab["name"]
    center = _centers().get(_key(j)) or {}
    return center.get("name") or _key(j)


def has(run, name: str) -> bool:
    """``find_joker(name)`` -- name is the centre *name* (e.g. ``"Mime"``)."""
    return any(_joker_name(j) == name for j in _jokers(run))


def count(run, name: str) -> int:
    """``#find_joker(name)``."""
    return sum(1 for j in _jokers(run) if _joker_name(j) == name)


# Expose the scoring tail for tests/introspection (same signature as calculate).
score_branches = _score_branches
