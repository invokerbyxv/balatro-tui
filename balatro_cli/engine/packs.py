"""Card creation, edition rolls and booster packs.

Port of ``balatro_source_code/functions/common_events.lua`` (+ the pack flow in
``card.lua``/``button_callbacks.lua``):

============================  ==================================================
this module                   Lua
============================  ==================================================
:func:`get_pack`              ``get_pack`` (common_events.lua:1944)
:func:`get_current_pool`      ``get_current_pool`` (common_events.lua:1963)
:func:`poll_edition`          ``poll_edition`` (common_events.lua:2055)
:func:`create_card`           ``create_card`` (common_events.lua:2082)
:func:`random_voucher_key`    ``get_next_voucher_key`` (common_events.lua:1901)
:func:`random_tag_key`        ``get_next_tag_key`` (common_events.lua:1914)
:func:`open_pack`             ``Card:open`` (card.lua:1681)
:func:`pack_choices`          the ``pack_cards`` area built by ``Card:open``
:func:`take_from_pack`        ``G.FUNCS.use_card`` pack branch (button_callbacks.lua:2171)
============================  ==================================================

Every roll goes through ``run.rng`` (:class:`balatro_cli.engine.rng.RNG`) with the
same string key the Lua passes to ``pseudoseed``/``pseudorandom``, so a run is
reproducible and each event has its own stream.  Nothing here prints, imports
``game_state`` or mutates the run's card areas: :func:`create_card` only *builds*
a card (``GameState.create_card`` does the placement), and :func:`open_pack`
returns the pack state for the caller to show.

Coverage / v1 divergences (all deliberate, all documented here)
--------------------------------------------------------------
* ``kind`` is the Lua ``_type``.  ``'Standard'``/``'Default'`` are aliases of
  ``'Base'`` (a plain/enhanced playing card); ``'Booster'`` draws from the
  Booster pool and yields a ``JokerCard`` with ``set == 'Booster'``.
* ``run.used_jokers`` / ``run.unlocked_keys`` / ``run.discovered_keys`` are read
  when present.  v1 does not track unlock/discovery progression (the same
  convention ``data/pools.py`` uses for Backs), so with none of them present the
  Lua's ``unlocked``/``discovered`` culls are treated as satisfied.
* The shop-voucher cull in ``get_current_pool`` (a voucher already offered this
  shop) is skipped - v1 shops are generated elsewhere.
* Eternal/Perishable/Rental (stake + challenge modifiers) and the
  ``skip_materialize``/animation arguments have no v1 equivalent and are ignored.
* ``get_pack``'s first-shop Buffoon rule uses the seeded RNG instead of Lua's
  unseeded ``math.random(1, 2)``; it still fires only once per run.
* ``run.edition_rate`` is the only rate ``poll_edition`` uses in the Lua.
  ``tarot_rate``/``planet_rate``/``spectral_rate`` weight *shop slot types*
  (UI_definitions.lua:764) rather than pack contents, so they are exposed through
  :func:`rates` and used by ``engine/shop`` - not by the pack draw itself.
"""

from __future__ import annotations

from .card import Card, JokerCard, SUIT_LETTER, normalize_seal

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

#: Lua ``_type`` values that produce a playing card (``set`` Base/Enhanced/Default).
PLAYING_CARD_SETS = frozenset({"Base", "Enhanced", "Default"})
#: Lua ``_type`` values that produce a consumable (Tarot/Planet/Spectral centers).
CONSUMABLE_SETS = frozenset({"Tarot", "Planet", "Spectral"})
#: ``get_pack`` kind filter values (the 5 booster ``kind`` fields).
BOOSTER_KINDS = ("Arcana", "Celestial", "Spectral", "Standard", "Buffoon")
#: Booster ``kind`` -> the ``_type`` ``Card:open`` draws for each card.
PACK_CARD_KIND = {"Arcana": "Tarot", "Celestial": "Planet", "Spectral": "Spectral",
                  "Standard": "Base", "Buffoon": "Joker"}
#: Booster ``kind`` -> the ``create_card`` ``key_append`` used by ``Card:open``.
PACK_KEY_APPEND = {"Arcana": "ar1", "Celestial": "pl1", "Spectral": "spe",
                   "Standard": "sta", "Buffoon": "buf"}
