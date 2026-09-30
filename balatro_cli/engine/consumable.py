"""Consumable effects (Tarot / Planet / Spectral) ported from card.lua:use_consumable.

v1 implements the practical set (planets level hands; enhancement-tarots upgrade
a card; rank-up/down tarots). Spectrals and rare tarots are represented as data
with a no-op notice where a mechanical effect isn't wired yet.
"""

from __future__ import annotations

from ..data import loader


def hand_level_map():
    # planets map to CONFIG hand_types
    return loader.centers()


ENHANCEMENT_TAROTS = {
    "c_magician": "m_lucky",
    "c_lovers": "m_wild",
    "c_chariot": "m_mult",
    "c_sun": "m_bonus",
    "c_strength": None,        # rank-up, handled separately
    "c_death": None,           # convert card to another
    "c_temperance": None,      # money = value of jokers (economy)
}


def use_consumable(state, key: str, target_cards=None) -> dict:
    """Apply a consumable center's effect. Returns a short result message dict."""
    centers = loader.centers()
    data = centers.get(key, {})
    s = data.get("set")

    target_cards = target_cards or []

    if s == "Planet":
        hand_type = (data.get("config") or {}).get("hand_type")
        if hand_type and hand_type in state.hand_levels:
            state.hand_levels[hand_type]["level"] += 1
            lvl = state.hand_levels[hand_type]["level"]
            return {"ok": True, "kind": "planet", "hand": hand_type, "level": lvl}
        return {"ok": False, "kind": "planet", "error": "no matching hand"}

    if s == "Tarot":
        enh = ENHANCEMENT_TAROTS.get(key)
        if enh and target_cards:
            for c in target_cards[: int((data.get("config") or {}).get("max_highlighted", 1))]:
                c.enhancement = enh
            return {"ok": True, "kind": "tarot", "enhance": enh, "n": len(target_cards)}
        if key == "c_strength" and target_cards:
            ranks = ["A", "K", "Q", "J", "T", "9", "8", "7", "6", "5", "4", "3", "2"]
            order = {r: i for i, r in enumerate(ranks)}
            for c in target_cards[:2]:
                if order.get(c.rank) is not None and order[c.rank] + 1 < len(ranks):
                    c.rank = ranks[order[c.rank] + 1]  # rank up
            return {"ok": True, "kind": "tarot", "effect": "up_rank"}
        return {"ok": False, "kind": "tarot", "effect": "not yet implemented"}

    if s == "Spectral":
        return {"ok": False, "kind": "spectral", "effect": "not yet implemented"}

    return {"ok": False, "error": f"unknown consumable {key}"}