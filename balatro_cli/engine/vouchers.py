"""Voucher effects - a port of ``card.lua:Card:redeem`` (~1813) + ``Card:apply_to_run`` (~1880-1971).

Voucher *data* lives in ``balatro_cli/assets/centers.json`` (the 32 centers with
``set == "Voucher"``); the ``requires`` list mirrors ``G.P_CENTERS[key].requires``
and gates what the shop pool may offer (``common_events.lua:get_current_pool``).

Entry points
------------
``redeem(run, key)``
    Apply a voucher's permanent effect (Lua ``Card:apply_to_run``).  It does *not*
    charge money - ``Card:redeem`` does ``ease_dollars(-self.cost)`` after the shop
    already collected payment, and back-granted vouchers (Magic/Nebula/Zodiac
    decks) are free, so the cost stays with the shop/``backs.py`` caller.
``can_redeem(run, key)``
    ``False`` for unknown keys, already-redeemed vouchers and unmet ``requires``.
``describe(key)``
    Plain-text (markup-stripped, ``#1#``-filled) English description.
``hook(run, event, ...)``
    The one voucher that scores: Observatory (``card.lua:2293-2301``).

Run-attribute mapping (Lua -> CLI)
----------------------------------
======================  ==========================================================
``card.lua`` / ``G.GAME``                     CLI run attribute
======================  ==========================================================
``G.GAME.used_vouchers``                      ``run.used_vouchers`` (set) + ``run.vouchers`` (list)
``change_shop_size(1)`` (1887)                ``run.shop_size`` (+1; default 2, ``game.lua:1984``)
``G.GAME.tarot_rate`` (1892)                  ``run.tarot_rate`` (multiplier over the base
                                              weight 4; ``run.tarot_rate == 2`` means the shop
                                              rolls tarots 2x as often)
``G.GAME.planet_rate`` (1897)                 ``run.planet_rate`` (same convention)
``G.GAME.edition_rate`` (1902)                ``run.edition_rate``
``G.GAME.playing_card_rate`` (1907)           ``run.playing_card_rate``
``G.GAME.discount_percent`` (1919)            ``run.discount_percent``
``G.consumeables.config.card_limit`` (1914)   ``run.params["consumable_slots"]``
``G.GAME.round_resets.reroll_cost`` (1927)    ``run.params["reroll_cost"]``, ``run.reroll_cost_delta``,
                                              ``run.reroll_cost`` (when the run has one)
``G.GAME.interest_cap`` (1933)                ``run.interest_cap`` (``//5 * interest_amount`` ==
                                              max $ per round -> ``run.interest_max``)
``G.GAME.round_resets.hands`` (1937)          ``run.params["hands"]``
``G.hand:change_size(1)`` (1941)              ``run.hand_size``   (Paint Brush *and* Palette)
``G.GAME.round_resets.discards`` (1944)       ``run.params["discards"]``
``G.jokers.config.card_limit`` (1953)         ``run.params["joker_slots"]``
``G.GAME.round_resets.ante`` (1958)           ``run.ante``, ``run.blind_ante``
``G.GAME.round_resets.blind_ante`` (1959)     ``run.blind_ante``
Observatory (2295)                            ``run.observatory_x_mult``
Omen Globe (1731)                             ``run.spectral_in_arcana``, ``run.omen_globe_rate``
Telescope (1737)                              ``run.telescope``
Director's Cut / Retcon (2786)                ``run.boss_reroll_limit`` (1, or ``-1`` == unlimited),
                                              ``run.boss_reroll_cost``, ``run.boss_rerolled``
Free rerolls (``current_round.free_rerolls``) ``run.free_rerolls`` (no voucher sets it in v1;
                                              Chaos the Clown does - kept here for symmetry)
======================  ==========================================================

Documented deviations from the task brief, all resolved in favour of the Lua:

* ``v_palette`` is **+1 hand size**, not -1: ``card.lua:1940`` groups
  ``'Paint Brush' or 'Palette'`` and both call ``G.hand:change_size(1)``; the
  localization (``v_palette``) also reads ``+#1# hand size``.
* ``v_seed_money`` / ``v_money_tree`` set ``G.GAME.interest_cap`` to the config
  ``extra`` (50 / 100), which is a **max of $10 / $20** per round because
  interest is ``min(dollars//5, cap//5) * interest_amount``.
* ``v_tarot_merchant`` / ``v_tarot_tycoon``: vanilla sets
  ``G.GAME.tarot_rate = 4 * config.extra`` with ``config.extra = 9.6/4`` / ``32/4``
  (``game.lua:600,617``), i.e. 9.6 / 32 against a base weight of 4 - a *2.4x* /
  *8x* weight while the card advertises ``extra_disp`` 2X / 4X.  We store the
  advertised multiplier in ``run.tarot_rate`` / ``run.planet_rate`` (base weight
  4 -> ``4 * run.tarot_rate``) because that is the documented attribute the shop
  consumes.
* No voucher in the source adds a *voucher* slot, so ``run.shop_extra_vouchers``
  is seeded to 0 purely as the documented knob for the shop's voucher column.
"""

