"""Tarot / Planet / Spectral consumable effects.

A port of ``card.lua:Card:use_consumeable`` (1091-1521) plus the usability gate
``Card:can_use_consumeable`` (1523-1579) and ``Card:check_use`` (1581-1588).

Public API
----------
``use(run, key, targets=None) -> dict``
    Apply one consumable's effect.  ``targets`` are the highlighted hand cards
    (Lua ``G.hand.highlighted``), in hand order.  Returns
    ``{"ok": True, "kind": "tarot"|"planet"|"spectral", "key": key, ...details}``
    or ``{"ok": False, "kind": ..., "key": key, "error": "..."}``.
``can_use(run, key, targets=None) -> bool``
    Mirror of ``Card:can_use_consumeable`` for the states this engine has.

Every consumable in ``centers.json`` whose ``set`` is Tarot/Planet/Spectral is
implemented; a key that ever falls through to the "no handler" branch is added
to the module level :data:`UNIMPLEMENTED` set and reported as
``{"ok": False, ..., "error": "not implemented: <key>"}``.

Faithfulness notes
------------------
* Dispatch order follows the Lua: ``config.mod_conv`` / ``config.suit_conv``
  first (this is where Death / Strength live), then the named effects, then
  ``config.hand_type`` (planets) and ``config.remove_card``.
* ``Card:set_ability`` (223) is mirrored by :func:`_set_enhancement`, including
  the ``config.Xmult`` -> ``ability.x_mult`` rename the scoring code expects.
* ``Death`` copies the *rightmost* highlighted card (Lua compares ``T.x``);
  this engine has no layout, so the last entry of ``targets`` is "rightmost".
* ``set_consumeable_usage`` (misc_functions.lua:1212) is applied *after* the
  effect, so The Fool still reads the previously used Tarot/Planet.
* The ``using_consumeable`` joker hook is fired by the button callback
  (button_callbacks.lua:2219) and therefore not here; the
  ``remove_playing_cards`` hook *is* inside ``use_consumeable`` and is fired.
"""

from __future__ import annotations

import copy as _copy

from ..data import loader
from . import hooks
from .card import (ID_RANKS, RANK_IDS, Card, JokerCard, enhancement_config,
                   normalize_seal)

CONSUMABLE_SETS = ("Tarot", "Planet", "Spectral")

#: Keys that reached the "no handler" branch (empty when fully implemented).
UNIMPLEMENTED: set[str] = set()

# config.mod_conv values that upgrade a card's enhancement (card.lua:1143)
ENHANCEMENT_MOD_CONV = frozenset({
    "m_lucky", "m_wild", "m_mult", "m_bonus", "m_glass", "m_steel",
    "m_stone", "m_gold",
})

# config.extra of the seal spectrals -> Card.seal (card.lua:1186)
SEAL_KEYS = {"Gold": "gold", "Red": "red", "Blue": "blue", "Purple": "purple"}

SUIT_TO_LETTER = {"Spades": "S", "Hearts": "H", "Diamonds": "D", "Clubs": "C"}
SUITS = ("S", "H", "D", "C")
LOW_RANKS = ("2", "3", "4", "5", "6", "7", "8", "9", "T")
FACE_RANKS = ("J", "Q", "K")
ALL_RANKS = LOW_RANKS + FACE_RANKS + ("A",)

# pools that are never handed out by create_card (common_events.lua:2022)
NEVER_IN_POOL = frozenset({"c_soul", "c_black_hole"})

# get_current_pool fallback when every entry is unavailable (common_events.lua:2039)
FALLBACK_POOL_KEY = {"Tarot": "c_strength", "Planet": "c_pluto",
                     "Spectral": "c_incantation", "Tarot_Planet": "c_strength",
                     "Joker": "j_joker"}

# deterministic rng stream for the edition spectrals (card.lua:1473)
_EDITION_SEED = {"The Wheel of Fortune": "wheel_of_fortune",
                 "Ectoplasm": "ectoplasm", "Hex": "hex"}


# ---------------------------------------------------------------------------
# small result helpers
# ---------------------------------------------------------------------------

def _ok(key: str, kind: str, **details) -> dict:
    out = {"ok": True, "kind": kind, "key": key}
    out.update(details)
    return out


def _fail(key: str, kind: str | None, error: str, **details) -> dict:
    out = {"ok": False, "key": key, "error": error}
    if kind:
        out["kind"] = kind
    out.update(details)
    return out


