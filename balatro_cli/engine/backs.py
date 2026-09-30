"""Deck backs - a port of ``back.lua:Back:apply_to_run`` (~174-278) and
``Back:trigger_effect`` (~108-172).

Deck data comes from ``balatro_cli/assets/centers.json`` (the 16 centers with
``set == "Back"``); ``Back:apply_to_run`` reads ``self.effect.config`` which is a
copy of the center's ``config`` table, so ``back_config(deck_key)`` is the single
source of truth here.

Entry points
------------
``setup(run, deck_key, apply=True)``
    Apply a back's *starting* effects (run setup).  Returns
    ``{"deltas", "vouchers", "consumables", "deck", "notes"}``.
``trigger(run, deck_key, context, **kw)``
    ``Back:trigger_effect``: ``'eval'`` (Anaglyph double tag), ``'final_scoring_step'``
    and ``'blind_amount'`` (Plasma).  ``None`` == "no effect", like the Lua.
``describe(deck_key)``
    Plain-text description (markup stripped, ``#1#`` filled).

``config.DECK_DELTAS`` is kept as the (deprecated) param-delta view of the same
data so that ``GameState._apply_deck`` keeps working; :func:`deltas_for` is the
authoritative source and ``DECK_DELTAS`` must stay a superset of it (pinned by
``tests/test_vouchers_backs.py``).  Where both are used for one run they must not
both be applied - pass ``apply=False`` to :func:`setup` if the caller already
folded ``DECK_DELTAS`` into ``run.params``.

Deltas
------
``deltas_for`` maps the Lua ``starting_params`` config onto engine param names::

    hands -> hands        discards -> discards      dollars -> dollars
    hand_size -> hand_size                             (G.GAME.starting_params.hand_size)
    joker_slot -> joker_slots                          (plural: run.params spelling)
    consumable_slot -> consumable_slots
    ante_scaling -> ante_scaling                       (ASSIGNED, not added: back.lua:263)
    reroll_discount -> reroll_cost (negated)

Green Deck's ``extra_hand_bonus`` / ``extra_discard_bonus`` are *not* params: the
Lua writes ``G.GAME.modifiers.money_per_hand`` / ``money_per_discard`` (back.lua:272-277),
so :func:`setup` sets those plus the legacy ``extra_*`` keys in the returned dict.

Documented deviations, all resolved in favour of the Lua:

* ``b_green`` ``extra_discard_bonus`` is **1**, not 2 (``game.lua:631``); the old
  ``config.DECK_DELTAS`` value contradicted the source and was fixed.
* ``b_checkered`` has an empty ``config`` in the source and is driven by the *name*
  (``back.lua:239``), so the 26-card deck is keyed off the center name.
* ``b_abandoned`` sets ``starting_params.no_faces`` which ``game.lua:2355`` turns
  into a 40-card deck (all 13 ranks minus J/Q/K, x4 suits).
* ``b_erratic`` sets ``starting_params.erratic_suits_and_ranks``; ``game.lua:2342``
  then picks a random ``G.P_CARDS`` entry *per card*, so ranks/suits are i.i.d.
  (duplicates possible), not a permutation.  We mirror that with the run RNG's
  ``'erratic'`` stream.
* Deck lists are only built for Checkered / Abandoned / Erratic; every other back
  uses the standard 52-card deck (``deck`` is ``None`` == "leave the deck alone").
"""

from __future__ import annotations

import math
import re

from .. import config
from ..data import loader
from . import vouchers
from .card import Card
from .deck import RANKS, SUITS, build_standard_deck

BACK_SET = "Back"

# Lua starting_params key -> engine param key (order == back.lua:181-214).
_PARAM_KEYS: tuple[tuple[str, str], ...] = (
    ("hands", "hands"),
    ("discards", "discards"),
    ("dollars", "dollars"),
    ("hand_size", "hand_size"),
    ("joker_slot", "joker_slots"),
    ("consumable_slot", "consumable_slots"),
    ("ante_scaling", "ante_scaling"),
    ("reroll_discount", "reroll_cost"),
)