from __future__ import annotations

import re

from .. import config
from ..data import loader
from .hooks import HOOK_JOKER_MAIN, Effect

VOUCHER_SET = "Voucher"

# ``G.GAME`` defaults this module lazily seeds onto the run (game.lua:1885-1910).
# Anything already set on the run wins - vouchers only ever adjust them.
DEFAULT_RUN_ATTRS: dict[str, object] = {
    "shop_size": 2,             # G.GAME.shop.joker_max (game.lua:1984)
    "shop_extra_vouchers": 0,   # voucher column of the shop (no voucher touches it)
    "discount_percent": 0,
    "edition_rate": 1,
    "tarot_rate": 1,            # multiplier over the base shop weight (see docstring)
    "planet_rate": 1,
    "playing_card_rate": 0,
    "spectral_rate": 0,
    "interest_cap": config.INTEREST_CAP,
    "interest_amount": config.INTEREST_AMOUNT,
    "reroll_cost_delta": 0,
    "free_rerolls": 0,
    "boss_reroll_limit": 0,     # 0 = none, 1 = Director's Cut, -1 = unlimited (Retcon)
    "boss_reroll_cost": 0,
    "boss_rerolled": False,
    "telescope": False,
    "spectral_in_arcana": False,
    "omen_globe_rate": 0.0,
    "observatory_x_mult": 1.0,
    "illusion_editions": False,
}

# Base shop weight for tarot/planet rolls (game.lua:1902-1903).
BASE_TAROT_WEIGHT = 4
BASE_PLANET_WEIGHT = 4

# Chance that an Arcana Pack slot holds a Spectral instead of a Tarot
# (card.lua:1731 ``pseudorandom('omen_globe') > 0.8``).
OMEN_GLOBE_RATE = 0.2

# -- what each voucher does, for the transcript ------------------------------
VOUCHER_EFFECTS: dict[str, str] = {
    "v_overstock_norm": "+1 card slot in the shop",
    "v_overstock_plus": "+1 card slot in the shop (stacks with Overstock)",
    "v_clearance_sale": "all shop cards and packs are 25% off",
    "v_liquidation": "all shop cards and packs are 50% off",
    "v_hone": "Foil/Holographic/Polychrome editions appear 2X more often",
    "v_glow_up": "Foil/Holographic/Polychrome editions appear 4X more often",
    "v_reroll_surplus": "rerolls cost $2 less",
    "v_reroll_glut": "rerolls cost $2 less (stacks with Reroll Surplus)",
    "v_crystal_ball": "+1 consumable slot",
    "v_omen_globe": "Spectral cards may appear in Arcana Packs",
    "v_telescope": "Celestial Packs always contain your most played hand's Planet",
    "v_observatory": "held Planet cards give X1.5 Mult to their poker hand",
    "v_grabber": "+1 hand per round",
    "v_nacho_tong": "+1 hand per round (stacks with Grabber)",
    "v_wasteful": "+1 discard per round",
    "v_recyclomancy": "+1 discard per round (stacks with Wasteful)",
    "v_tarot_merchant": "Tarot cards appear 2X more often in the shop",
    "v_tarot_tycoon": "Tarot cards appear 4X more often in the shop",
    "v_planet_merchant": "Planet cards appear 2X more often in the shop",
    "v_planet_tycoon": "Planet cards appear 4X more often in the shop",
    "v_seed_money": "interest cap raised to $50 held => max $10 per round",
    "v_money_tree": "interest cap raised to $100 held => max $20 per round",
    "v_blank": "does nothing",
    "v_antimatter": "+1 Joker slot",
    "v_magic_trick": "playing cards can be purchased from the shop",
    "v_illusion": "shop playing cards may have an Enhancement, Edition and/or Seal",
    "v_hieroglyph": "-1 Ante, -1 hand each round",
    "v_petroglyph": "-1 Ante, -1 discard each round",
    "v_directors_cut": "reroll the Boss Blind once per Ante, $10 per roll",
    "v_retcon": "reroll the Boss Blind unlimited times, $10 per roll",
    "v_paint_brush": "+1 hand size",
    "v_palette": "+1 hand size",
}

