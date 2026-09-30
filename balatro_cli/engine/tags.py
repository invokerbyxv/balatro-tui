"""Tag effects, ported from ``balatro_source_code/tag.lua``.

A Tag is gained by *skipping a blind* (``button_callbacks.lua:2740 skip_blind``
-> ``add_tag``, UI_definitions.lua:1252), and every tag carries a
``config.type`` naming the event it reacts to.  ``Tag:apply_to_run(context)``
(tag.lua:115-468) is one if-chain keyed off ``context.type``; this module is its
Python spelling:

    engine/tags.py  ->  tag.lua:115-468

The run holds tag *keys* in ``run.tags`` (list[str]).  Balatro's tags are
objects with a per-object ``triggered`` flag (tag.lua:12) and the same key can
be held twice (Double Tag), so that bit lives in a parallel list
``run.tag_flags`` which the helpers below keep in sync with ``run.tags``.

:func:`apply` mirrors one ``Tag:apply_to_run`` call (it marks the tag triggered
but leaves it in ``run.tags``, exactly like the Lua before ``Tag:remove()``);
:func:`apply_tags` is the loop the Lua call sites run, and consumes the tags
that fired.

Extra run state (all optional, created on demand with getattr/setattr so this
effect table never imports ``game_state``):

    run.tag_flags              list[bool]  per held tag: already triggered?
    run.tag_double_pending     bool        Double Tag awaiting the next tag
    run.pending_packs          list[str]   free booster packs to open
    run.pending_vouchers       list[int]   extra vouchers for the next shop
    run.round_bonus            dict        next-round modifiers (``h_size``)
    run.boss_reroll_pending    bool        Boss Tag asked to reroll the boss
    run.shop_free              bool        Coupon Tag: shop items are free
    run.shop_d6ed              bool        D6 Tag already used this shop
    run.orbital_choices        dict        {ante: {blind_kind: poker_hand}}

``run.add_tag`` should honour ``run.tag_double_pending`` (add the key twice,
then clear the flag) - the Double Tag fires on the *next* tag gained
(tag.lua:319-333).

Never prints, stdlib + :mod:`balatro_cli.data.loader` only.
"""

from __future__ import annotations

import re

from ..data import loader
from .hooks import Context

# ---------------------------------------------------------------------------
# Tag data (assets/tags.json, extracted from game.lua:224)
# ---------------------------------------------------------------------------

# config.type -> the events Tag:apply_to_run reacts to (tag.lua:115-467)
EVENTS = (
    "eval", "voucher_add", "store_joker_create", "store_joker_modify",
    "new_blind_choice", "immediate", "shop_final_pass", "tag_add",
    "round_start_bonus", "shop_start",
)

# tag -> edition centre key (tag.lua:398-441)
EDITION_TAGS = {
    "tag_foil": "e_foil",
    "tag_holo": "e_holo",
    "tag_polychrome": "e_polychrome",
    "tag_negative": "e_negative",
}

# tag -> free booster pack (tag.lua:209-283); "_" suffix means "mega 1 or 2"
PACK_TAGS = {
    "tag_charm": ("p_arcana_mega_", "Arcana"),
    "tag_meteor": ("p_celestial_mega_", "Celestial"),
    "tag_ethereal": ("p_spectral_normal_1", "Spectral"),
    "tag_standard": ("p_standard_mega_1", "Standard"),
    "tag_buffoon": ("p_buffoon_mega_1", "Buffoon"),
}

