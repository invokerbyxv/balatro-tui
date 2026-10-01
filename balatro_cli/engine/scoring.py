"""Scoring pipeline - a port of `state_events.lua:G.FUNCS.evaluate_play` (~571-1135).

Per played hand, in the exact order the Lua performs them:

1.  Resolve the best hand (`get_poker_hand_info`) -> hand key + scoring cards;
    bump `played` / `played_this_round`, remember `last_hand_played`.
2.  Splash / Stone cards are appended to the scoring hand.
3.  `blind.debuff_hand(...)` - if the boss forbids this hand, mult/chips are
    forced to 0 and only the `debuffed_hand` joker hook fires.
4.  Base chips/mult come from the *level table*; `before` joker hooks may level
    the hand up, after which chips/mult are re-read from the table.
5.  `blind.modify_hand(...)` (The Flint halves both).
6.  For every scoring card, for every repetition (Red seal / retrigger jokers):
    the card's own chips+mult+x_mult, its edition, then each joker's
    `individual` hook - applied strictly in that order.
7.  For every card still held: `h_mult` / `x_mult` from the card and the
    `individual` joker hooks on `cardarea=hand`.
8.  The `joker_main` pass over jokers *and* consumables (Observatory), including
    the joker-edition pass and the "joker on joker" pass (Baseball Card).
9.  The deck back's `final_scoring_step` (Plasma Deck swaps chips and mult).
10. `destroying_card` hooks + the Glass Card shatter roll.

Chips and mult are floats; the final hand score is `floor(chips * mult)`,
exactly like the Lua.

Backwards compatibility: :func:`score_play` keeps its original positional
signature ``(played, held, level, blind, jokers=None, flags=None, ...)`` and the
:class:`ScoreResult` object keeps the field names the render layer reads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .. import config
from ..data import loader
from .card import Card, JokerCard, rank_nominal
from .hand import JokerFlags, evaluate_poker_hand
from .hooks import (AREA_HAND, AREA_JOKERS, AREA_PLAY, HOOK_AFTER, HOOK_BEFORE,
                    HOOK_DEBUFFED_HAND, HOOK_DESTROYING_CARD, HOOK_INDIVIDUAL,
                    HOOK_JOKER_MAIN, HOOK_OTHER_JOKER, HOOK_REPETITION,
                    Context, Effect, joker_name)


@dataclass
class CardDelta:
    card: Card
    chips: int = 0
    mult: float = 0
    x_mult: float = 1.0


@dataclass
class JokerDelta:
    key: str
    name: str
    chips: int = 0
    mult: float = 0
    x_mult: float = 1.0


@dataclass
class ScoreResult:
    hand_key: str
    scoring_cards: list[Card]
    base_chips: float
    base_mult: float
    level: int
    card_deltas: list[CardDelta] = field(default_factory=list)
    joker_deltas: list[JokerDelta] = field(default_factory=list)
    held_x_mult: float = 1.0
    total_chips: float = 0
    total_mult: float = 0.0
    score: int = 0
    blind_chips: int = 0
    debuffed: bool = False
    destroyed: list[Card] = field(default_factory=list)
    dollars: int = 0
    money: int = 0
    notes: list[str] = field(default_factory=list)
    effects_log: list[tuple[str, Effect]] = field(default_factory=list)

    # -- convenience for the render layer ------------------------------------
    @property
    def chips(self) -> int:
        return int(self.total_chips)

    @property
    def mult(self) -> float:
        return self.total_mult


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def mod_chips(v):
    return v


def mod_mult(v):
    return v


def as_joker(j) -> JokerCard:
    """Coerce a centers key into a :class:`JokerCard` (tests pass bare strings)."""
    if isinstance(j, JokerCard):
        return j
    if isinstance(j, Card):
        return j  # already a carrier
    key = str(j)
    center = loader.centers().get(key) or {}
    return JokerCard(key, name=center.get("name", key),
                     cfg=center.get("config") or {},
                     edition=None,
                     rarity=center.get("rarity", 1),
                     cost=center.get("cost", 0),
                     set_=center.get("set", "Joker"))


def hand_level(run, hand_key: str, level: dict | None) -> dict:
    """Resolved {chips, mult, level} for a hand, preferring the live run table."""
    table = None
    if run is not None:
        table = (getattr(run, "hand_levels", None) or {}).get(hand_key)
    if table is None and isinstance(level, dict):
        table = level
    if table is None:
        table = {**config.HAND_LEVELS[hand_key], "level": 1}
    lvl = int(table.get("level", 1) or 1)
    s_chips = table.get("s_chips", 0) or 0
    s_mult = table.get("s_mult", 0) or 0
    return {
        "chips": table.get("chips", 0) + s_chips * (lvl - 1),
        "mult": table.get("mult", 0) + s_mult * (lvl - 1),
        "level": lvl,
    }


def _joker_calc(run, joker, ctx: Context):
    """Dispatch one joker hook, tolerating the absence of the full table."""
    try:
        from . import jokers as joker_mod
        return joker_mod.calculate(run, joker, ctx)
    except ImportError:
        # Legacy v1 table: it has no context awareness, so only the main pass
        # may use it (otherwise its flat bonuses would be applied repeatedly).
        if ctx.event != HOOK_JOKER_MAIN:
            return None
        from . import joker as legacy
        key = joker.key if isinstance(joker, JokerCard) else str(joker)
        data = legacy.calculate(key, ctx.scoring_name, ctx.full_hand,
                                ctx.scoring_hand,
                                getattr(run, "joker_flags", JokerFlags()))
        if not data:
            return None
        eff = Effect()
        eff.chips = int(data.get("chips", 0) or 0)
        eff.mult = data.get("mult", 0) or 0
        eff.x_mult = data.get("x_mult", 1.0) or 1.0
        return eff


def _iter_jokers(jokers) -> list[JokerCard]:
    return [as_joker(j) for j in (jokers or [])]


# ---------------------------------------------------------------------------
# per-card / per-joker effect gathering
# ---------------------------------------------------------------------------

def _card_own_effects(card: Card, rng) -> list[Effect]:
    """`eval_card(card, {cardarea = G.play})`: chips, mult, x_mult, p_dollars, edition."""
    out: list[Effect] = []
    own = Effect()
    own.chips = int(card.get_chip_bonus() or 0)
    own.mult = card.get_chip_mult(rng) or 0
    x = card.get_chip_x_mult()
    if x:
        own.x_mult = float(x)
    pd = card.get_p_dollars(rng)
    if pd:
        own.p_dollars = pd
    if not own.is_empty():
        out.append(own)
    ed = card.get_edition_effect()
    if ed:
        e = Effect()
        e.chips = int(ed.get("chip_mod", 0) or 0)
        e.mult = ed.get("mult_mod", 0) or 0
        e.x_mult = float(ed.get("x_mult_mod", 1) or 1)
        out.append(e)
    return out


def _card_held_effects(card: Card) -> list[Effect]:
    """`eval_card(card, {cardarea = G.hand})`: h_mult / x_mult only."""
    out: list[Effect] = []
    hm = card.get_chip_h_mult()
    hx = card.get_chip_h_x_mult()
    if hm or hx:
        e = Effect()
        e.mult = hm or 0
        e.x_mult = float(hx) if hx else 1.0
        e.extra["held"] = True
        out.append(e)
    return out


def _repetitions(run, card: Card, ctx: Context, joker_list) -> int:
    """Total scoring repetitions for `card` (1 + Red seal + retrigger jokers)."""
    reps = 1
    if card.debuffed:
        return 1
    # seal probe (context.repetition_only)
    seal_ctx = ctx.with_(event=HOOK_REPETITION, other_card=card,
                         repetition_only=True, cardarea=ctx.cardarea)
    reps += _seal_repetitions(card, seal_ctx)
    for j in (joker_list or []):
        eff = _joker_calc(run, j, ctx.with_(event=HOOK_REPETITION, other_card=card,
                                            cardarea=AREA_PLAY, repetition_only=False))
        if eff and eff.repetitions:
            reps += int(eff.repetitions)
    return reps


def _seal_repetitions(card: Card, ctx: Context) -> int:
    """`Card:calculate_seal` with context.repetition -> Red seal gives +1."""
    if card.debuffed:
        return 0
    if card.seal == "red":
        return 1
    return 0


# ---------------------------------------------------------------------------
# main entry point
# ---------------------------------------------------------------------------

def score_play(played: list[Card], held: list[Card], level: dict,
               blind, jokers: list[Any] | None = None,
               flags: JokerFlags | None = None,
               run=None, rng=None,
               play_order: list[int] | None = None) -> ScoreResult:
    """Evaluate one played hand and produce an aggregate :class:`ScoreResult`.

    `level` is the resolved {mult, chips, s_mult, s_chips, level} for the hand;
    when `run` is supplied the live `run.hand_levels` table is preferred so that
    `before`-hook level-ups (Space Joker, Burnt Joker, ...) take effect.
    """
    flags = flags or (getattr(run, "joker_flags", None) if run else None) or JokerFlags()
    if rng is None:
        rng = getattr(run, "rng", None)
    joker_list = _iter_jokers(jokers if jokers is not None else
                              (getattr(run, "jokers", []) if run else []))

    results = evaluate_poker_hand(played, flags)
    hand_key = results["top_key"] or "High Card"
    scoring_cards = list(results["top"] or [])

    # 2. Splash keeps every played card; Stone cards always score.
    splash = _has_joker_name(joker_list, "Splash")
    if splash:
        scoring_cards = list(played)
    else:
        for c in played:
            if c.effect == "Stone Card" and c not in scoring_cards:
                scoring_cards.append(c)
    if play_order is not None:
        order = {id(c): i for i, c in enumerate(played)}
        scoring_cards.sort(key=lambda c: order.get(id(c), 99))

    lvl = hand_level(run, hand_key, level)

    ctx = Context(event=HOOK_BEFORE, run=run, cardarea=AREA_JOKERS,
                  full_hand=list(played), scoring_hand=scoring_cards,
                  held=list(held), scoring_name=hand_key, poker_hands=results,
                  blind=blind, extra={"jokers": joker_list})

    result = ScoreResult(hand_key=hand_key, scoring_cards=scoring_cards,
                         base_chips=lvl["chips"], base_mult=lvl["mult"],
                         level=lvl["level"],
                         blind_chips=getattr(blind, "chips", 0) or 0)

    # 3. boss blind hand ban
    debuff_hand = getattr(blind, "debuff_hand", None)
    if debuff_hand is not None and debuff_hand(played, results, hand_key, run=run):
        result.debuffed = True
        result.total_chips = 0
        result.total_mult = 0
        result.score = 0
        for j in joker_list:
            eff = _joker_calc(run, j, ctx.with_(event=HOOK_DEBUFFED_HAND))
            if eff:
                result.effects_log.append(("debuff", eff))
                # Matador still pays its $8 on a debuffed hand (card.lua:2736)
                if getattr(eff, "dollars", 0):
                    result.dollars += int(eff.dollars)
        return result

    # 4. before hooks (may level up the hand)
    for j in joker_list:
        eff = _joker_calc(run, j, ctx)
        if eff is None:
            continue
        result.effects_log.append(("before", eff))
        for hand, amount in _level_ups(eff, hand_key):
            _level_up(run, hand, amount)
    lvl = hand_level(run, hand_key, level)
    result.base_chips, result.base_mult, result.level = lvl["chips"], lvl["mult"], lvl["level"]

    mult = mod_mult(lvl["mult"])
    chips = mod_chips(lvl["chips"])

    # 5. boss blind hand modification (The Flint)
    modify = getattr(blind, "modify_hand", None)
    if modify is not None:
        mult, chips, _modded = modify(played, results, hand_key, mult, chips)
        mult, chips = mod_mult(mult), mod_chips(chips)

    # 6. scoring cards, with retriggers
    for card in scoring_cards:
        delta = CardDelta(card)
        if card.debuffed:
            result.card_deltas.append(delta)
            continue
        reps = _repetitions(run, card, ctx, joker_list)
        for _rep in range(reps):
            effects = _card_own_effects(card, rng)
            for j in joker_list:
                eff = _joker_calc(run, j, ctx.with_(event=HOOK_INDIVIDUAL,
                                                    cardarea=AREA_PLAY,
                                                    other_card=card))
                if eff is not None:
                    effects.append(eff)
                    result.effects_log.append(("individual", eff))
            for eff in effects:
                chips, mult = _apply(eff, chips, mult, result)
                delta.chips += int(eff.chips or 0)
                delta.mult += eff.mult or 0
                delta.x_mult *= eff.x_mult or 1.0
        result.card_deltas.append(delta)

    # 7. held cards - every repetition re-evaluates the card's own held
    # effect and every joker's individual effect (fresh random rolls), as in
    # the Lua per-card eval loop (state_events.lua held branch).
    for card in held:
        if card.debuffed:
            continue
        reps = 1
        if card.seal == "red":
            reps += 1
        for j in joker_list:
            eff = _joker_calc(run, j, ctx.with_(event=HOOK_REPETITION,
                                                cardarea=AREA_HAND,
                                                other_card=card))
            if eff and eff.repetitions:
                reps += int(eff.repetitions)
        for _rep in range(reps):
            effects = _card_held_effects(card)
            for j in joker_list:
                eff = _joker_calc(run, j, ctx.with_(event=HOOK_INDIVIDUAL,
                                                    cardarea=AREA_HAND,
                                                    other_card=card))
                if eff is not None:
                    effects.append(eff)
                    result.effects_log.append(("held", eff))
            for eff in effects:
                before_mult = mult
                chips, mult = _apply_held(eff, chips, mult, result)
                if eff.x_mult and eff.x_mult != 1.0 and before_mult:
                    result.held_x_mult *= eff.x_mult

    # 8. joker_main pass (jokers + consumables)
    # The Lua splits the joker-edition application: chip_mod/mult_mod land
    # before joker_main (state_events.lua:880-897), Xmult_mod after the
    # joker_main + joker-on-joker passes (947-955).
    consumeables = list(getattr(run, "consumeables", []) or []) if run else []
    edition_x: list[float] = []
    for j in list(joker_list) + [as_joker(c) for c in consumeables]:
        if getattr(j, "edition", None):
            ed = j.get_edition_effect() if hasattr(j, "get_edition_effect") else {}
            if ed:
                eff = Effect()
                eff.chips = int(ed.get("chip_mod", 0) or 0)
                eff.mult = ed.get("mult_mod", 0) or 0
                x = float(ed.get("x_mult_mod", 1) or 1)
                if x != 1.0:
                    edition_x.append(x)
                chips, mult = _apply(eff, chips, mult, result)
        eff = _joker_calc(run, j, ctx.with_(event=HOOK_JOKER_MAIN, joker=j))
        if eff is not None:
            mult, chips = _apply_main(eff, chips, mult, result, j, run)
        # joker-on-joker (Baseball Card) - a distinct branch in the Lua, so it
        # is *not* the joker_main context.
        for v in joker_list:
            oeff = _joker_calc(run, v, ctx.with_(event=HOOK_OTHER_JOKER,
                                                 cardarea=None,
                                                 other_joker=j, joker=v))
            if oeff is not None and (oeff.chips or oeff.mult or oeff.x_mult != 1.0):
                mult, chips = _apply_main(oeff, chips, mult, result, v, run)
    for x in edition_x:                     # Polychrome, after all joker effects
        mult = mod_mult(mult * x)

    # 9. deck back final scoring step (Plasma Deck swaps chips and mult)
    back_trigger = getattr(run, "back_trigger", None) if run else None
    if back_trigger is not None:
        out = back_trigger("final_scoring_step", chips=chips, mult=mult) or {}
        chips = mod_chips(out.get("chips", chips))
        mult = mod_mult(out.get("mult", mult))

    # 10. card destruction (destroying_card hooks + Glass shatter)
    destroyed: list[Card] = []
    for card in scoring_cards:
        destroy = False
        for j in joker_list:
            eff = _joker_calc(run, j, ctx.with_(event=HOOK_DESTROYING_CARD,
                                                other_card=card))
            if eff and eff.destroy:
                destroy = True
                break
        if card.effect == "Glass Card" and not card.debuffed and rng is not None:
            odds = card.ability.get("extra", 4) or 4
            if rng.chance("glass", odds):
                destroy = True
                card.shattered = True   # Glass Joker only counts shatters
        if destroy:
            destroyed.append(card)
    result.destroyed = destroyed

    # after hooks
    for j in joker_list:
        eff = _joker_calc(run, j, ctx.with_(event=HOOK_AFTER))
        if eff is not None:
            result.effects_log.append(("after", eff))

    result.total_chips = float(chips)
    result.total_mult = float(mult)
    result.score = int(chips * mult) if (chips * mult) > 0 else 0
    return result


# ---------------------------------------------------------------------------
# effect application (order is significant - see the module docstring)
# ---------------------------------------------------------------------------

def _apply(eff: Effect, chips: float, mult: float, result: ScoreResult):
    """Card-scoring application order: chips, mult, p_dollars, dollars, extra, x_mult."""
    if eff.chips:
        chips = mod_chips(chips + eff.chips)
    if eff.mult:
        mult = mod_mult(mult + eff.mult)
    if eff.p_dollars:
        result.dollars += int(eff.p_dollars)
        result.money += int(eff.p_dollars)
    if eff.dollars:
        result.dollars += int(eff.dollars)
        result.money += int(eff.dollars)
    # "any extra effects" (state_events.lua:735-745): mult/chip mods land
    # before the swap, same relative order as the Lua.
    if eff.extra.get("mult_mod"):
        mult = mod_mult(mult + eff.extra["mult_mod"])
    if eff.extra.get("chip_mod"):
        chips = mod_chips(chips + eff.extra["chip_mod"])
    if eff.extra.get("swap"):
        mult, chips = chips, mult
    if eff.x_mult and eff.x_mult != 1.0:
        mult = mod_mult(mult * eff.x_mult)
    return chips, mult


def _apply_held(eff: Effect, chips: float, mult: float, result: ScoreResult):
    """Held-card application order: dollars, h_mult, x_mult."""
    if eff.dollars:
        result.dollars += int(eff.dollars)
    if eff.mult:
        mult = mod_mult(mult + eff.mult)
    if eff.x_mult and eff.x_mult != 1.0:
        mult = mod_mult(mult * eff.x_mult)
    return chips, mult


def _apply_main(eff: Effect, chips: float, mult: float, result: ScoreResult,
                joker, run=None) -> tuple[float, float]:
    """joker_main application order: mult, chips, Xmult."""
    if eff.mult:
        mult = mod_mult(mult + eff.mult)
    if eff.chips:
        chips = mod_chips(chips + eff.chips)
    if eff.x_mult and eff.x_mult != 1.0:
        mult = mod_mult(mult * eff.x_mult)
    result.joker_deltas.append(JokerDelta(
        key=getattr(joker, "key", str(joker)), name=joker_name(joker),
        chips=int(eff.chips or 0), mult=eff.mult or 0,
        x_mult=eff.x_mult or 1.0))
    if eff.dollars:
        result.dollars += int(eff.dollars)
    for hand, amount in _level_ups(eff, result.hand_key):
        _level_up(run, hand, amount)
    return mult, chips


def _level_ups(eff: Effect, default_hand: str | None):
    """Normalize an effect's level-up request.

    The Lua's `before` hook returns `level_up = true` (a boolean meaning "level
    the played hand"), while other paths return an explicit hand.  Accept both.
    """
    if not eff.level_up:
        return []
    if eff.level_up is True:
        return [(default_hand, 1)] if default_hand else []
    out = []
    for item in eff.level_up:
        if isinstance(item, str):
            out.append((item, 1))
        elif isinstance(item, (tuple, list)) and len(item) == 2:
            out.append((item[0], int(item[1])))
    return out


def _level_up(run, hand_key: str, amount: int = 1) -> None:
    if run is None or not hand_key:
        return
    fn = getattr(run, "level_up_hand", None)
    if fn is not None:
        fn(hand_key, amount)


def _has_joker_name(joker_list, name: str) -> bool:
    want = name.lower()
    for j in joker_list:
        jn = joker_name(j)
        if jn and jn.lower() == want:
            return True
    return False


# ---------------------------------------------------------------------------
# helpers used by render/tests
# ---------------------------------------------------------------------------

def card_chip_base(c: Card) -> int:
    if c.effect == "Stone Card":
        return 0
    return rank_nominal(c.rank)