#: ``_type`` aliases (common_events.lua has no 'Standard' type; c_base is 'Default').
KIND_ALIASES = {"Standard": "Base", "Default": "Base"}

#: get_current_pool's empty-pool fallbacks (common_events.lua:2039-2049).
EMPTY_POOL_FALLBACK = {"Tarot": "c_strength", "Tarot_Planet": "c_strength",
                       "Planet": "c_pluto", "Spectral": "c_incantation",
                       "Joker": "j_joker", "Voucher": "v_blank", "Tag": "tag_handy",
                       # Lua has no Base/Enhanced arm (its pool is never empty);
                       # c_base keeps the card a playing card.
                       "Base": "c_base", "Enhanced": "c_base"}
#: fallback for any other type (Lua's ``else`` -> j_joker).
DEFAULT_FALLBACK = "j_joker"

#: poll_edition results, worst-to-best (shadowed by no_neg, see :func:`poll_edition`).
EDITION_NEGATIVE = "e_negative"
EDITION_POLYCHROME = "e_polychrome"
EDITION_HOLO = "e_holo"
EDITION_FOIL = "e_foil"

#: ``create_card``'s "The Soul"/"Black Hole" substitution odds (1 in ~334).
SOUL_CHANCE = 0.997
#: Arcana pack: Omen Globe turns a card into a Spectral one (common_events.lua:1731).
OMEN_GLOBE_ODDS = 0.8
#: Standard pack: edition/seal rates (card.lua:1760-1765).
STANDARD_EDITION_RATE = 2
STANDARD_SEAL_RATE = 10
#: Standard pack: chance the pack offers Enhanced rather than Base cards.
STANDARD_ENHANCED_ODDS = 0.6
#: ``get_pack``'s "first shop always has a Buffoon pack" keys (common_events.lua:1947).
FIRST_SHOP_BUFFOON = ("p_buffoon_normal_1", "p_buffoon_normal_2")
#: bounded stand-in for Lua's unbounded UNAVAILABLE re-sample loop.
RESAMPLE_LIMIT = 64

#: card front values -> ``Card.rank`` (game.lua:P_CARDS / cards.json).
VALUE_RANK = {"2": "2", "3": "3", "4": "4", "5": "5", "6": "6", "7": "7", "8": "8",
              "9": "9", "10": "T", "T": "T", "Jack": "J", "J": "J", "Queen": "Q",
              "Q": "Q", "King": "K", "K": "K", "Ace": "A", "A": "A"}

#: ``G.P_TAGS`` (game.lua:224-249) as (key, min_ante, requires), in ``order``.
#: Only a fallback: ``loader.pools()['Tag']`` (data/tags.json) is preferred.
INLINE_TAGS = (
    ("tag_uncommon", None, None), ("tag_rare", None, "j_blueprint"),
    ("tag_negative", 2, "e_negative"), ("tag_foil", None, "e_foil"),
    ("tag_holo", None, "e_holo"), ("tag_polychrome", None, "e_polychrome"),
    ("tag_investment", None, None), ("tag_voucher", None, None),
    ("tag_boss", None, None), ("tag_standard", 2, None), ("tag_charm", None, None),
    ("tag_meteor", 2, None), ("tag_buffoon", 2, None), ("tag_handy", 2, None),
    ("tag_garbage", 2, None), ("tag_ethereal", 2, None), ("tag_coupon", None, None),
    ("tag_double", None, None), ("tag_juggle", None, None), ("tag_d_six", None, None),
    ("tag_top_up", 2, None), ("tag_skip", None, None), ("tag_orbital", 2, None),
    ("tag_economy", None, None),
)


# ---------------------------------------------------------------------------
# run accessors (duck-typed; never import game_state)
# ---------------------------------------------------------------------------

def _ante(run) -> int:
    """``G.GAME.round_resets.ante``."""
    try:
        return int(getattr(run, "ante", 1) or 1)
    except (TypeError, ValueError):
        return 1


def _banned(run) -> frozenset:
    return frozenset(getattr(run, "banned_keys", None) or ())