# Fallback one-liners (used only when the localization asset is unavailable)
SIMPLE_DESCRIPTIONS = {
    "tag_uncommon": "Shop has a free Uncommon Joker",
    "tag_rare": "Shop has a free Rare Joker",
    "tag_negative": "Next shop Joker is free and becomes Negative",
    "tag_foil": "Next shop Joker is free and becomes Foil",
    "tag_holo": "Next shop Joker is free and becomes Holographic",
    "tag_polychrome": "Next shop Joker is free and becomes Polychrome",
    "tag_investment": "After defeating the Boss Blind, gain $25",
    "tag_voucher": "Adds an extra Voucher to the next shop",
    "tag_boss": "Rerolls the Boss Blind",
    "tag_standard": "Gives a free Mega Standard Pack",
    "tag_charm": "Gives a free Mega Arcana Pack",
    "tag_meteor": "Gives a free Mega Celestial Pack",
    "tag_buffoon": "Gives a free Mega Buffoon Pack",
    "tag_handy": "Gives $1 per played hand this run",
    "tag_garbage": "Gives $1 per unused discard this run",
    "tag_ethereal": "Gives a free Spectral Pack",
    "tag_coupon": "Initial cards and booster packs in the next shop are free",
    "tag_double": "Gives a copy of the next selected Tag",
    "tag_juggle": "+3 hand size next round",
    "tag_d_six": "Rerolls in the next shop start at $0",
    "tag_top_up": "Create up to 2 Common Jokers",
    "tag_skip": "Gives $5 per skipped Blind this run",
    "tag_orbital": "Upgrade a random Poker Hand by 3 levels",
    "tag_economy": "Doubles your money (max of $40)",
}

_RICH = re.compile(r"\{[^{}]*\}")


# ---------------------------------------------------------------------------
# Reader helpers
# ---------------------------------------------------------------------------

def tag_defs() -> dict:
    """All tag prototypes (``self.P_TAGS``), keyed by tag key."""
    try:
        return loader.tags()
    except (OSError, ValueError):   # asset missing/corrupt -> tags are no-ops
        return {}


def config_of(key: str) -> dict:
    return tag_defs().get(key, {}).get("config") or {}