# ---------------------------------------------------------------------------
# center/data helpers
# ---------------------------------------------------------------------------

def centers() -> dict:
    return loader.centers()


def keys(set_name: str | None = None) -> list[str]:
    """Every consumable key, optionally filtered to one set."""
    out = []
    for key, center in centers().items():
        if not isinstance(center, dict):
            continue
        s = center.get("set")
        if s not in CONSUMABLE_SETS:
            continue
        if set_name is None or s == set_name:
            out.append(key)
    return out


def _center(key) -> dict:
    if isinstance(key, dict):
        return key
    if isinstance(key, str):
        return centers().get(key) or {}
    return {}


def _config(key) -> dict:
    return dict(_center(key).get("config") or {})


def _kind(key) -> str | None:
    s = _center(key).get("set")
    return s.lower() if s in CONSUMABLE_SETS else None


def _name(key) -> str:
    return _center(key).get("name") or (key if isinstance(key, str) else "")


def _hand_levels(run) -> dict:
    levels = getattr(run, "hand_levels", None)
    return levels if isinstance(levels, dict) else {}


def _hand_level(run, hand: str):
    entry = _hand_levels(run).get(hand) or {}
    return entry.get("level")


def _banned(run) -> set:
    banned = getattr(run, "banned_keys", None)
    return set(banned) if banned else set()


def _ante(run) -> int:
    try:
        return int(getattr(run, "ante", 1) or 1)
    except (TypeError, ValueError):
        return 1


def _card_list(run, name: str) -> list:
    lst = getattr(run, name, None)
    return lst if isinstance(lst, list) else []


def _jokers(run) -> list:
    return _card_list(run, "jokers")


def _hand(run) -> list:
    return _card_list(run, "hand")


def _joker_key(j) -> str:
    if isinstance(j, str):
        return j
    return getattr(j, "key", "") or ""


def _is_joker(j) -> bool:
    """Lua ``v.ability.set == 'Joker'``."""
    if isinstance(j, str):
        return _center(j).get("set") == "Joker"
    ability = getattr(j, "ability", None) or {}
    if ability.get("set"):
        return ability.get("set") == "Joker"
    return bool(getattr(j, "is_joker", False))


def _edition(card):
    return getattr(card, "edition", None)


def _is_eternal(j) -> bool:
    if isinstance(j, str):
        return bool(_config(j).get("eternal"))
    ability = getattr(j, "ability", None) or {}
    return bool(ability.get("eternal"))


def _joker_limit(run) -> int:
    """Joker slots, including the +1 each Negative joker grants (card.lua:630)."""
    params = getattr(run, "params", None) or {}
    try:
        limit = int(params.get("joker_slots", 5))
    except (TypeError, ValueError):
        limit = 5
    limit += sum(1 for j in _jokers(run) if _edition(j) == "e_negative")
    return limit


def _free_joker_slots(run) -> int:
    return max(0, _joker_limit(run) - len(_jokers(run)))


def _consumable_limit(run) -> int:
    limit = getattr(run, "consumable_slots", None)
    if limit is None:
        params = getattr(run, "params", None) or {}
        limit = params.get("consumable_slots", 2)
    try:
        return int(limit)
    except (TypeError, ValueError):
        return 2


def _free_consumable_slots(run) -> int:
    return max(0, _consumable_limit(run) - len(_card_list(run, "consumeables")))