def _pool_flags(run) -> dict:
    return getattr(run, "pool_flags", None) or {}


def _redeemed(run) -> set:
    """Redeemed vouchers: ``G.GAME.used_vouchers`` (+ v1's ``run.vouchers``)."""
    out = set(getattr(run, "used_vouchers", None) or ())
    out |= set(getattr(run, "vouchers", None) or ())
    return out


def _rates(run) -> dict:
    """Shop luck rates (``getattr(run, ..., 1)``), see the module docstring."""
    return {"edition_rate": getattr(run, "edition_rate", 1) or 1,
            "tarot_rate": getattr(run, "tarot_rate", 1) or 1,
            "planet_rate": getattr(run, "planet_rate", 1) or 1,
            "spectral_rate": getattr(run, "spectral_rate", 1) or 1}


#: public alias - ``engine/shop`` weights its slot types with these.
rates = _rates


def _centers() -> dict:
    from ..data import loader
    return loader.centers()


def _pools() -> dict:
    """``G.P_CENTER_POOLS``; degrades to ``{}`` so callers keep the fallbacks."""
    from ..data import loader
    try:
        return loader.pools()
    except Exception:  # missing/stale assets mid-build: use the documented fallbacks
        return {}


def _joker_key(j) -> str:
    if isinstance(j, str):
        return j
    return getattr(j, "key", None) or (getattr(j, "ability", {}) or {}).get("key") or ""


def _has_showman(run) -> bool:
    """``next(find_joker("Showman"))`` - Showman disables the seen-joker cull."""
    return any(_joker_key(j) == "j_showman" for j in (getattr(run, "jokers", None) or ()))


def _joker_seen(run, key: str) -> bool:
    """``G.GAME.used_jokers[key] and not next(find_joker("Showman"))``."""
    seen = getattr(run, "used_jokers", None) or ()
    return key in seen and not _has_showman(run)


def _unlocked(run, entry: dict) -> bool:
    """``v.unlocked ~= false or v.rarity == 4`` (v1 tracks no unlocks)."""
    if entry.get("unlocked") is not False or entry.get("rarity") == 4:
        return True
    keys = getattr(run, "unlocked_keys", None)
    return keys is not None and entry.get("key") in keys


def _discovered(run, key: str) -> bool:
    """``G.P_CENTERS[requires].discovered`` (v1 tracks no discovery)."""
    keys = getattr(run, "discovered_keys", None)
    if keys is None:
        return True
    return key in keys


def _playing_cards(run) -> list:
    fn = getattr(run, "playing_cards", None)
    if callable(fn):
        return list(fn() or ())
    out: list = []
    for attr in ("deck", "hand", "played"):
        out.extend(getattr(run, attr, None) or ())
    return out


# ---------------------------------------------------------------------------
# pools
# ---------------------------------------------------------------------------

def _entries(type_: str) -> list:
    """The starting pool (``G.P_CENTER_POOLS[_type]`` / ``P_JOKER_RARITY_POOLS``)."""
    if type_ == "Tag":
        tag_pool = _pools().get("Tag") or []
        if tag_pool:
            return tag_pool
        return [{"key": k, "set": "Tag", "min_ante": m, "requires": r, "config": {}}
                for k, m, r in INLINE_TAGS]
    return _pools().get(type_) or []


def _voucher_available(run, entry: dict) -> bool:
    """``v.set == 'Voucher'`` cull: not redeemed, requirements redeemed."""
    redeemed = _redeemed(run)
    if entry.get("key") in redeemed:
        return False
    requires = entry.get("requires")
    if not requires:
        return True
    if isinstance(requires, str):
        requires = [requires]
    return all(r in redeemed for r in requires)