# Keys the Lua *assigns* instead of adding (back.lua:263).
ABSOLUTE_KEYS = frozenset({"ante_scaling"})

# non-param config keys that describe the deck itself
DECK_CONFIG_KEYS = ("voucher", "vouchers", "consumables", "spectral_rate",
                    "remove_faces", "randomize_rank_suit")

_MARKUP = re.compile(r"\{[^{}]*\}")
_PLACEHOLDER = re.compile(r"#(\d+)#")


# ---------------------------------------------------------------------------
# data helpers
# ---------------------------------------------------------------------------

def back_keys() -> list[str]:
    """Every ``set == "Back"`` center key, in ``order`` order (16 keys)."""
    centers = loader.centers()
    keys = [k for k, c in centers.items()
            if isinstance(c, dict) and c.get("set") == BACK_SET]
    return sorted(keys, key=lambda k: (centers[k].get("order") is None,
                                       centers[k].get("order", 0), k))


def center(deck_key: str) -> dict:
    c = loader.centers().get(deck_key)
    return c if isinstance(c, dict) else {}


def name_of(deck_key: str) -> str:
    return center(deck_key).get("name") or deck_key


def back_config(deck_key: str) -> dict:
    """The Lua ``self.effect.config`` table for ``deck_key``."""
    return dict(center(deck_key).get("config") or {})


def deltas_for(deck_key: str) -> dict:
    """Param deltas this back applies at run start (see the module docstring)."""
    cfg = back_config(deck_key)
    out: dict = {}
    for lua_key, engine_key in _PARAM_KEYS:
        if lua_key not in cfg:
            continue
        value = cfg[lua_key]
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        out[engine_key] = -value if lua_key == "reroll_discount" else value
    if cfg.get("no_interest"):
        out["no_interest"] = True
    for key in ("extra_hand_bonus", "extra_discard_bonus"):
        if key in cfg:
            out[key] = cfg[key]
    return out


def fmt_number(value) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------

def setup(run, deck_key: str, apply: bool = True) -> dict:
    """Apply a deck back's starting effects to a fresh run.

    Returns ``{"deltas": {...}, "vouchers": [...], "consumables": [...],
    "deck": list[Card] | None, "notes": [...]}``.  ``deck`` is always computed
    (Errantic consumes the run RNG); ``apply=False`` skips mutating the run.
    """
    cfg = back_config(deck_key)
    name = name_of(deck_key)
    deltas = deltas_for(deck_key)
    granted: list[str] = []
    if cfg.get("voucher"):
        granted.append(cfg["voucher"])
    granted.extend(cfg.get("vouchers") or [])
    consumables = list(cfg.get("consumables") or [])
    notes: list[str] = []
    deck = _deck_for(run, name, cfg, notes)

    if not apply:
        return {"deltas": deltas, "vouchers": granted, "consumables": consumables,
                "deck": deck, "notes": notes}

    _apply_deltas(run, deltas)
    _apply_modifiers(run, cfg)
    if any(key in deltas for key in ("hands", "discards", "dollars", "hand_size",
                                     "joker_slots", "consumable_slots", "ante_scaling")):
        notes.append("starting params: " + ", ".join(
            f"{k}{v:+d}" if isinstance(v, int) and not isinstance(v, bool) else f"{k}={v}"
            for k, v in deltas.items()
            if k in ("hands", "discards", "dollars", "hand_size", "joker_slots",
                     "consumable_slots", "ante_scaling")))
    if cfg.get("no_interest"):
        notes.append("no interest earned at end of round")
    if "extra_hand_bonus" in cfg:
        notes.append(f"${fmt_number(cfg['extra_hand_bonus'])} per remaining hand at round end")
    if "extra_discard_bonus" in cfg:
        notes.append(f"${fmt_number(cfg['extra_discard_bonus'])} per remaining discard at round end")
    if cfg.get("spectral_rate"):
        run.spectral_rate = cfg["spectral_rate"]
        notes.append(f"shop spectral rate x{fmt_number(cfg['spectral_rate'])}")

    for key in granted:
        result = vouchers.redeem(run, key)
        if result.get("ok"):
            notes.append(f"starting voucher {key} ({vouchers.name_of(key)})")
        else:
            notes.append(f"starting voucher {key} not applied: {result.get('error')}")

    for key in consumables:
        if _add_consumable(run, key):
            notes.append(f"starting consumable {key}")

    if deck is not None:
        run.deck = deck
    return {"deltas": deltas, "vouchers": granted, "consumables": consumables,
            "deck": deck, "notes": notes}


