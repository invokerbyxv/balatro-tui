"""Line templates for the covert transcript (the app's "screen").

Every phase renders to a single scrolling line - never clears, never moves the
cursor, monochrome text.  Kept intentionally terse: it must read like ordinary
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
    j = len([k for k in state.jokers if k])
    cc = len([k for k in state.consumeables if k])
    tags = len(getattr(state, "tags", []) or [])
    vou = len(getattr(state, "vouchers", []) or [])
    return (f"${state.dollars} | jokers {j}/{state.params['joker_slots']} "
            f"| consumables {cc}/{state.params['consumable_slots']} "
            f"| tags {tags} vouchers {vou} | "
            f"hands {state.hands_left}/{state.params['hands']} "
            f"disc {state.discards_left}/{state.params['discards']}")


def blind_line(state) -> str:
    b = getattr(state, "the_blind", None)
    if b is None:
        return f"ante {state.ante} | no blind | chips {number_format(state.chips)}"
    kind = "Boss" if getattr(b, "is_boss", False) else "Blind"
    return (f"ante {state.ante} {kind} {b.name} | chips {number_format(state.chips)}/"
            f"{number_format(b.chips)}")


def hand_line(state, glyphs: bool = False) -> str:
    return "hand: " + hand_str(state.hand, glyphs)


def hand_info_line(state, glyphs: bool = False) -> str:
    """Best-hand hint plus the total for the cards currently selected."""
    from ..engine.hand import get_poker_hand_info
    from ..engine.scoring import hand_level
    key, cards = get_poker_hand_info(state.hand, state.joker_flags)
    if not key:
        return "best: -"
    lvl = hand_level(state, key, None)
    return (f"best: {key} lvl{lvl['level']} base {lvl['chips']}x{lvl['mult']}"
            f"  ({hand_str(cards or [], glyphs)})")


def jokers_line(state) -> str:
    if not state.jokers:
        return "jokers: -"
    parts = []
    for i, j in enumerate(state.jokers, 1):
        name = getattr(j, "ability", {}).get("name") or getattr(j, "key", str(j))
        ed = f"({j.edition[2:]})" if getattr(j, "edition", None) else ""
        parts.append(f"{i}:{name}{ed}")
    return "jokers: " + " ".join(parts)


def consumables_line(state) -> str:
    if not state.consumeables:
        return "consumables: -"
    parts = []
    for i, c in enumerate(state.consumeables, 1):
        name = getattr(c, "ability", {}).get("name") or getattr(c, "key", str(c))
        parts.append(f"{i}:{name}")
    return "consumables: " + " ".join(parts)


def tags_line(state) -> str:
    tags = getattr(state, "tags", []) or []
    if not tags:
        return "tags: -"
    return "tags: " + " ".join(str(t)[4:] if str(t).startswith("tag_") else str(t)
                               for t in tags)


def vouchers_line(state) -> str:
    vou = getattr(state, "vouchers", []) or []
    if not vou:
        return "vouchers: -"
    return "vouchers: " + " ".join(str(v)[2:] if str(v).startswith("v_") else str(v)
                                   for v in vou)


def prompt_select(state, selected: list[int]) -> str:
    if not selected:
        return "> select: (p=play d=discard 1-8 toggle c=use k=skip q=quit ?=help)"
    return "> selected: " + " ".join(str(i + 1) for i in selected) + "  p=play d=discard"


def play_line(res, won: bool = False, glyphs: bool = False) -> str:
    cards = " ".join(card_str(c, glyphs) for c in res.scoring_cards)
    dels = []
    for d in res.joker_deltas:
        if d.chips:
            dels.append(f"{d.name}+{d.chips}")
        elif d.mult:
            dels.append(f"{d.name}+{d.mult:g}")
        elif d.x_mult != 1.0:
            dels.append(f"{d.name}x{d.x_mult:.1f}")
    extra = []
    for d in getattr(res, "card_deltas", []) or []:
        bits = []
        if d.chips:
            bits.append(f"+{int(d.chips)}c")
        if d.mult:
            bits.append(f"+{d.mult:g}m")
        if d.x_mult != 1.0:
            bits.append(f"x{d.x_mult:g}")
        if bits:
            extra.append(f"{card_str(d.card, glyphs)}{''.join(bits)}")
    if getattr(res, "destroyed", None):
        extra.append("destroyed " + " ".join(card_str(c, glyphs) for c in res.destroyed))
    if getattr(res, "debuffed", False):
        extra.append("DEBUFFED by blind")
    if getattr(res, "dollars", 0):
        extra.append(f"+${res.dollars}")
    suffix = f" | {', '.join(dels + extra)}" if (dels or extra) else ""
    gap = "WON" if won else f"{- (res.blind_chips - res.score):+d}"
    return (f"play -> {res.hand_key}  [{cards}]  base {res.base_chips:g}*{res.base_mult:g} "
            f"lvl{res.level} -> total {number_format(res.score)}  blind {number_format(res.blind_chips)}"
            f" ({gap}){suffix}")


def discard_line(state, dropped: list, n_drawn: int, glyphs: bool = False) -> str:
    return (f"discard -> {hand_str(dropped, glyphs)} +draw {n_drawn} "
            f"hands {state.hands_left}/{state.params['hands']} disc {state.discards_left}/{state.params['discards']}")


def shop_line(state, shop) -> str:
    parts = []
    for it in shop.items:
        parts.append(it.describe() if it else f"[..]---sold---")
    return f"shop | {status(state)} | " + " ".join(parts)


def shop_voucher_line(shop) -> str:
    if not getattr(shop, "vouchers", None):
        return ""
    parts = [it.describe() if it else "[..]---sold---" for it in shop.vouchers]
    return "voucher | " + " ".join(parts)


def shop_prompt(shop, state) -> str:
    return (f"> shop: 1-{len(shop.items) + len(shop.vouchers)} buy  r=reroll ${shop.reroll_cost} "
            f"x#=sell  s=leave  q=quit")


def pack_line(pack: dict, glyphs: bool = False) -> str:
    if not pack or not pack.get("ok"):
        return "pack -> (empty)"
    cards = []
    for i, c in enumerate(pack.get("cards", []), 1):
        cards.append(f"{i}:{_card_label(c, glyphs)}")
    return (f"pack -> {pack.get('name', pack.get('key'))} choose {pack.get('choose', 1)} | "
            + " ".join(cards))


def _card_label(c, glyphs: bool = False) -> str:
    if hasattr(c, "rank") and not getattr(c, "is_joker", False) and not getattr(c, "key", None):
        return card_str(c, glyphs)
    return getattr(c, "ability", {}).get("name") or getattr(c, "key", str(c))


def round_end(state, reward: int, interest: int, gold: int,
              money=None, rows=None) -> str:
    bits = [f"+${reward} reward"]
    if money is not None:
        if money.hands:
            bits.append(f"+${money.hands} hands")
        if money.discards:
            bits.append(f"+${money.discards} discards")
        if money.jokers:
            bits.append(f"+${money.jokers} jokers")
        if money.tags:
            bits.append(f"+${money.tags} tags")
    bits.append(f"+${interest} interest")
    if gold:
        bits.append(f"+${gold} gold")
    return (f"round end: {' '.join(bits)} -> ${state.dollars}   ante {state.ante}")


def skip_line(result: dict) -> str:
    if not result.get("ok"):
        return f"skip -> {result.get('error', '?')}"
    return (f"skip -> {result.get('blind')} (tag {result.get('tag_name')})"
            + (f" | {result['display']}" if result.get("display") else ""))


def game_over(state) -> str:
    return (f"=== game over | ante {state.ante} | ${state.dollars} "
            f"| hands {state.hands_left}/{state.params['hands']} | "
            f"jokers {len(state.jokers)} ===")


def win_message(state) -> str:
    return f"=== full clear at ante {state.ante}! ==="