def _entry_available(run, type_: str, entry: dict) -> bool:
    """One iteration of ``get_current_pool``'s cull (common_events.lua:1976-2035)."""
    add = None
    if type_ == "Enhanced":
        add = True
    elif type_ == "Tag":
        requires = entry.get("requires")
        if (not requires or _discovered(run, requires)) and _min_ante_ok(run, entry):
            add = True
    elif not _joker_seen(run, entry.get("key")) and _unlocked(run, entry):
        set_ = entry.get("set")
        if set_ == "Voucher":
            add = _voucher_available(run, entry)
        elif set_ == "Planet":
            cfg = entry.get("config") or {}
            if not cfg.get("softlock") or _hands_played(run, cfg.get("hand_type")) > 0:
                add = True
        elif entry.get("enhancement_gate"):
            gate = entry["enhancement_gate"]
            add = any(getattr(c, "enhancement", None) == gate for c in _playing_cards(run))
        else:
            add = True
        if entry.get("name") in ("Black Hole", "The Soul"):
            add = False

    flags = _pool_flags(run)
    if entry.get("no_pool_flag") and flags.get(entry["no_pool_flag"]):
        add = False
    if entry.get("yes_pool_flag") and not flags.get(entry["yes_pool_flag"]):
        add = False
    return bool(add) and entry.get("key") not in _banned(run)


def _min_ante_ok(run, entry: dict) -> bool:
    """``not v.min_ante or v.min_ante <= G.GAME.round_resets.ante``."""
    min_ante = entry.get("min_ante")
    return not min_ante or min_ante <= _ante(run)


def _hands_played(run, hand_type: str | None) -> int:
    if not hand_type:
        return 0
    entry = (getattr(run, "hand_levels", None) or {}).get(hand_type) or {}
    try:
        return int(entry.get("played", 0) or 0)
    except (TypeError, ValueError):
        return 0


def get_current_pool(run, type_, rarity=None, legendary=False, append=""):
    """Port of ``get_current_pool`` (common_events.lua:1963).

    Returns ``(pool, pool_key)`` where ``pool`` holds center keys and the string
    ``'UNAVAILABLE'`` for every culled entry (Lua keeps the holes so that the
    re-sample loop draws from the same-sized table).
    """
    ante = _ante(run)

    if type_ == "Joker":
        # `_rarity or pseudorandom(...)` - the roll happens whenever _rarity is nil.
        rolled = run.rng.roll("rarity" + str(ante) + (append or "")) if rarity is None else rarity
        if legendary:
            tier = 4
        else:
            tier = 3 if rolled > 0.95 else 2 if rolled > 0.7 else 1
        entries = _pools().get("JokerRarity", [[], [], [], [], []])[tier]
        pool_key = "Joker" + str(tier) + ("" if legendary else (append or ""))
    elif type_ == "Tag":
        entries = _entries(type_)
        pool_key = "Tag" + (append or "")
    else:
        entries = _pools().get(type_) or []
        pool_key = type_ + (append or "")

    pool: list[str] = []
    size = 0
    for entry in entries:
        if _entry_available(run, type_, entry):
            pool.append(entry.get("key"))
            size += 1
        else:
            pool.append("UNAVAILABLE")

    if size == 0:
        pool = [EMPTY_POOL_FALLBACK.get(type_, DEFAULT_FALLBACK)]

    return pool, pool_key + ("" if legendary else str(ante))


def _pick_pool(run, pool, pool_key: str, type_: str) -> str:
    """``pseudorandom_element(_pool, pseudoseed(_pool_key))`` + UNAVAILABLE retry."""
    available = [k for k in pool if k != "UNAVAILABLE"]
    if not available:
        return EMPTY_POOL_FALLBACK.get(type_, DEFAULT_FALLBACK)
    picked = run.rng.pick(pool_key, pool)
    it = 1
    while picked == "UNAVAILABLE":
        it += 1
        if it > RESAMPLE_LIMIT:  # Lua loops forever; guarantee an answer instead
            return run.rng.pick(pool_key + "_fallback", available)
        picked = run.rng.pick("%s_resample%d" % (pool_key, it), pool)
    return picked


def pool_keys(run, type_, rarity=None, legendary=False, append="") -> list[str]:
    """The pickable keys of a pool (no ``'UNAVAILABLE'`` holes) - handy for callers."""
    pool, _key = get_current_pool(run, type_, rarity, legendary, append)
    return [k for k in pool if k != "UNAVAILABLE"]


# ---------------------------------------------------------------------------
# editions
# ---------------------------------------------------------------------------