def _apply_deltas(run, deltas: dict) -> None:
    if getattr(run, "params", None) is None:
        run.params = dict(config.STARTING_PARAMS)
    for key, value in deltas.items():
        if key == "no_interest":
            run.params["no_interest"] = value
        elif key in ("extra_hand_bonus", "extra_discard_bonus"):
            continue          # -> run.modifiers, see _apply_modifiers
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            if key in ABSOLUTE_KEYS:                       # back.lua:263 assigns
                run.params[key] = value
                # ante_scaling multiplies blind chips (Plasma); it must not
                # touch run.scaling, which selects the blind-amount table
                if hasattr(run, "ante_scaling"):
                    run.ante_scaling = value
            else:
                run.params[key] = run.params.get(key, 0) + value
            if key == "hand_size" and hasattr(run, "hand_size"):
                run.hand_size = int(run.params["hand_size"])
            if key == "dollars" and hasattr(run, "dollars"):
                run.dollars = int(run.params["dollars"])


def _apply_modifiers(run, cfg: dict) -> None:
    if getattr(run, "modifiers", None) is None:
        run.modifiers = {}
    if cfg.get("no_interest"):
        run.modifiers["no_interest"] = True
    if "extra_hand_bonus" in cfg:
        run.modifiers["money_per_hand"] = cfg["extra_hand_bonus"]
    if "extra_discard_bonus" in cfg:
        run.modifiers["money_per_discard"] = cfg["extra_discard_bonus"]


def _add_consumable(run, key: str) -> bool:
    fn = getattr(run, "add_consumable", None)
    if fn is not None:
        fn(key)
        return True
    slots = getattr(run, "consumeables", None)
    if isinstance(slots, list):
        slots.append(key)
        return True
    return False


def _deck_for(run, name: str, cfg: dict, notes: list[str]) -> list[Card] | None:
    if name == "Checkered Deck":                            # back.lua:239
        deck = [Card(rank, suit) for rank in RANKS for suit in ("S", "H")]
        notes.append(f"deck: {len(deck)} cards (Spades + Hearts only)")
        return deck
    if cfg.get("remove_faces") or name == "Abandoned Deck":  # back.lua:202
        deck = build_standard_deck(no_faces=True)
        notes.append(f"deck: {len(deck)} cards (no face cards)")
        return deck
    if cfg.get("randomize_rank_suit"):                       # back.lua:254 + game.lua:2342
        rng = getattr(run, "rng", None)
        if rng is None:
            notes.append("deck: randomize_rank_suit set but the run has no rng; deck left standard")
            return None
        base = build_standard_deck()
        combos = [(rank, suit) for rank in RANKS for suit in SUITS]   # G.P_CARDS
        deck = []
        for _ in base:
            rank, suit = rng.pick("erratic", combos)
            deck.append(Card(rank, suit))
        notes.append(f"deck: {len(deck)} cards, every rank/suit randomized (pseudoseed 'erratic')")
        return deck
    return None


# ---------------------------------------------------------------------------
# trigger_effect
# ---------------------------------------------------------------------------