def _joker_sell_cost(run, j) -> int:
    """Card:set_cost sell_cost (card.lua:382) - the run's canonical value."""
    sell = getattr(run, "sell_value", None)
    if callable(sell):
        return int(sell(j))
    sc = getattr(j, "sell_cost", None)
    if isinstance(sc, (int, float)):
        return int(sc)
    center = _center(j) if isinstance(j, str) else {}
    return max(1, int(center.get("cost", 2) or 2) // 2)


# ---------------------------------------------------------------------------
# run mutations (tolerant: the run API may be partially implemented)
# ---------------------------------------------------------------------------

def _level_up(run, hand: str, amount: int = 1):
    """``level_up_hand`` (common_events.lua:464)."""
    fn = getattr(run, "level_up_hand", None)
    if callable(fn):
        fn(hand, amount)
    else:
        entry = _hand_levels(run).get(hand)
        if isinstance(entry, dict):
            entry["level"] = max(0, int(entry.get("level", 1) or 0) + amount)
            lvl = entry["level"]
            if "s_mult" in entry:
                entry["mult"] = max(entry["s_mult"] + entry.get("l_mult", 0) * (lvl - 1), 1)
            if "s_chips" in entry:
                entry["chips"] = max(entry["s_chips"] + entry.get("l_chips", 0) * (lvl - 1), 0)
    return _hand_level(run, hand)


def _add_dollars(run, amount: int) -> int:
    if not amount:
        return int(getattr(run, "dollars", 0) or 0)
    run.dollars = int(getattr(run, "dollars", 0) or 0) + int(amount)
    return run.dollars


def _change_hand_size(run, delta: int) -> None:
    size = getattr(run, "hand_size", None)
    if isinstance(size, (int, float)):
        run.hand_size = max(0, int(size) + int(delta))


def _last_tarot_planet(run):
    val = getattr(run, "last_tarot_planet", None)
    if val:
        return val
    for holder in (getattr(run, "current_round", None), getattr(run, "pool_flags", None)):
        if isinstance(holder, dict) and holder.get("last_tarot_planet"):
            return holder["last_tarot_planet"]
    return None


def _set_last_tarot_planet(run, key: str) -> None:
    try:
        run.last_tarot_planet = key
        return
    except AttributeError:
        pass
    for holder in (getattr(run, "current_round", None), getattr(run, "pool_flags", None)):
        if isinstance(holder, dict):
            holder["last_tarot_planet"] = key
            return


def _destroy(run, card) -> None:
    """``Card:start_dissolve`` / ``shatter`` (card.lua:2079/2130)."""
    fn = getattr(run, "playing_card_destroyed", None)
    if callable(fn):
        fn(card)
        return
    for area in (_hand(run), _card_list(run, "deck")):
        if card in area:
            area.remove(card)
    played = getattr(run, "played", None)
    if isinstance(played, list):
        played.append(card)


def _fire(run, event: str, **kwargs) -> None:
    fn = getattr(run, "eval_hooks", None)
    if not callable(fn):
        return
    try:
        fn(event, **kwargs)
    except TypeError:
        pass


def _destroy_all(run, cards) -> list:
    """Destroy cards and fire the ``remove_playing_cards`` hook once (card.lua:1369)."""
    cards = [c for c in cards if c is not None]
    for card in cards:
        _destroy(run, card)
    if cards:
        _fire(run, hooks.HOOK_REMOVE_PLAYING_CARDS,
              other_card=cards[-1], extra={"removed": list(cards)})
    return cards


def _add_playing_card(run, card) -> None:
    """Emplace a freshly created playing card into the hand (card.lua:1336)."""
    hand = getattr(run, "hand", None)
    if isinstance(hand, list):
        hand.append(card)
    _fire(run, hooks.HOOK_PLAYING_CARD_ADDED, other_card=card)


def _add_consumable(run, key: str):
    fn = getattr(run, "add_consumable", None)
    if callable(fn):
        return fn(key)
    created = _create_card(run, _center(key).get("set") or "Tarot", key=key)
    if created is None:
        created = key
    consumeables = getattr(run, "consumeables", None)
    if isinstance(consumeables, list):
        consumeables.append(created)
    return created


def _add_joker(run, key: str, edition: str | None = None):
    fn = getattr(run, "add_joker", None)
    if callable(fn):
        try:
            return fn(key, edition=edition)
        except TypeError:
            return fn(key)
    created = _create_card(run, "Joker", key=key, edition=edition)
    if created is None:
        created = JokerCard(key, _name(key), _config(key), edition=edition)
    _jokers(run).append(created)
    return created


def _create_card(run, kind: str, **kwargs):
    fn = getattr(run, "create_card", None)
    if not callable(fn):
        return None
    for attempt in (dict(kwargs), {}):
        try:
            return fn(kind, **attempt)
        except TypeError:
            continue
    return None


def _remove_joker(run, joker) -> None:
    lst = _jokers(run)
    if joker not in lst:
        return
    idx = lst.index(joker)
    fn = getattr(run, "remove_joker", None)
    if callable(fn):
        fn(idx)
    else:
        lst.pop(idx)


def _with_edition(run, joker, edition: str):
    """``Card:set_edition``; bare key jokers are swapped for a JokerCard carrier."""
    if not isinstance(joker, str):
        try:
            joker.edition = edition
            return joker
        except AttributeError:
            pass
    center = _center(joker) if isinstance(joker, str) else {}
    carrier = JokerCard(_joker_key(joker), center.get("name", ""),
                        center.get("config"), edition=edition,
                        rarity=center.get("rarity", 1), cost=center.get("cost", 0))
    lst = _jokers(run)
    for i, existing in enumerate(lst):
        if existing is joker:
            lst[i] = carrier
            break
    return carrier


# ---------------------------------------------------------------------------
# card mutations
# ---------------------------------------------------------------------------

def _set_enhancement(card, enhancement: str) -> None:
    """``Card:set_ability`` for an Enhanced center (card.lua:277-303)."""
    ability = dict(enhancement_config(enhancement))
    # Lua reads center.config.Xmult into ability.x_mult
    if "x_mult" not in ability:
        ability["x_mult"] = ability.get("Xmult", 1) or 1
    old = getattr(card, "ability", None) or {}
    if old.get("perma_bonus"):
        ability["perma_bonus"] = old["perma_bonus"]
    card.enhancement = enhancement
    card.ability = ability


def _copy_onto(source, dest) -> None:
    """``copy_card(source, dest)`` (common_events.lua:2156)."""
    dest.rank = source.rank
    dest.suit = source.suit
    dest.enhancement = source.enhancement
    dest.edition = source.edition
    dest.seal = source.seal
    if hasattr(dest, "ability") and hasattr(source, "ability"):
        dest.ability = _copy.deepcopy(source.ability)
    if hasattr(dest, "debuffed"):
        dest.debuffed = bool(getattr(source, "debuffed", False))


def _rank_up(rank: str):
    """card.lua:1126 - Ace wraps to 2, everything else steps up."""
    cid = RANK_IDS.get(rank)
    if cid is None:
        return None
    nxt = 2 if cid == 14 else min(cid + 1, 14)
    return ID_RANKS.get(nxt)


def _poll_edition(run, seed_key: str, mod: int = 1, no_neg: bool = False,
                  guaranteed: bool = False):
    """``poll_edition`` (common_events.lua:2055) -> edition key or None."""
    poll = run.rng.roll(seed_key)
    if guaranteed:
        if poll > 1 - 0.003 * 25 and not no_neg:
            return "e_negative"
        if poll > 1 - 0.006 * 25:
            return "e_polychrome"
        if poll > 1 - 0.02 * 25:
            return "e_holo"
        if poll > 1 - 0.04 * 25:
            return "e_foil"
        return None
    rate = getattr(run, "edition_rate", 1) or 1
    if poll > 1 - 0.003 * mod and not no_neg:
        return "e_negative"
    if poll > 1 - 0.006 * rate * mod:
        return "e_polychrome"
    if poll > 1 - 0.02 * rate * mod:
        return "e_holo"
    if poll > 1 - 0.04 * rate * mod:
        return "e_foil"
    return None


# ---------------------------------------------------------------------------
# pools (common_events.lua:get_current_pool / create_card)
# ---------------------------------------------------------------------------

def _has_free_planet(run, center: dict) -> bool:
    cfg = center.get("config") or {}
    if not cfg.get("softlock"):
        return True
    entry = _hand_levels(run).get(cfg.get("hand_type")) or {}
    return int(entry.get("played", 0) or 0) > 0


def _pick_consumable_key(run, set_name: str):
    pool = [c for c in loader.pools().get(set_name, []) if c.get("key")]
    banned = _banned(run)
    pool = [c for c in pool if c["key"] not in banned and c["key"] not in NEVER_IN_POOL]
    if set_name == "Planet":
        pool = [c for c in pool if _has_free_planet(run, c)]
    pool_keys = [c["key"] for c in pool]
    if not pool_keys:
        pool_keys = [FALLBACK_POOL_KEY.get(set_name, "j_joker")]
    return run.rng.pick(f"{set_name}{_ante(run)}", pool_keys)


def _pick_joker_key(run, legendary: bool = False, rarity=None, append: str = ""):
    pools = loader.pools()
    if legendary:
        rarity_idx = 4
        pool = pools["JokerRarity"][4]
    else:
        roll = rarity if rarity is not None else run.rng.roll(f"rarity{_ante(run)}{append}")
        rarity_idx = 3 if roll > 0.95 else (2 if roll > 0.7 else 1)
        pool = pools["JokerRarity"][rarity_idx]
    banned = _banned(run)
    pool_keys = [c["key"] for c in pool if c.get("key") and c["key"] not in banned]
    if not pool_keys:
        pool_keys = [FALLBACK_POOL_KEY["Joker"]]
    return run.rng.pick(f"Joker{rarity_idx}{append}", pool_keys)


def _random_enhancement(run) -> str:
    pool = [c["key"] for c in loader.pools()["Enhanced"]
            if c.get("key") and c["key"] != "m_stone"]
    if not pool:
        return "m_bonus"
    return run.rng.pick("spe_card", pool)


def _random_front(run, name: str):
    if name == "Familiar":
        rank = run.rng.pick("familiar_create_rank", list(FACE_RANKS))
        suit = run.rng.pick("familiar_create_suit", list(SUITS))
    elif name == "Grim":
        rank = "A"
        suit = run.rng.pick("grim_create", list(SUITS))
    else:  # Incantation
        rank = run.rng.pick("incantation_create_rank", list(LOW_RANKS))
        suit = run.rng.pick("incantation_create_suit", list(SUITS))
    return rank, suit


# ---------------------------------------------------------------------------
# highlight validation (config.max_highlighted / config.min_highlighted)
# ---------------------------------------------------------------------------

def _highlight_spec(name: str, cfg: dict):
    """(min, max) highlighted cards, or None when the consumable takes none."""
    if name == "Aura":
        # Aura's center has an empty config but can_use demands exactly 1 card
        return 1, 1
    if "max_highlighted" not in cfg:
        return None
    try:
        hi = int(cfg["max_highlighted"])
    except (TypeError, ValueError):
        return None
    try:
        lo = int(cfg.get("min_highlighted", 1) or 1)
    except (TypeError, ValueError):
        lo = 1
    return lo, hi


def _validate_targets(name: str, cfg: dict, targets: list) -> str | None:
    spec = _highlight_spec(name, cfg)
    if spec is None:
        return None
    lo, hi = spec
    n = len(targets)
    if n < lo:
        return f"needs {lo} highlighted card(s), got {n}"
    if n > hi:
        return f"at most {hi} highlighted card(s), got {n}"
    return None


# ---------------------------------------------------------------------------
# can_use (card.lua:1523)
# ---------------------------------------------------------------------------

def _editionless_jokers(run) -> list:
    return [j for j in _jokers(run) if _is_joker(j) and not _edition(j)]


def can_use(run, key: str, targets: list | None = None) -> bool:
    center = _center(key)
    if center.get("set") not in CONSUMABLE_SETS:
        return False
    cfg = dict(center.get("config") or {})
    name = center.get("name") or key
    targets = list(targets or [])
    if _validate_targets(name, cfg, targets):
        return False

    # -- always usable from the consumable area (card.lua:1530)
    if name in ("The Hermit", "Temperance", "Black Hole") or cfg.get("hand_type"):
        return True
    if name in ("The Emperor", "The High Priestess"):
        return True  # the used card itself occupies G.consumeables
    if name == "The Wheel of Fortune":
        return bool(_editionless_jokers(run))
    if name in ("Ectoplasm", "Hex"):
        return bool(_editionless_jokers(run))
    if name == "Ankh":
        return bool(_jokers(run)) and _joker_limit(run) > 1
    if name == "Aura":
        return len(targets) == 1 and not _edition(targets[0])
    if name == "The Fool":
        last = _last_tarot_planet(run)
        return bool(last) and last != "c_fool"
    if name in ("Judgement", "The Soul", "Wraith"):
        return _free_joker_slots(run) > 0
    if name in ("Familiar", "Grim", "Incantation", "Immolate", "Sigil", "Ouija"):
        return len(_hand(run)) > 1
    return True


# ---------------------------------------------------------------------------
# effect handlers
# ---------------------------------------------------------------------------

def _planet(run, key, kind, name, cfg, targets):
    hand = cfg["hand_type"]
    if hand not in _hand_levels(run):
        return _fail(key, kind, f"unknown hand: {hand}")
    _level_up(run, hand, 1)
    return _ok(key, kind, hand=hand, level=_hand_level(run, hand), amount=1)


def _mod_conv(run, key, kind, name, cfg, targets):
    conv = cfg["mod_conv"]

    if conv == "card":  # Death (card.lua:1111)
        source = targets[-1]
        copied = 0
        for dest in targets:
            if dest is source:
                continue
            _copy_onto(source, dest)
            copied += 1
        return _ok(key, kind, effect="card", copied=copied, n=len(targets),
                   source=source.rank + str(source.suit))

    if conv == "up_rank":  # Strength (card.lua:1121)
        ranks = []
        for card in targets:
            new_rank = _rank_up(getattr(card, "rank", ""))
            if new_rank:
                card.rank = new_rank
            ranks.append(new_rank or getattr(card, "rank", ""))
        return _ok(key, kind, effect="up_rank", ranks=ranks, n=len(targets))

    if conv in ENHANCEMENT_MOD_CONV:  # card.lua:1141
        for card in targets:
            _set_enhancement(card, conv)
        return _ok(key, kind, enhance=conv, n=len(targets))

    UNIMPLEMENTED.add(key)
    return _fail(key, kind, f"not implemented: {key}")


def _suit_conv(run, key, kind, name, cfg, targets):
    # card.lua:1137 (The Star / The Moon / The Sun / The World)
    suit = SUIT_TO_LETTER.get(cfg["suit_conv"])
    if not suit:
        UNIMPLEMENTED.add(key)
        return _fail(key, kind, f"not implemented: {key}")
    for card in targets:
        card.suit = suit
    return _ok(key, kind, suit=suit, n=len(targets))


def _destroy_targets(run, key, kind, name, cfg, targets):
    # The Hanged Man (card.lua:1271)
    destroyed = _destroy_all(run, targets)
    return _ok(key, kind, destroyed=len(destroyed), n=len(destroyed))


def _black_hole(run, key, kind, name, cfg, targets):
    # card.lua:1153 - level up every poker hand
    levels = _hand_levels(run)
    for hand in list(levels):
        _level_up(run, hand, 1)
    return _ok(key, kind, n=len(levels))


def _seal(run, key, kind, name, cfg, targets):
    # Talisman / Deja Vu / Trance / Medium (card.lua:1178)
    seal = SEAL_KEYS.get(str(cfg.get("extra")))
    if not seal:
        UNIMPLEMENTED.add(key)
        return _fail(key, kind, f"not implemented: {key}")
    card = targets[0]
    card.seal = normalize_seal(seal)
    return _ok(key, kind, seal=seal, n=1)


def _aura(run, key, kind, name, cfg, targets):
    # card.lua:1192 - guaranteed edition, never negative
    edition = _poll_edition(run, "aura", no_neg=True, guaranteed=True)
    _with_edition(run, targets[0], edition)
    return _ok(key, kind, edition=edition, n=1)


def _cryptid(run, key, kind, name, cfg, targets):
    # card.lua:1201 - copy the highlighted card N times into the hand
    source = targets[0]
    count = int(cfg.get("extra") or 0)
    for _ in range(max(0, count)):
        if hasattr(source, "copy"):
            new_card = source.copy()
        else:
            new_card = Card(source.rank, source.suit, source.enhancement,
                            source.edition, source.seal)
        _add_playing_card(run, new_card)
        # card.lua:1210 - each copy raises the deck's card_limit
        if isinstance(getattr(run, "params", None), dict):
            run.params["deck_limit"] = run.params.get("deck_limit", 52) + 1
    return _ok(key, kind, copies=max(0, count), n=max(0, count))


def _sigil(run, key, kind, name, cfg, targets):
    # card.lua:1232 - every card in hand becomes one random suit
    suit = run.rng.pick("sigil", list(SUITS))
    hand = _hand(run)
    for card in hand:
        card.suit = suit
    return _ok(key, kind, suit=suit, n=len(hand))


def _ouija(run, key, kind, name, cfg, targets):
    # card.lua:1246 - every card in hand becomes one random rank, hand size -1
    rank = run.rng.pick("ouija", list(ALL_RANKS))
    hand = _hand(run)
    for card in hand:
        card.rank = rank
    _change_hand_size(run, -1)
    return _ok(key, kind, rank=rank, hand_size=getattr(run, "hand_size", None),
               n=len(hand))


def _destroy_and_create(run, key, kind, name, cfg, targets):
    # Familiar / Grim / Incantation (card.lua:1292)
    hand = _hand(run)
    if len(hand) < 2:
        return _fail(key, kind, "needs at least 2 cards in hand")
    victim = run.rng.pick("random_destroy", list(hand))
    _destroy_all(run, [victim])
    created = []
    for _ in range(max(0, int(cfg.get("extra") or 0))):
        rank, suit = _random_front(run, name)
        card = Card(rank, suit, _random_enhancement(run))
        _add_playing_card(run, card)
        created.append(f"{card.rank}{card.suit}")
    return _ok(key, kind, destroyed=1, created=created, n=len(created))


def _immolate(run, key, kind, name, cfg, targets):
    # card.lua:1340 - destroy N random cards, gain dollars
    extra = cfg.get("extra") or {}
    count = max(0, int(extra.get("destroy", 0) or 0))
    dollars = int(extra.get("dollars", 0) or 0)
    order = run.rng.shuffle("immolate", list(_hand(run)))
    destroyed = _destroy_all(run, order[:count])
    _add_dollars(run, dollars)
    return _ok(key, kind, destroyed=len(destroyed), dollars=dollars)


def _the_fool(run, key, kind, name, cfg, targets):
    # card.lua:1373 - recreate the last used Tarot/Planet (never The Fool)
    last = _last_tarot_planet(run)
    if not last or last == "c_fool":
        return _fail(key, kind, "no previous Tarot/Planet to create")
    if _free_consumable_slots(run) <= 0:
        return _ok(key, kind, created=None)
    _add_consumable(run, last)
    return _ok(key, kind, created=last)


def _the_hermit(run, key, kind, name, cfg, targets):
    # card.lua:1385 - add min(dollars, 20)
    cap = int(cfg.get("extra", 20) or 0)
    amount = max(0, min(int(getattr(run, "dollars", 0) or 0), cap))
    _add_dollars(run, amount)
    return _ok(key, kind, dollars=amount, money=amount)


def _temperance(run, key, kind, name, cfg, targets):
    # card.lua:1393 - add the summed sell value of owned jokers, capped
    cap = int(cfg.get("extra", 50) or 0)
    total = sum(_joker_sell_cost(run, j) for j in _jokers(run) if _is_joker(j))
    amount = max(0, min(total, cap))
    _add_dollars(run, amount)
    return _ok(key, kind, dollars=amount, money=amount, total=total)


def _emperor(run, key, kind, name, cfg, targets):
    # card.lua:1401 - The Emperor (Tarots) / The High Priestess (Planets)
    set_name = "Tarot" if name == "The Emperor" else "Planet"
    want = int(cfg.get("tarots") or cfg.get("planets") or 0)
    slots = min(want, _free_consumable_slots(run))
    created = []
    for _ in range(max(0, slots)):
        new_key = _pick_consumable_key(run, set_name)
        if not new_key:
            break
        _add_consumable(run, new_key)
        created.append(new_key)
    return _ok(key, kind, created=created, n=len(created))


def _create_joker(run, key, kind, name, cfg, targets):
    # Judgement / The Soul (card.lua:1415)
    if _free_joker_slots(run) <= 0:
        return _fail(key, kind, "no free joker slot")
    legendary = name == "The Soul"
    joker_key = _pick_joker_key(run, legendary=legendary,
                                rarity=None if legendary else None)
    if not joker_key:
        return _fail(key, kind, "no joker available")
    _add_joker(run, joker_key)
    return _ok(key, kind, created=joker_key, joker=joker_key, legendary=legendary)


def _ankh(run, key, kind, name, cfg, targets):
    # card.lua:1426 - copy one random joker, destroy the other non-eternal ones
    jokers = list(_jokers(run))
    if not jokers:
        return _fail(key, kind, "no jokers to copy")
    if _free_joker_slots(run) <= 0:
        return _fail(key, kind, "no free joker slot")
    chosen = run.rng.pick("ankh_choice", jokers)
    doomed = [j for j in jokers if j is not chosen and not _is_eternal(j)]
    for j in doomed:
        _remove_joker(run, j)
    edition = _edition(chosen)
    if edition == "e_negative":  # copy_card strip_edition (card.lua:1445)
        edition = None
    copied_key = _joker_key(chosen)
    _add_joker(run, copied_key, edition=edition)
    return _ok(key, kind, copied=copied_key, destroyed=len(doomed), edition=edition)


def _wraith(run, key, kind, name, cfg, targets):
    # card.lua:1454 - a Rare joker, then lose all money
    if _free_joker_slots(run) <= 0:
        return _fail(key, kind, "no free joker slot")
    joker_key = _pick_joker_key(run, rarity=0.99, append="wra")
    if not joker_key:
        return _fail(key, kind, "no joker available")
    _add_joker(run, joker_key)
    run.dollars = 0 if getattr(run, "dollars", 0) else getattr(run, "dollars", 0)
    return _ok(key, kind, created=joker_key, joker=joker_key, dollars=0)


def _edition_spectral(run, key, kind, name, cfg, targets):
    # The Wheel of Fortune / Ectoplasm / Hex (card.lua:1467)
    eligible = _editionless_jokers(run)
    if not eligible:
        return _fail(key, kind, "no eligible joker")

    if name == "The Wheel of Fortune":
        if not run.rng.chance("wheel_of_fortune", int(cfg.get("extra", 4) or 4)):
            return _ok(key, kind, applied=False, edition=None)
        edition = _poll_edition(run, "wheel_of_fortune", no_neg=True, guaranteed=True)
    elif name == "Ectoplasm":
        edition = "e_negative"
    else:  # Hex
        edition = "e_polychrome"

    chosen = run.rng.pick(_EDITION_SEED.get(name, "edition"), eligible)
    doomed = [j for j in _jokers(run) if j is not chosen and not _is_eternal(j)]
    _with_edition(run, chosen, edition)

    destroyed = 0
    if name == "Hex":
        for j in doomed:
            _remove_joker(run, j)
            destroyed += 1
    if name == "Ectoplasm":
        minus = int(getattr(run, "ecto_minus", 1) or 1)
        _change_hand_size(run, -minus)
        try:
            run.ecto_minus = minus + 1
        except AttributeError:
            pass

    return _ok(key, kind, applied=True, edition=edition, joker=_joker_key(chosen),
               destroyed=destroyed)


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------

_HANDLERS = {
    "Black Hole": _black_hole,
    "Talisman": _seal,
    "Deja Vu": _seal,
    "Trance": _seal,
    "Medium": _seal,
    "Aura": _aura,
    "Cryptid": _cryptid,
    "Sigil": _sigil,
    "Ouija": _ouija,
    "Familiar": _destroy_and_create,
    "Grim": _destroy_and_create,
    "Incantation": _destroy_and_create,
    "Immolate": _immolate,
    "The Fool": _the_fool,
    "The Hermit": _the_hermit,
    "Temperance": _temperance,
    "The Emperor": _emperor,
    "The High Priestess": _emperor,
    "Judgement": _create_joker,
    "The Soul": _create_joker,
    "Ankh": _ankh,
    "Wraith": _wraith,
    "The Wheel of Fortune": _edition_spectral,
    "Ectoplasm": _edition_spectral,
    "Hex": _edition_spectral,
    "The Hanged Man": _destroy_targets,
}


def _dispatch(run, key, kind, name, cfg, targets):
    if cfg.get("mod_conv"):
        return _mod_conv(run, key, kind, name, cfg, targets)
    if cfg.get("suit_conv"):
        return _suit_conv(run, key, kind, name, cfg, targets)
    if cfg.get("hand_type"):
        return _planet(run, key, kind, name, cfg, targets)
    handler = _HANDLERS.get(name)
    if handler is not None:
        return handler(run, key, kind, name, cfg, targets)
    UNIMPLEMENTED.add(key)
    return _fail(key, kind, f"not implemented: {key}")


def use(run, key: str, targets: list | None = None) -> dict:
    """Apply a consumable's effect (``Card:use_consumeable``).

    Returns ``{"ok": True, "kind": "tarot"|"planet"|"spectral", "key": key,
    ...details}`` or ``{"ok": False, "kind": ..., "key": key, "error": "..."}``.
    """
    center = _center(key)
    if center.get("set") not in CONSUMABLE_SETS:
        return _fail(key, None, f"unknown consumable: {key}")
    kind = _kind(key)
    name = center.get("name") or key
    cfg = dict(center.get("config") or {})
    targets = list(targets or [])

    error = _validate_targets(name, cfg, targets)
    if error:
        return _fail(key, kind, error)

    result = _dispatch(run, key, kind, name, cfg, targets)

    # set_consumeable_usage (misc_functions.lua:1212) runs *before* the effect in
    # the Lua; applying it after keeps The Fool reading the previous card.
    if result.get("ok") and center.get("set") in ("Tarot", "Planet"):
        _set_last_tarot_planet(run, key)
    return result