def name_of(key: str) -> str:
    """The tag's display name (``proto.name``, tag.lua:10)."""
    d = tag_defs().get(key)
    if isinstance(d, dict) and d.get("name"):
        return d["name"]
    try:
        loc = loader.localization("en-us").get("descriptions", {}).get("Tag", {})
        if loc.get(key, {}).get("name"):
            return loc[key]["name"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return key


def _loc_vars(key: str, cfg: dict) -> dict:
    """``Tag:get_uibox_table`` loc_vars (tag.lua:545-558), minus run counters."""
    if key == "tag_investment":
        return {1: cfg.get("dollars", 0)}
    if key == "tag_handy":
        return {1: cfg.get("dollars_per_hand", 0), 2: 0}
    if key == "tag_garbage":
        return {1: cfg.get("dollars_per_discard", 0), 2: 0}
    if key == "tag_juggle":
        return {1: cfg.get("h_size", 0)}
    if key == "tag_top_up":
        return {1: cfg.get("spawn_jokers", 0)}
    if key == "tag_skip":
        return {1: cfg.get("skip_bonus", 0), 2: cfg.get("skip_bonus", 0)}
    if key == "tag_orbital":
        return {1: "a random Poker Hand", 2: cfg.get("levels", 0)}
    if key == "tag_economy":
        return {1: cfg.get("max", 0)}
    return {}


def describe(key: str) -> str:
    """One-line plain-text description of a tag (localization text if present)."""
    cfg = config_of(key)
    try:
        entry = (loader.localization("en-us").get("descriptions", {})
                 .get("Tag", {}).get(key) or {})
        lines = entry.get("text")
        if lines:
            text = _RICH.sub("", " ".join(lines)).strip()
            for i, value in _loc_vars(key, cfg).items():
                text = text.replace(f"#{i}#", str(value))
            if text:
                return text
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return SIMPLE_DESCRIPTIONS.get(key, name_of(key))


# ---------------------------------------------------------------------------
# Pool / random selection (common_events.lua:1914, game.lua:779-793)
# ---------------------------------------------------------------------------

def tag_pool(ante: int) -> list[str]:
    """`get_current_pool('Tag')` culled by ``min_ante`` (common_events.lua:1982).

    Returns every tag key whose ``min_ante`` is nil or <= ``ante``, in ``order``.
    The Lua also culls on ``requires`` (e.g. Negative Tag needs ``e_negative``
    *discovered*); discovery is not tracked yet, so those stay available.
    """
    try:
        pool = loader.pools().get("Tag", [])
    except (OSError, ValueError):
        pool = []
    if not pool:                                   # degrade: straight from data
        pool = sorted((dict(v, key=k) for k, v in tag_defs().items()),
                      key=lambda a: (a.get("order") is None, a.get("order", 0)))
    lvl = max(1, int(ante or 1))
    out = []
    for entry in pool:
        ma = entry.get("min_ante")
        if ma is None or int(ma) <= lvl:
            out.append(entry["key"])
    return out


def _rng(run):
    return getattr(run, "rng", None)


def _rng_num(run, key: str, lo: int, hi: int) -> int:
    rng = _rng(run)
    if rng is None:
        return lo
    try:
        return int(rng.num(key, lo, hi))
    except (AttributeError, TypeError, ValueError):
        return lo


def _record_orbital_choice(run, ante: int, blind_kind: str | None) -> str | None:
    """Mirror ``Tag:set_ability`` (tag.lua:103) picking the Orbital hand.

    UI_definitions.lua:1506-1515 stores ``pseudorandom_element(_poker_hands,
    pseudoseed('orbital'))`` per ante/blind; the Orbital tag then upgrades it.
    """
    hands = getattr(run, "hand_levels", None)
    if not isinstance(hands, dict) or not hands:
        return None
    names = list(hands)
    rng = _rng(run)
    if rng is not None:
        try:
            hand = rng.pick("orbital", names)
        except (AttributeError, TypeError, IndexError):
            hand = names[0]
    else:
        hand = names[0]
    choices = getattr(run, "orbital_choices", None)
    if not isinstance(choices, dict):
        choices = {}
        setattr(run, "orbital_choices", choices)
    per_ante = choices.get(ante)
    if not isinstance(per_ante, dict):
        per_ante = {}
        choices[ante] = per_ante
    per_ante[blind_kind or "Small"] = hand
    return hand


def random_tag(run, ante: int, blind_kind: str) -> str:
    """`get_next_tag_key` (common_events.lua:1914): pool-correct random tag."""
    pool = tag_pool(ante)
    banned = getattr(run, "banned_keys", None) or set()
    allowed = [k for k in pool if k not in banned] or pool
    if not allowed:
        return ""
    rng = _rng(run)
    if rng is None:
        key = allowed[0]
    else:
        try:
            key = rng.pick("Tag", allowed)
        except (AttributeError, TypeError, IndexError):
            key = allowed[0]
    if key == "tag_orbital":
        _record_orbital_choice(run, ante, blind_kind)
    return key


# ---------------------------------------------------------------------------
# held-tag bookkeeping (per-object `triggered` flag, tag.lua:12)
# ---------------------------------------------------------------------------

def _flags(run) -> list:
    flags = getattr(run, "tag_flags", None)
    if not isinstance(flags, list):
        flags = []
        setattr(run, "tag_flags", flags)
    tags = getattr(run, "tags", None) or []
    while len(flags) < len(tags):
        flags.append(False)
    if len(flags) > len(tags):
        del flags[len(tags):]
    return flags


def _find_pending(run, key: str):
    """Index of the first held, not-yet-triggered instance of ``key``."""
    tags = getattr(run, "tags", None) or []
    flags = _flags(run)
    for i, held in enumerate(tags):
        if held == key and not flags[i]:
            return i
    return None


def _mark(run, idx: int) -> None:
    flags = _flags(run)
    if 0 <= idx < len(flags):
        flags[idx] = True


def _consume(run, idx: int) -> None:
    """Lua ``Tag:remove()`` (tag.lua:571): drop one instance from G.GAME.tags."""
    tags = getattr(run, "tags", None)
    flags = _flags(run)
    if tags is None or not 0 <= idx < len(tags):
        return
    tags.pop(idx)
    if idx < len(flags):
        flags.pop(idx)


def _round_bonus(run) -> dict:
    rb = getattr(run, "round_bonus", None)
    if not isinstance(rb, dict):
        rb = {}
        setattr(run, "round_bonus", rb)
    return rb


def _pending_packs(run) -> list:
    packs = getattr(run, "pending_packs", None)
    if not isinstance(packs, list):
        packs = []
        setattr(run, "pending_packs", packs)
    return packs


def _pending_vouchers(run) -> list:
    pend = getattr(run, "pending_vouchers", None)
    if not isinstance(pend, list):
        pend = []
        setattr(run, "pending_vouchers", pend)
    return pend


def _add_tag(run, key: str) -> None:
    """`add_tag` (UI_definitions.lua:1252)."""
    fn = getattr(run, "add_tag", None)
    if callable(fn):
        fn(key)
        return
    tags = getattr(run, "tags", None)
    if not isinstance(tags, list):
        tags = []
        setattr(run, "tags", tags)
    tags.append(key)
    if key != "tag_double" and getattr(run, "tag_double_pending", False):
        tags.append(key)
        setattr(run, "tag_double_pending", False)


def _jokers(run) -> list:
    jokers = getattr(run, "jokers", None)
    return jokers if isinstance(jokers, list) else []


def _joker_slot_free(run) -> bool:
    """Lua ``#G.jokers.cards < G.jokers.config.card_limit``."""
    params = getattr(run, "params", None) or {}
    limit = params.get("joker_slots") if isinstance(params, dict) else None
    if limit is None:
        return True
    return len(_jokers(run)) < int(limit)


def _joker_key(j) -> str | None:
    if isinstance(j, str):
        return j
    return getattr(j, "key", None)


def _pool_joker_key(run, rarity: int, rng_key: str) -> str | None:
    try:
        pools = loader.pools()
        pool = pools["JokerRarity"][rarity] or pools["Joker"]
    except (KeyError, IndexError, OSError, ValueError):
        return None
    if not pool:
        return None
    rng = _rng(run)
    if rng is not None:
        try:
            return rng.pick(rng_key, pool).get("key")
        except (AttributeError, TypeError, IndexError):
            pass
    return pool[0].get("key")


def _create_card(run, kind: str, **kw):
    """`run.create_card` (PORTING.md); ``None`` when the run has no factory."""
    fn = getattr(run, "create_card", None)
    if not callable(fn):
        return None
    return fn(kind, **kw)


def _make_joker(run, rarity: int, rng_key: str, **kw):
    """create_card('Joker', ..., _rarity) - falls back to a pool key."""
    card = _create_card(run, "Joker", rarity=rarity, **kw)
    if card is not None:
        return card
    key = _pool_joker_key(run, rarity, rng_key)
    if key is None:
        return None
    maker = getattr(run, "make_card", None)          # optional test hook
    if callable(maker):
        return maker("Joker", key)
    from .card import JokerCard
    pool = loader.pools()["JokerRarity"][rarity]
    entry = next((c for c in pool if c.get("key") == key), {})
    return JokerCard(key, entry.get("name", key), entry.get("config") or {},
                     rarity=rarity, cost=entry.get("cost", 0))


def _emplace_joker(run, card) -> None:
    """``G.jokers:emplace(card)``; prefers ``run.add_joker`` when present."""
    if card is None or not _joker_slot_free(run):
        return
    key = _joker_key(card)
    fn = getattr(run, "add_joker", None)
    if callable(fn) and key:
        fn(key, edition=getattr(card, "edition", None))
        return
    if isinstance(card, str):
        _jokers(run).append(card)
    else:
        _jokers(run).append(card)


def _result(message: str, dollars: int = 0, **extra) -> dict:
    return {"dollars": int(dollars), "message": message, "extra": extra}


def _round_count(run, *names: str) -> int:
    """A ``G.GAME.current_round`` counter, falling back to a run attribute."""
    cr = getattr(run, "current_round", None)
    if isinstance(cr, dict):
        for n in names:
            v = cr.get(n)
            if isinstance(v, (int, float)):
                return int(v)
    for n in names:
        v = getattr(run, n, None)
        if isinstance(v, (int, float)):
            return int(v)
    return 0


def _context_card(ctx):
    extra = getattr(ctx, "extra", None) or {}
    return extra.get("card") or getattr(ctx, "other_card", None)


def _context_tag_key(ctx) -> str | None:
    extra = getattr(ctx, "extra", None) or {}
    for name in ("tag", "tag_key"):
        v = extra.get(name)
        if v is None:
            continue
        if isinstance(v, str):
            return v
        return getattr(v, "key", None)
    return None


# ---------------------------------------------------------------------------
# Tag handlers (tag.lua:115-468)
# ---------------------------------------------------------------------------

def _tag_investment(run, key, cfg, ctx):
    """tag.lua:118 - $config.dollars, only after a defeated Boss Blind."""
    last = getattr(run, "last_blind", None)
    if isinstance(last, dict):
        boss = bool(last.get("boss"))
    else:
        boss = bool(getattr(last, "boss", False)) or bool(getattr(last, "is_boss", False))
    if not boss:
        return None
    dollars = int(cfg.get("dollars", 0) or 0)
    return _result(f"+${dollars} ({name_of(key)})", dollars,
                   condition="ph_defeat_the_boss")


def _tag_voucher(run, key, cfg, ctx):
    """tag.lua:303 - +1 voucher slot/card in the next shop."""
    _pending_vouchers(run).append(1)
    setattr(run, "voucher_tag", True)
    return _result("+1 Voucher in the next shop", 0, vouchers=1)


def _tag_pack(run, key, cfg, ctx):
    """tag.lua:209-283 - free booster pack of the matching kind."""
    base, kind = PACK_TAGS[key]
    pack_key = f"{base}{_rng_num(run, 'tag_pack', 1, 2)}" if base.endswith("_") else base
    _pending_packs(run).append(pack_key)
    return _result(f"Free {kind} Pack", 0, pack=pack_key, pack_kind=kind, free=True)


def _tag_boss(run, key, cfg, ctx):
    """tag.lua:284 - reroll the Boss Blind (`G.from_boss_tag`, reroll_boss)."""
    setattr(run, "boss_reroll_pending", True)
    return _result("Boss Blind rerolled", 0, reroll_boss=True, from_boss_tag=True)


def _tag_uncommon(run, key, cfg, ctx):
    """tag.lua:369 - a free Uncommon Joker for the shop (`_rarity` 0.9 -> 2)."""
    card = _make_joker(run, 2, "uta", area=getattr(ctx, "area", None))
    if card is not None and isinstance(getattr(card, "ability", None), dict):
        card.ability["couponed"] = True
    return _result("Uncommon Joker", 0, card=card, rarity=2, kind="Joker", free=True)


def _tag_rare(run, key, cfg, ctx):
    """tag.lua:346 - a free Rare Joker (skipped once every Rare is owned)."""
    try:
        rare_pool = loader.pools()["JokerRarity"][3]
    except (KeyError, IndexError, OSError, ValueError):
        rare_pool = []
    owned = set()
    for j in _jokers(run):
        k = _joker_key(j)
        if not k:
            continue
        rarity = (getattr(j, "ability", None) or {}).get("rarity")
        if rarity is None:
            rarity = (loader.centers().get(k) or {}).get("rarity")
        if rarity == 3:
            owned.add(k)
    if rare_pool and len(rare_pool) <= len(owned):
        return None
    # NB: the decompiled call passes `_rarity = 1` (-> Common); the tag's own
    # contract is a *Rare* Joker, so we ask the pool for rarity 3.
    card = _make_joker(run, 3, "rta", area=getattr(ctx, "area", None))
    if card is not None and isinstance(getattr(card, "ability", None), dict):
        card.ability["couponed"] = True
    return _result("Rare Joker", 0, card=card, rarity=3, kind="Joker", free=True)


def _tag_edition(run, key, cfg, ctx):
    """tag.lua:393-446 - edition + free cost on the next shop Joker."""
    card = _context_card(ctx)
    if card is None:
        return None
    ability = getattr(card, "ability", None)
    if not isinstance(ability, dict):
        ability = {}
    if getattr(card, "edition", None) or ability.get("temp_edition"):
        return None
    if not getattr(card, "is_joker", False) and ability.get("set") != "Joker":
        return None
    edition = EDITION_TAGS[key]
    card.edition = edition
    ability["couponed"] = True
    return _result(f"Joker is {edition[2:].title()}", 0,
                   card=card, edition=edition, couponed=True)


def _tag_coupon(run, key, cfg, ctx):
    """tag.lua:447 - the next shop's stock is free."""
    if getattr(run, "shop_free", False):
        return None
    shop = getattr(run, "shop", None)
    if shop is None:                       # Lua requires G.shop
        return None
    setattr(run, "shop_free", True)
    for item in getattr(shop, "items", None) or []:
        if item is not None and hasattr(item, "cost"):
            item.cost = 0
    return _result("Shop is free", 0, shop_free=True)


def _tag_double(run, key, cfg, ctx):
    """tag.lua:319 - copy the next tag gained (not another Double Tag)."""
    other = _context_tag_key(ctx)
    if other is None:
        # No "next tag" in this context yet: remember it, so run.add_tag can
        # double the next tag gained.
        setattr(run, "tag_double_pending", True)
        return None
    if other == "tag_double":
        return None
    _add_tag(run, other)
    return _result(f"Copied {name_of(other)}", 0, copied=other, duplicate=True)


def _tag_juggle(run, key, cfg, ctx):
    """tag.lua:334 - +config.h_size hand size for the next round."""
    size = int(cfg.get("h_size", 0) or 0)
    bonus = _round_bonus(run)
    bonus["h_size"] = int(bonus.get("h_size", 0) or 0) + size
    if isinstance(getattr(run, "hand_size", None), int):
        run.hand_size += size
    return _result(f"+{size} hand size next round", 0, h_size=size)


def _tag_d_six(run, key, cfg, ctx):
    """tag.lua:382 - shop rerolls start at $0."""
    if getattr(run, "shop_d6ed", False):
        return None
    setattr(run, "shop_d6ed", True)
    setattr(run, "reroll_cost", 0)
    shop = getattr(run, "shop", None)
    if shop is not None and hasattr(shop, "reroll_cost"):
        shop.reroll_cost = 0
    return _result("Shop rerolls are free", 0, reroll_cost=0)


def _tag_top_up(run, key, cfg, ctx):
    """tag.lua:134 - create `config.spawn_jokers` Common Jokers."""
    count = int(cfg.get("spawn_jokers", 0) or 0)
    made = []
    for _ in range(count):
        if not _joker_slot_free(run):
            break
        card = _make_joker(run, 1, "top")
        if card is None:
            break
        _emplace_joker(run, card)
        made.append(_joker_key(card) or card)
    return _result(f"Created {len(made)} Common Joker(s)", 0, jokers=made, count=len(made))


def _tag_skip(run, key, cfg, ctx):
    """tag.lua:149 - $config.skip_bonus per skipped Blind this run."""
    bonus = int(cfg.get("skip_bonus", 0) or 0)
    skips = int(getattr(run, "skips", 0) or 0) or 1   # the skip that granted it
    dollars = bonus * skips
    return _result(f"+${dollars}", dollars, skips=skips)


def _tag_garbage(run, key, cfg, ctx):
    """tag.lua:158 - $config.dollars_per_discard per unused discard this run.

    ``G.GAME.unused_discards`` is a run-level tally (state_events.lua:129).
    """
    per = int(cfg.get("dollars_per_discard", 0) or 0)
    n = int(getattr(run, "unused_discards", 0) or 0) or \
        _round_count(run, "discards_used", "unused_discards")
    dollars = per * n
    return _result(f"+${dollars}", dollars, discards=n)


def _tag_handy(run, key, cfg, ctx):
    """tag.lua:167 - $config.dollars_per_hand per hand played this run."""
    per = int(cfg.get("dollars_per_hand", 0) or 0)
    n = int(getattr(run, "hands_played_total", 0) or 0) or \
        _round_count(run, "hands_played")
    dollars = per * n
    return _result(f"+${dollars}", dollars, hands=n)


def _tag_economy(run, key, cfg, ctx):
    """tag.lua:176 - double your money, capped at config.max."""
    cap = int(cfg.get("max", 0) or 0)
    held = int(getattr(run, "dollars", 0) or 0)
    dollars = min(cap, max(0, held))
    return _result(f"+${dollars}", dollars, cap=cap)


def _orbital_hand(run) -> str | None:
    hand = getattr(run, "orbital_hand", None)
    if hand:
        return hand
    choices = getattr(run, "orbital_choices", None)
    if isinstance(choices, dict):
        per_ante = choices.get(getattr(run, "ante", 1))
        if isinstance(per_ante, dict):
            for v in per_ante.values():
                if v:
                    return v
    return _record_orbital_choice(run, getattr(run, "ante", 1), None)


def _tag_orbital(run, key, cfg, ctx):
    """tag.lua:191 - upgrade the chosen Poker Hand by config.levels."""
    levels = int(cfg.get("levels", 0) or 0)
    hand = _orbital_hand(run)
    if not hand:
        return None
    fn = getattr(run, "level_up_hand", None)
    if callable(fn):
        fn(hand, levels)
    else:
        levels_map = getattr(run, "hand_levels", None)
        if isinstance(levels_map, dict) and hand in levels_map:
            entry = levels_map[hand]
            entry["level"] = int(entry.get("level", 1) or 1) + levels
    return _result(f"{hand} +{levels} level(s)", 0, hand=hand, levels=levels)


TAG_HANDLERS = {
    "tag_uncommon": _tag_uncommon,
    "tag_rare": _tag_rare,
    "tag_negative": _tag_edition,
    "tag_foil": _tag_edition,
    "tag_holo": _tag_edition,
    "tag_polychrome": _tag_edition,
    "tag_investment": _tag_investment,
    "tag_voucher": _tag_voucher,
    "tag_boss": _tag_boss,
    "tag_standard": _tag_pack,
    "tag_charm": _tag_pack,
    "tag_meteor": _tag_pack,
    "tag_buffoon": _tag_pack,
    "tag_handy": _tag_handy,
    "tag_garbage": _tag_garbage,
    "tag_ethereal": _tag_pack,
    "tag_coupon": _tag_coupon,
    "tag_double": _tag_double,
    "tag_juggle": _tag_juggle,
    "tag_d_six": _tag_d_six,
    "tag_top_up": _tag_top_up,
    "tag_skip": _tag_skip,
    "tag_orbital": _tag_orbital,
    "tag_economy": _tag_economy,
}


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def apply(run, tag_key: str, ctx) -> dict | None:
    """Port of ``Tag:apply_to_run`` (tag.lua:115).

    ``ctx`` is a :class:`hooks.Context` whose ``.event`` is the tag's
    ``config.type`` spelling ('eval', 'immediate', ...).  Returns ``None`` when
    the tag does not fire, else a dict with any of
    ``{'dollars': int, 'message': str, 'extra': {...}}``.

    Firing marks the tag triggered (tag.lua:12) but leaves it in ``run.tags``;
    :func:`apply_tags` removes the tags it consumed.
    """
    idx = _find_pending(run, tag_key)
    if idx is None:
        return None
    cfg = config_of(tag_key)
    if not cfg or cfg.get("type") != getattr(ctx, "event", None):
        return None
    handler = TAG_HANDLERS.get(tag_key)
    if handler is None:
        return None
    result = handler(run, tag_key, cfg, ctx)
    if result is None:
        return None
    _mark(run, idx)
    return result


def _context(run, event: str, kw: dict) -> Context:
    ctx = Context(event=event, run=run, extra=dict(kw))
    if "area" in kw:
        ctx.area = kw["area"]
    if "card" in kw:
        ctx.other_card = kw["card"]
    if "blind" in kw:
        ctx.blind = kw["blind"]
    return ctx


def apply_tags(run, event: str, **kw) -> list[dict]:
    """Fire every held, not-yet-triggered tag whose ``config.type`` is `event`.

    Fired tags are consumed (removed from ``run.tags``, Lua ``Tag:remove()``).
    Returns one dict per fired tag, each carrying its ``key``.

    ``kw`` becomes the :class:`hooks.Context` extra (e.g. ``tag=``,
    ``card=``, ``area=``, ``blind=``).  ``first_only=True`` stops after the
    first tag fires, mirroring the call sites that ``break`` out of the loop
    (game.lua:3293-3294, button_callbacks.lua:2775).
    """
    first_only = bool(kw.pop("first_only", False))
    tags = getattr(run, "tags", None)
    if not isinstance(tags, list) or not tags:
        return []
    ctx = _context(run, event, kw)
    snapshot = list(tags)
    fired: list[dict] = []
    consumed: list[int] = []
    for key in snapshot:
        idx = _find_pending(run, key)
        if idx is None:
            continue
        result = apply(run, key, ctx)
        if result is None:
            continue
        consumed.append(idx)
        fired.append({"key": key, **result})
        if first_only:
            break
    for idx in sorted(set(consumed), reverse=True):
        _consume(run, idx)
    return fired