def trigger(run, deck_key: str, context: str, **kwargs) -> dict | None:
    """``Back:trigger_effect``.  ``None`` means "no effect", exactly like the Lua."""
    name = name_of(deck_key)

    if name == "Anaglyph Deck" and context == "eval":        # back.lua:111
        if not _last_blind_was_boss(run):
            return None
        add_tag = getattr(run, "add_tag", None)
        if add_tag is not None:
            add_tag("tag_double")
        else:
            tags = getattr(run, "tags", None)
            if isinstance(tags, list):
                tags.append("tag_double")
        return {"context": "eval", "tags": ["tag_double"],
                "notes": ["Anaglyph Deck: boss blind defeated, gained a Double Tag"]}

    if name == "Plasma Deck":                                # back.lua:121 / 125
        if context == "blind_amount":
            # The Lua returns nothing here: the X2 comes from
            # starting_params.ante_scaling (back.lua:263), not from a hook.
            return None
        if context == "final_scoring_step":
            chips = kwargs.get("chips", 0) or 0
            mult = kwargs.get("mult", 0) or 0
            half = math.floor((chips + mult) / 2)
            return {"context": "final_scoring_step", "chips": half, "mult": half,
                    "balanced": chips + mult,
                    "notes": [f"Plasma Deck: chips/mult balanced to {half}/{half}"]}

    return None


def _last_blind_was_boss(run) -> bool:
    blind = getattr(run, "last_blind", None)
    if blind is None:
        blind = getattr(run, "the_blind", None)
    if blind is None:
        return False
    if isinstance(blind, dict):
        return bool(blind.get("boss") or blind.get("is_boss"))
    return bool(getattr(blind, "is_boss", False) or getattr(blind, "boss", False))


# ---------------------------------------------------------------------------
# descriptions
# ---------------------------------------------------------------------------

def _loc_text(deck_key: str) -> str:
    try:
        loc = loader.localization("en-us")
    except Exception:  # assets missing
        return ""
    entry = ((loc.get("descriptions") or {}).get(BACK_SET) or {}).get(deck_key) or {}
    lines = entry.get("text") or []
    if not lines:
        return ""
    return " ".join(_MARKUP.sub("", str(line)) for line in lines).strip()


def _center_name(key: str) -> str:
    return center(key).get("name") or key


def _tag_name(key: str) -> str:
    try:
        loc = loader.localization("en-us")
        entry = ((loc.get("descriptions") or {}).get("Tag") or {}).get(key) or {}
        return entry.get("name") or key
    except Exception:
        return key


def _desc_args(name: str, cfg: dict) -> list[str]:
    if name == "Red Deck":
        return [fmt_number(cfg.get("discards", 1))]
    if name == "Blue Deck":
        return [fmt_number(cfg.get("hands", 1))]
    if name == "Yellow Deck":
        return [fmt_number(cfg.get("dollars", 10))]
    if name == "Green Deck":
        return [fmt_number(cfg.get("extra_hand_bonus", 2)),
                fmt_number(cfg.get("extra_discard_bonus", 1))]
    if name == "Black Deck":
        return [fmt_number(cfg.get("joker_slot", 1)),
                fmt_number(-(cfg.get("hands", -1)))]
    if name == "Magic Deck":
        return [_center_name(cfg.get("voucher", "v_crystal_ball")),
                _center_name((cfg.get("consumables") or ["c_fool"])[0])]
    if name == "Nebula Deck":
        return [_center_name(cfg.get("voucher", "v_telescope")),
                fmt_number(cfg.get("consumable_slot", -1))]
    if name == "Zodiac Deck":
        return [_center_name(k) for k in (cfg.get("vouchers") or [])]
    if name == "Painted Deck":
        return [fmt_number(cfg.get("hand_size", 2)), fmt_number(cfg.get("joker_slot", -1))]
    if name == "Anaglyph Deck":
        return [_tag_name("tag_double")]
    if name == "Plasma Deck":
        return [fmt_number(cfg.get("ante_scaling", 2))]
    return []


def describe(deck_key: str) -> str:
    """Plain-text description of ``deck_key`` ('' for a non-Back key)."""
    c = center(deck_key)
    if c.get("set") != BACK_SET:
        return ""
    text = _loc_text(deck_key)
    if not text:
        return ""
    args = _desc_args(c.get("name") or deck_key, back_config(deck_key))

    def _sub(match: re.Match) -> str:
        idx = int(match.group(1)) - 1
        return args[idx] if 0 <= idx < len(args) else match.group(0)

    return re.sub(r"\s+", " ", _PLACEHOLDER.sub(_sub, text)).strip()
