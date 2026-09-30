"""Line templates for the covert transcript (the app's "screen").

Every phase renders to a single scrolling line — never clears, never moves the
cursor, monochrome text. Kept intentionally terse: it must read like ordinary
CLI/log output on an IDE terminal.
"""

from __future__ import annotations

from .text import hand_str, card_str, number_format


def run_header(run_no: int, deck: str, locale: str) -> str:
    return f"==== run {run_no} | deck {deck} | locale {locale} ===="


def blind_offer(ante: int, offer) -> str:
    kind = {"boss": "Boss", "big": "Big", "small": "Small"}.get(offer.kind, offer.kind)
    return f"ante {ante} {kind} {offer.name} (chips {number_format(offer.chips)})"


def status(state) -> str:
    j = sum(1 for k in state.jokers if k)
    cc = len([k for k in state.consumeables if k])
    return (f"${state.dollars} | jokers {j}/{state.params['joker_slots']} "
            f"| consumables {cc}/{state.params['consumable_slots']} | "
            f"hands {state.hands_left}/{state.params['hands']} disc {state.discards_left}/{state.params['discards']}")


def hand_line(state, glyphs: bool = False) -> str:
    return "hand: " + hand_str(state.hand, glyphs)


def prompt_select(state, selected: list[int]) -> str:
    if not selected:
        return "> select: (p=play d=discard 1-8 toggle q=quit ?=help)"
    return "> selected: " + " ".join(str(i + 1) for i in selected) + "  p=play d=discard"


def play_line(res, won: bool = False, glyphs: bool = False) -> str:
    cards = " ".join(card_str(c, glyphs) for c in res.scoring_cards)
    dels = []
    for d in res.joker_deltas:
        if d.chips:
            dels.append(f"{d.name}+{d.chips}")
        elif d.mult:
            dels.append(f"{d.name}+{d.mult}")
        elif d.x_mult != 1.0:
            dels.append(f"{d.name}x{d.x_mult:.1f}")
    suffix = f" | {', '.join(dels)}" if dels else ""
    gap = "WON" if won else f"{- (res.blind_chips - res.score):+d}"
    return (f"play -> {res.hand_key}  [{cards}]  base {res.base_chips}*{res.base_mult} "
            f"lvl{res.level} -> total {number_format(res.score)}  blind {number_format(res.blind_chips)}"
            f" ({gap}){suffix}")


def discard_line(state, dropped: list, n_drawn: int, glyphs: bool = False) -> str:
    return (f"discard -> {hand_str(dropped, glyphs)} +draw {n_drawn} "
            f"hands {state.hands_left}/{state.params['hands']} disc {state.discards_left}/{state.params['discards']}")


def shop_line(state, shop) -> str:
    parts = []
    for it in shop.items:
        if it is None:
            parts.append(f"[{len(parts)}]---sold---")
            continue
        parts.append(it.describe())
    return f"shop | {status(state)} | " + " ".join(parts)


def shop_prompt(shop, state) -> str:
    extra = [f"r=reroll ${shop.reroll_cost}"]
    return "> shop: 1-5 buy  r reroll  s leave" + (" | " + " ".join(extra) if extra else "")


def round_end(state, reward: int, interest: int, gold: int) -> str:
    return (f"round end: +${reward} reward +${interest} interest "
            f"(+${gold} gold) -> ${state.dollars}   ante {state.ante}")


def game_over(state) -> str:
    return f"=== game over | ante {state.ante} | ${state.dollars} | hands{state.hands_left}/{state.params['hands']} ==="


def win_message(state) -> str:
    return f"=== full clear at ante {state.ante}! ==="