def poll_edition(run, key="edition", mod=1, no_neg=False, guaranteed=False):
    """Port of ``poll_edition`` (common_events.lua:2055).

    One roll in ``[0, 1)`` picks the strongest edition whose threshold it clears:
    negative 0.3%, polychrome 0.6%, holo 2%, foil 4% - all scaled by
    ``run.edition_rate`` (vouchers: Hone -> 2, Glow Up -> 4, ...) and ``mod``.
    ``guaranteed`` replaces the rate with ``edition_rate = 25``, and ``no_neg``
    skips the negative roll (Standard packs never hand out Negative cards).
    Returns an edition center key (``e_foil``/``e_holo``/``e_polychrome``/
    ``e_negative``) or ``None`` (Lua returns nothing).
    """
    mod = mod or 1
    # The `_guaranteed` branch hard-codes 25 in place of G.GAME.edition_rate *and*
    # ignores _mod (common_events.lua:2058-2067).
    neg = 0.003 * (25 if guaranteed else mod)
    mult = 1 if guaranteed else mod
    factor = 25 if guaranteed else (getattr(run, "edition_rate", 1) or 1)

    poll = run.rng.roll(key or "edition_generic")
    if poll > 1 - neg and not no_neg:
        return EDITION_NEGATIVE
    if poll > 1 - 0.006 * factor * mult:
        return EDITION_POLYCHROME
    if poll > 1 - 0.02 * factor * mult:
        return EDITION_HOLO
    if poll > 1 - 0.04 * factor * mult:
        return EDITION_FOIL
    return None


# ---------------------------------------------------------------------------
# create_card
# ---------------------------------------------------------------------------

def _front(run, key_append: str, ante: int) -> tuple[str, str]:
    """``pseudorandom_element(G.P_CARDS, pseudoseed('front'..append..ante))``."""
    from ..data import loader
    try:
        cards = loader.cards()
    except Exception:
        cards = {}
    keys = sorted(cards) or ["S_A"]
    picked = run.rng.pick("front" + (key_append or "") + str(ante), keys)
    entry = cards.get(picked) or {}
    rank = VALUE_RANK.get(str(entry.get("value")), "A")
    suit = SUIT_LETTER.get(entry.get("suit"), "S")
    return rank, suit


def create_card(run, kind, area=None, legendary=False, rarity=None, soulable=False,
                forced_key=None, key_append="", edition=None):
    """Port of ``create_card`` (common_events.lua:2082).

    ``kind`` is the Lua ``_type``: ``Joker``, ``Tarot``, ``Planet``, ``Spectral``,
    ``Enhanced``, ``Base``, ``Standard`` (alias of Base), ``Voucher`` or
    ``Booster``.  ``area`` (``hand``/``jokers``/``consumeables``/``deck``/``None``)
    mirrors the Lua's ``area``: in v1 it only exists for signature parity - the
    caller (``GameState.create_card``) does the placement and v1 has no
    Eternal/Perishable/Rental modifier polls.

    Playing-card types return a :class:`~balatro_cli.engine.card.Card` (with the
    enhancement/edition/seal the draw produced); everything else returns a
    :class:`~balatro_cli.engine.card.JokerCard`.  ``edition`` overrides the
    rolled edition (used by Standard packs, which roll it themselves).
    """
    ante = _ante(run)
    type_ = KIND_ALIASES.get(kind, kind)
    rng = run.rng
    banned = _banned(run)

    # -- The Soul / Black Hole substitution (common_events.lua:2088-2101) -----
    if not forced_key and soulable and "c_soul" not in banned:
        if type_ in ("Tarot", "Spectral", "Tarot_Planet") and not _joker_seen(run, "c_soul"):
            if rng.roll("soul_%s%d" % (type_, ante)) > SOUL_CHANCE:
                forced_key = "c_soul"
        if type_ in ("Planet", "Spectral") and not _joker_seen(run, "c_black_hole"):
            if rng.roll("soul_%s%d" % (type_, ante)) > SOUL_CHANCE:
                forced_key = "c_black_hole"

    if type_ == "Base":
        forced_key = "c_base"

    centers = _centers()
    if forced_key and forced_key not in banned:
        center = dict(centers.get(forced_key) or {})
        center.setdefault("key", forced_key)
        set_ = center.get("set")
        if set_ and set_ != "Default":
            type_ = set_                      # Tarot->Spectral for The Soul, ...
    else:
        pool, pool_key = get_current_pool(run, type_, rarity, legendary, key_append)
        picked = _pick_pool(run, pool, pool_key, type_)
        center = dict(centers.get(picked) or {})
        center.setdefault("key", picked)

    key = center.get("key")
    set_ = center.get("set")
    is_playing = set_ in PLAYING_CARD_SETS

    if is_playing:
        rank, suit = _front(run, key_append, ante)
        enhancement = key if set_ == "Enhanced" else None
        return Card(rank, suit, enhancement=enhancement, edition=edition)

    if type_ == "Joker" and edition is None:
        edition = poll_edition(run, "edi" + (key_append or "") + str(ante))
    return JokerCard(key, name=center.get("name", ""), cfg=center.get("config") or {},
                     edition=edition, rarity=center.get("rarity", 1) or 1,
                     cost=center.get("cost", 0) or 0, set_=set_ or "Joker")