# Vouchers that change what the shop offers or what it charges, and the run
# attribute each one writes.  (Everything else is deck/pack/scoring state.)
SHOP_EFFECTS: dict[str, str] = {
    "v_overstock_norm": "run.shop_size += 1",
    "v_overstock_plus": "run.shop_size += 1",
    "v_clearance_sale": "run.discount_percent = 25",
    "v_liquidation": "run.discount_percent = 50",
    "v_tarot_merchant": "run.tarot_rate = 2",
    "v_tarot_tycoon": "run.tarot_rate = 4",
    "v_planet_merchant": "run.planet_rate = 2",
    "v_planet_tycoon": "run.planet_rate = 4",
    "v_magic_trick": "run.playing_card_rate = 4",
    "v_illusion": "run.playing_card_rate = 4, run.illusion_editions = True",
    "v_omen_globe": "run.spectral_in_arcana = True, run.omen_globe_rate = 0.2",
}

# config field + transform used to fill the localization '#1#' placeholders.
_LOC_ARG: dict[str, tuple[str, str]] = {
    "v_clearance_sale": ("extra", "plain"),
    "v_liquidation": ("extra", "plain"),
    "v_hone": ("extra", "plain"),
    "v_glow_up": ("extra", "plain"),
    "v_reroll_surplus": ("extra", "plain"),
    "v_reroll_glut": ("extra", "plain"),
    "v_grabber": ("extra", "plain"),
    "v_nacho_tong": ("extra", "plain"),
    "v_wasteful": ("extra", "plain"),
    "v_recyclomancy": ("extra", "plain"),
    "v_paint_brush": ("extra", "plain"),
    "v_palette": ("extra", "plain"),
    "v_hieroglyph": ("extra", "plain"),
    "v_petroglyph": ("extra", "plain"),
    "v_directors_cut": ("extra", "plain"),
    "v_retcon": ("extra", "plain"),
    "v_observatory": ("extra", "plain"),
    "v_seed_money": ("extra", "interest"),
    "v_money_tree": ("extra", "interest"),
    "v_tarot_merchant": ("extra_disp", "plain"),
    "v_tarot_tycoon": ("extra_disp", "plain"),
    "v_planet_merchant": ("extra_disp", "plain"),
    "v_planet_tycoon": ("extra_disp", "plain"),
}

_MARKUP = re.compile(r"\{[^{}]*\}")
_PLACEHOLDER = re.compile(r"#(\d+)#")


# ---------------------------------------------------------------------------
# data helpers
# ---------------------------------------------------------------------------

def voucher_keys() -> list[str]:
    """Every ``set == "Voucher"`` center key, in ``order`` order (32 keys)."""
    centers = loader.centers()
    keys = [k for k, c in centers.items()
            if isinstance(c, dict) and c.get("set") == VOUCHER_SET]
    return sorted(keys, key=lambda k: (centers[k].get("order") is None,
                                       centers[k].get("order", 0), k))


def center(key: str) -> dict:
    """The raw centers.json entry for ``key`` (``{}`` when unknown)."""
    c = loader.centers().get(key)
    return c if isinstance(c, dict) else {}


def voucher_config(key: str) -> dict:
    return dict(center(key).get("config") or {})


def name_of(key: str) -> str:
    return center(key).get("name") or key