# ---------------------------------------------------------------------------
# booster packs
# ---------------------------------------------------------------------------

def get_pack(run, kind=None, ante=None) -> str | None:
    """Port of ``get_pack`` (common_events.lua:1944): a weighted booster key.

    ``kind`` filters on a booster's ``kind`` (``Arcana``/``Celestial``/
    ``Spectral``/``Standard``/``Buffoon``); ``None`` means any.  The very first
    call of a run always returns a normal Buffoon pack (Lua's
    ``G.GAME.first_shop_buffoon``), and it sets that flag on the run.
    Returns ``None`` when every candidate is banned (Lua returns nil).
    """
    ante = _ante(run) if ante is None else int(ante)
    banned = _banned(run)

    if (not getattr(run, "first_shop_buffoon", False)
            and FIRST_SHOP_BUFFOON[0] not in banned):
        run.first_shop_buffoon = True
        return run.rng.pick("first_shop_buffoon", list(FIRST_SHOP_BUFFOON))

    pool, weights = [], []
    for entry in _pools().get("Booster") or []:
        if kind and entry.get("kind") != kind:
            continue
        if entry.get("key") in banned:
            continue
        pool.append(entry.get("key"))
        weights.append(entry.get("weight", 1) or 1)
    if not pool:
        return None
    return run.rng.weighted_pick("pack_generic" + str(ante), pool, weights)


def _key_of(pack) -> str:
    if isinstance(pack, str):
        return pack
    return getattr(pack, "key", None) or ""


def _most_played_hand(run) -> str | None:
    """``G.handlist`` scan for the most played *visible* hand (card.lua:1739)."""
    levels = getattr(run, "hand_levels", None) or {}
    best, tally = None, 0
    for name, entry in sorted(levels.items(),
                              key=lambda kv: (kv[1] or {}).get("order", 99)):
        entry = entry or {}
        if not entry.get("visible", True):
            continue
        played = _hands_played(run, name)
        if played > tally:
            best, tally = name, played
    return best


def _planet_for_hand(run, hand: str | None) -> str | None:
    """``v_telescope``: the planet center whose ``config.hand_type`` is ``hand``."""
    if not hand:
        return None
    for entry in _pools().get("Planet") or []:
        if (entry.get("config") or {}).get("hand_type") == hand:
            return entry.get("key")
    return None


def _pack_card(run, kind: str, index: int):
    """One ``Card:open`` draw (card.lua:1728-1776); ``index`` is 1-based."""
    ante = _ante(run)
    redeemed = _redeemed(run)

    if kind == "Arcana":
        if "v_omen_globe" in redeemed and run.rng.roll("omen_globe") > OMEN_GLOBE_ODDS:
            return create_card(run, "Spectral", soulable=True, key_append="ar2")
        return create_card(run, "Tarot", soulable=True, key_append="ar1")

    if kind == "Celestial":
        forced = None
        if "v_telescope" in redeemed and index == 1:
            forced = _planet_for_hand(run, _most_played_hand(run))
        return create_card(run, "Planet", soulable=True, forced_key=forced,
                           key_append="pl1")

    if kind == "Spectral":
        return create_card(run, "Spectral", soulable=True, key_append="spe")

    if kind == "Standard":
        mode = ("Enhanced" if run.rng.roll("stdset" + str(ante)) > STANDARD_ENHANCED_ODDS
                else "Base")
        card = create_card(run, mode, soulable=True, key_append="sta")
        ed = poll_edition(run, "standard_edition" + str(ante),
                          STANDARD_EDITION_RATE, True)
        if ed:
            card.edition = ed
        if run.rng.roll("stdseal" + str(ante)) > 1 - 0.02 * STANDARD_SEAL_RATE:
            seal_poll = run.rng.roll("stdsealtype" + str(ante))
            if seal_poll > 0.75:
                card.seal = normalize_seal("red")
            elif seal_poll > 0.5:
                card.seal = normalize_seal("blue")
            elif seal_poll > 0.25:
                card.seal = normalize_seal("gold")
            else:
                card.seal = normalize_seal("purple")
        return card

    if kind == "Buffoon":
        return create_card(run, "Joker", soulable=True, key_append="buf")

    return None


def open_pack(run, pack_key) -> dict:
    """Port of opening a booster (``Card:open``, card.lua:1681).

    ``config.extra`` cards are drawn - Arcana from Tarot (Omen Globe can swap in
    Spectral), Celestial from Planet (Telescope forces the most played hand's
    planet on the first card), Spectral from Spectral, Standard from Base/
    Enhanced playing cards (with editions and seals), Buffoon from Joker.
    ``config.choose`` is how many of them the player may take.

    ``cost`` is the center's price; the caller charges for the pack (the shop
    already did, exactly like ``Shop.buy``), so nothing is deducted here.
    Returns ``{"ok", "key", "kind", "cards", "choose", "cost", ...}``; ``ok`` is
    False (with ``"error"``) when the key is not a Booster.
    """
    key = _key_of(pack_key)
    center = _centers().get(key) or {}
    cfg = center.get("config") or {}
    extra = int(cfg.get("extra", 0) or 0)
    state = {"ok": False, "key": key, "kind": center.get("kind") or "",
             "name": center.get("name", ""), "cards": [],
             "choose": int(cfg.get("choose", 1) or 1), "extra": extra,
             "cost": int(center.get("cost", 0) or 0), "taken": [], "closed": False}
    if center.get("set") != "Booster":
        state["choose"] = 0
        state["error"] = "not a booster pack"
        return state

    kind = state["kind"]
    cards = []
    for i in range(1, extra + 1):
        card = _pack_card(run, kind, i)
        if card is not None:
            cards.append(card)
    state["cards"] = cards
    state["ok"] = True
    return state


def pack_choices(run, pack_key) -> list:
    """The cards a booster offers: ``open_pack``'s ``cards``.

    Accepts a pack state dict (then it is simply read) or a booster key (then the
    pack is drawn, advancing the RNG exactly once).
    """
    if isinstance(pack_key, dict):
        return list(pack_key.get("cards") or [])
    return list(open_pack(run, pack_key).get("cards") or [])


def _slot_limit(run, param: str):
    params = getattr(run, "params", None) or {}
    return params.get(param)


def _place(run, card, check: bool = False) -> bool:
    """Move a pack card into the run.  ``check`` only asks whether it would fit."""
    key = getattr(card, "key", None)
    if not key:                                     # a playing card
        return True
    set_ = (getattr(card, "ability", {}) or {}).get("set")
    if set_ == "Joker":
        slots, adder, area = "joker_slots", "add_joker", "jokers"
    elif set_ in CONSUMABLE_SETS:
        slots, adder, area = "consumable_slots", "add_consumable", "consumeables"
    else:
        return False

    limit = _slot_limit(run, slots)
    target = getattr(run, area, None)
    if limit is not None and target is not None and len(target) >= limit:
        return False

    fn = getattr(run, adder, None)
    if check:
        return True
    if callable(fn):
        return fn(key, getattr(card, "edition", None)) is not None
    if target is None:
        return False
    target.append(card)
    return True