def fmt_number(value) -> str:
    """``2.0 -> '2'``, ``1.5 -> '1.5'``."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _interest_max(run) -> int:
    cap = int(getattr(run, "interest_cap", config.INTEREST_CAP) or 0)
    amount = int(getattr(run, "interest_amount", config.INTEREST_AMOUNT) or 0)
    return (cap // 5) * amount


def _ensure(run) -> None:
    """Seed the G.GAME defaults this module reads/writes (never overwrite)."""
    for attr, value in DEFAULT_RUN_ATTRS.items():
        if getattr(run, attr, None) is None:
            setattr(run, attr, value)
    if getattr(run, "params", None) is None:
        run.params = dict(config.STARTING_PARAMS)
    for key, value in config.STARTING_PARAMS.items():
        run.params.setdefault(key, value)
    if getattr(run, "modifiers", None) is None:
        run.modifiers = {}
    if getattr(run, "used_vouchers", None) is None:
        run.used_vouchers = set()
    if getattr(run, "vouchers", None) is None:
        run.vouchers = []
    if getattr(run, "current_round", None) is None:
        run.current_round = {}
    run.current_round.setdefault("free_rerolls", getattr(run, "free_rerolls", 0))
    if getattr(run, "interest_max", None) is None:
        run.interest_max = _interest_max(run)
    if not hasattr(run, "ante"):
        run.ante = 1


def _used(run) -> set[str]:
    used = getattr(run, "used_vouchers", None)
    keyset = set(used) if used else set()
    listed = getattr(run, "vouchers", None)
    if listed:
        keyset.update(listed)
    return keyset


def is_redeemed(run, key: str) -> bool:
    return key in _used(run)


def _mark_used(run, key: str) -> None:
    if getattr(run, "used_vouchers", None) is None:
        run.used_vouchers = set()
    run.used_vouchers.add(key)
    if isinstance(getattr(run, "vouchers", None), list) and key not in run.vouchers:
        run.vouchers.append(key)


# ---------------------------------------------------------------------------
# the actual effects (mirrors Card:apply_to_run branch for branch)
# ---------------------------------------------------------------------------

def _apply_effect(run, key: str, cfg: dict, name: str) -> list[str]:
    """Mutate the run for ``key`` and return transcript-ready effect strings."""
    extra = cfg.get("extra")
    out: list[str] = []

    if name in ("Overstock", "Overstock Plus"):                 # card.lua:1885
        run.shop_size = int(run.shop_size) + 1
        out.append(f"shop card slots +1 (now {run.shop_size})")

    elif name in ("Tarot Merchant", "Tarot Tycoon"):            # card.lua:1890
        # Lua-real: G.GAME.tarot_rate = 4 * config.extra (2.4 / 8); the shop
        # multiplies its base weight of 4 by this, giving 9.6 / 32
        run.tarot_rate = cfg.get("extra") or 1
        out.append(f"tarot shop rate x{fmt_number(BASE_TAROT_WEIGHT * run.tarot_rate)} "
                   f"(base weight {BASE_TAROT_WEIGHT} -> {fmt_number(BASE_TAROT_WEIGHT * run.tarot_rate)})")

    elif name in ("Planet Merchant", "Planet Tycoon"):          # card.lua:1895
        run.planet_rate = cfg.get("extra") or 1
        out.append(f"planet shop rate x{fmt_number(BASE_PLANET_WEIGHT * run.planet_rate)} "
                   f"(base weight {BASE_PLANET_WEIGHT} -> {fmt_number(BASE_PLANET_WEIGHT * run.planet_rate)})")

    elif name in ("Hone", "Glow Up"):                           # card.lua:1900
        run.edition_rate = extra
        out.append(f"edition_rate x{fmt_number(extra)} (Foil/Holographic/Polychrome)")

    elif name in ("Magic Trick", "Illusion"):                   # card.lua:1905
        run.playing_card_rate = extra
        out.append(f"playing_card_rate {fmt_number(extra)} (playing cards in the shop)")
        if name == "Illusion":
            run.illusion_editions = True
            out.append("shop playing cards may roll Enhancement/Edition/Seal")

    elif name == "Telescope":                                   # card.lua:1737
        run.telescope = True
        out.append("Celestial Packs always contain the most played hand's Planet")

    elif name == "Observatory":                                 # card.lua:2295
        run.observatory_x_mult = float(extra or 1.5)
        out.append(f"held Planet cards give X{fmt_number(run.observatory_x_mult)} Mult "
                   "to their poker hand")

    elif name == "Omen Globe":                                  # card.lua:1731
        run.spectral_in_arcana = True
        run.omen_globe_rate = OMEN_GLOBE_RATE
        out.append(f"Arcana Packs: {fmt_number(OMEN_GLOBE_RATE * 100)}% chance per slot to "
                   "hold a Spectral instead of a Tarot")

    elif name == "Crystal Ball":                                # card.lua:1912
        run.params["consumable_slots"] = int(run.params.get("consumable_slots", 0)) + 1
        out.append(f"consumable slots +1 (now {run.params['consumable_slots']})")

    elif name in ("Clearance Sale", "Liquidation"):             # card.lua:1917
        run.discount_percent = extra
        out.append(f"shop prices -{fmt_number(extra)}%")

    elif name in ("Reroll Surplus", "Reroll Glut"):             # card.lua:1925
        step = int(extra or 0)
        run.reroll_cost_delta = int(run.reroll_cost_delta) - step
        run.params["reroll_cost"] = max(
            0, int(run.params.get("reroll_cost", config.STARTING_PARAMS["reroll_cost"])) - step)
        if getattr(run, "reroll_cost", None) is not None:
            run.reroll_cost = max(0, int(run.reroll_cost) - step)
        out.append(f"reroll cost -${step} (base ${run.params['reroll_cost']})")

    elif name in ("Seed Money", "Money Tree"):                  # card.lua:1931
        run.interest_cap = extra
        run.interest_max = _interest_max(run)
        out.append(f"interest cap ${fmt_number(extra)} held => max ${run.interest_max} per round")

    elif name in ("Grabber", "Nacho Tong"):                     # card.lua:1936
        run.params["hands"] = int(run.params.get("hands", 0)) + int(extra or 1)
        out.append(f"+{fmt_number(extra or 1)} hand per round (now {run.params['hands']})")

    elif name in ("Wasteful", "Recyclomancy"):                  # card.lua:1943
        run.params["discards"] = int(run.params.get("discards", 0)) + int(extra or 1)
        out.append(f"+{fmt_number(extra or 1)} discard per round (now {run.params['discards']})")

    elif name in ("Paint Brush", "Palette"):                    # card.lua:1940
        run.hand_size = int(run.hand_size) + 1
        out.append(f"hand size +1 (now {run.hand_size})")

    elif name == "Blank":                                       # card.lua:1947
        out.append("no effect (Blank)")

    elif name == "Antimatter":                                  # card.lua:1950
        run.params["joker_slots"] = int(run.params.get("joker_slots", 0)) + 1
        out.append(f"Joker slots +1 (now {run.params['joker_slots']})")

    elif name in ("Hieroglyph", "Petroglyph"):                  # card.lua:1957
        step = int(extra or 1)
        run.ante = int(run.ante) - step
        # Lua order: ease_ante() runs first, so the *first* redeem initialises
        # blind_ante from the already-decremented ante (card.lua:1958-1960).
        prev = getattr(run, "blind_ante", None)
        run.blind_ante = (int(prev) if prev is not None else int(run.ante)) - step
        out.append(f"ante -{step} (now {run.ante})")
        if name == "Hieroglyph":
            run.params["hands"] = int(run.params.get("hands", 0)) - step
            out.append(f"hands per round -{step} (now {run.params['hands']})")
        else:
            run.params["discards"] = int(run.params.get("discards", 0)) - step
            out.append(f"discards per round -{step} (now {run.params['discards']})")

    elif name == "Director's Cut":                              # button_callbacks.lua:2786
        run.boss_reroll_limit = 1
        run.boss_reroll_cost = int(extra or 10)
        run.boss_rerolled = False
        out.append(f"reroll the Boss Blind 1x per Ante (${run.boss_reroll_cost} per roll)")

    elif name == "Retcon":
        run.boss_reroll_limit = -1
        run.boss_reroll_cost = int(extra or 10)
        run.boss_rerolled = False
        out.append(f"reroll the Boss Blind unlimited times (${run.boss_reroll_cost} per roll)")

    else:                                                       # pragma: no cover
        out.append("no effect (unported)")

    return out


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def can_redeem(run, key: str) -> bool:
    """True when ``key`` is a voucher this run may still redeem (honours ``requires``)."""
    c = center(key)
    if c.get("set") != VOUCHER_SET:
        return False
    used = _used(run)
    if key in used:
        return False
    return all(req in used for req in (c.get("requires") or []))


def redeem(run, key: str) -> dict:
    """Apply a voucher's permanent effect to the run.

    Returns ``{"ok": True, "key": key, "effects": [str, ...]}`` or
    ``{"ok": False, "key": key, "error": "..."}``.  Money is *not* spent here
    (see the module docstring).
    """
    c = center(key)
    if c.get("set") != VOUCHER_SET:
        return {"ok": False, "key": key, "error": f"unknown voucher {key!r}"}
    _ensure(run)
    used = _used(run)
    if key in used:
        return {"ok": False, "key": key, "error": "already redeemed"}
    missing = [req for req in (c.get("requires") or []) if req not in used]
    if missing:
        return {"ok": False, "key": key,
                "error": "missing prerequisite: " + ", ".join(missing)}
    effects = _apply_effect(run, key, voucher_config(key), c.get("name") or key)
    _mark_used(run, key)
    return {"ok": True, "key": key, "effects": effects}


# -- scoring hook -----------------------------------------------------------

def _ability(card) -> dict:
    if isinstance(card, str):
        return voucher_config(card) | {"set": center(card).get("set")}
    return dict(getattr(card, "ability", None) or {})


def consumable_hand_type(card) -> str | None:
    """``hand_type`` of a Planet consumable (key, JokerCard or ability dict)."""
    if isinstance(card, dict):
        return card.get("hand_type")
    return _ability(card).get("hand_type")


def consumable_set(card) -> str | None:
    if isinstance(card, dict):
        return card.get("set")
    if isinstance(card, str):
        return center(card).get("set")
    ab = _ability(card)
    return ab.get("set") or (center(getattr(card, "key", "") or "").get("set"))


def hook(run, event: str, *, consumable=None, scoring_name: str | None = None, **_):
    """Voucher ``calculate_joker`` hook.  Only Observatory scores (card.lua:2293)."""
    if event == HOOK_JOKER_MAIN and consumable is not None and run is not None:
        if is_redeemed(run, "v_observatory") and consumable_set(consumable) == "Planet":
            if consumable_hand_type(consumable) and consumable_hand_type(consumable) == scoring_name:
                x = float(getattr(run, "observatory_x_mult", 1.5) or 1.5)
                return Effect(x_mult=x, message=f"Observatory X{fmt_number(x)}")
    return None


# -- descriptions -----------------------------------------------------------

def _strip_markup(text: str) -> str:
    return _MARKUP.sub("", text)


def _loc_text(key: str) -> str:
    try:
        loc = loader.localization("en-us")
    except Exception:  # assets missing -> fall back to VOUCHER_EFFECTS
        return ""
    entry = ((loc.get("descriptions") or {}).get(VOUCHER_SET) or {}).get(key) or {}
    lines = entry.get("text") or []
    if not lines:
        return ""
    return " ".join(_strip_markup(str(line)) for line in lines).strip()


def _desc_args(key: str, cfg: dict) -> list[str]:
    field, mode = _LOC_ARG.get(key, (None, "plain"))
    if not field:
        return []
    value = cfg.get(field)
    if value is None:
        return []
    if mode == "interest":
        value = int(value) // 5
    return [fmt_number(value)]


def describe(key: str) -> str:
    """Plain-text description of ``key`` ('' for a non-voucher key)."""
    c = center(key)
    if c.get("set") != VOUCHER_SET:
        return ""
    text = _loc_text(key)
    if not text:
        return VOUCHER_EFFECTS.get(key, "")

    args = _desc_args(key, voucher_config(key))

    def _sub(match: re.Match) -> str:
        idx = int(match.group(1)) - 1
        return args[idx] if 0 <= idx < len(args) else match.group(0)

    return re.sub(r"\s+", " ", _PLACEHOLDER.sub(_sub, text)).strip()