def take_from_pack(run, pack_state, indices) -> dict:
    """Take ``indices`` (0-based) from an :func:`open_pack` state.

    Picks at most ``choose`` cards and moves each into the run (jokers/consumables
    through ``run.add_joker``/``run.add_consumable`` when available, playing cards
    onto ``run.deck``).  Nothing is moved when a selected card does not fit or the
    selection is too large - the pack state is then untouched.  Taken cards leave
    the pack; it closes once ``choose`` cards were taken.
    """
    cards = list(pack_state.get("cards") or []) if isinstance(pack_state, dict) else []
    choose = int(pack_state.get("choose", 1) or 1) if isinstance(pack_state, dict) else 0

    picked: list[int] = []
    for raw in indices or ():
        try:
            i = int(raw)
        except (TypeError, ValueError):
            continue
        if 0 <= i < len(cards) and i not in picked:
            picked.append(i)
    if len(picked) > choose:
        return {"ok": False, "error": "choose at most %d" % choose,
                "taken": [], "choose": choose}

    chosen = [cards[i] for i in picked]
    if not all(_place(run, c, check=True) for c in chosen):
        return {"ok": False, "error": "no space", "taken": [], "choose": choose}

    taken = []
    for card in chosen:
        if _place(run, card):
            taken.append(card)

    if isinstance(pack_state, dict):
        pack_state["cards"] = [c for n, c in enumerate(cards) if n not in picked]
        pack_state["taken"] = taken
        pack_state["closed"] = len(taken) >= choose
    return {"ok": True, "taken": taken, "count": len(taken), "choose": choose,
            "key": pack_state.get("key") if isinstance(pack_state, dict) else None,
            "closed": bool(isinstance(pack_state, dict) and pack_state.get("closed"))}


# ---------------------------------------------------------------------------
# vouchers / tags
# ---------------------------------------------------------------------------

def random_voucher_key(run, from_tag=False) -> str:
    """Port of ``get_next_voucher_key`` (common_events.lua:1901).

    Picks from the Voucher pool, which :func:`get_current_pool` has already culled
    of redeemed vouchers and unmet ``requires`` - so the result is never an
    already-owned voucher.  ``from_tag`` uses the ``'Voucher_fromtag'`` seed (a
    tag-reward voucher, which excludes the ante suffix) like the Lua.
    """
    pool, pool_key = get_current_pool(run, "Voucher")
    if from_tag:
        pool_key = "Voucher_fromtag"
    return _pick_pool(run, pool, pool_key, "Voucher")


def random_tag_key(run, append="") -> str:
    """Port of ``get_next_tag_key`` (common_events.lua:1914).

    ``run.force_tag`` (``G.FORCE_TAG``) wins.  Otherwise the Tag pool comes from
    :mod:`balatro_cli.engine.tags` when it is available - ``tag_pool(ante)``
    applies the ``min_ante`` cull - and the draw keeps the Lua seed key
    ``'Tag' .. append .. ante``.  Without that module the pool is built inline
    from ``P_CENTER_POOLS['Tag']`` (data/tags.json, or :data:`INLINE_TAGS`) with
    the ``min_ante``/``requires`` cull of :func:`get_current_pool`.
    """
    forced = getattr(run, "force_tag", None)
    if forced:
        return forced

    ante = _ante(run)
    try:
        from . import tags as tags_mod
    except Exception:
        tags_mod = None

    if tags_mod is not None:
        # A dedicated get_next_tag_key port wins; tags.random_tag() takes a
        # different (ante, blind_kind) signature, so it is not called here.
        for name in ("random_tag_key", "random_key"):
            fn = getattr(tags_mod, name, None)
            if callable(fn):
                return fn(run, append)
        pool_fn = getattr(tags_mod, "tag_pool", None)
        if callable(pool_fn):
            try:
                available = [k for k in (pool_fn(ante) or ()) if k not in _banned(run)]
            except Exception:
                available = []
            if available:
                return run.rng.pick("Tag" + (append or "") + str(ante), available)

    pool, pool_key = get_current_pool(run, "Tag", None, None, append)
    return _pick_pool(run, pool, pool_key, "Tag")
