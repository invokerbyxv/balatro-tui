"""Game tuning constants, ported from balatro_source_code.

Sources:
- `functions/misc_functions.lua:get_starting_params` (~line 1868)
- `game.lua` Game:init_game_object() hand-levels table (~line 2002)
- `game.lua` interest caps / round_resets (~line 1909)
- `functions/common_events.lua:calculate_reroll_cost` (~line 2263)

This module is part of the pure core: it must never import render/ or input/.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Starting parameters (get_starting_params)
# ---------------------------------------------------------------------------
STARTING_PARAMS = {
    "dollars": 4,
    "hand_size": 8,
    "discards": 3,
    "hands": 4,
    "reroll_cost": 5,
    "joker_slots": 5,
    "ante_scaling": 1,
    "consumable_slots": 2,
}

# Reroll cost escalation (calculate_reroll_cost): base 5, +1 each time.
REROLL_COST_INCREASE = 1

# Shop layout: 2 card slots (jokers/consumables) + 2 booster slots (game.lua
# shop creation), each raisable by the Overstock vouchers.
SHOP_SIZE = 2
BOOSTER_SLOTS = 2
VOUCHER_SLOTS = 1

# Interest (state_events.lua ~1192): dollars += amount * min(floor(dollars/5), cap/5)
INTEREST_AMOUNT = 1
INTEREST_CAP = 25  # /5 => max $5 interest at $25 held

# Tag / pack draw rates
DEFAULT_TAG_RATE = 1
SPECTRAL_RATE = 0

# ---------------------------------------------------------------------------
# Poker hand base levels (game.lua ~2002)
# ---------------------------------------------------------------------------
# Each entry: mult / chips base, s_mult / s_chips per-level scaling,
# l_mult / l_chips per-level increments from Planet cards.
# Level scaling formula (state_events.lua, level_up_hand):
#   shown mult = mult + s_mult*(level-1)
#   shown chips = chips + s_chips*(level-1)
# Planet card levels up the hand adding l_mult/l_chips per use.
HAND_LEVELS: dict[str, dict] = {
    "Flush Five":       {"mult": 16, "chips": 160, "s_mult": 16, "s_chips": 160, "l_mult": 3, "l_chips": 50,  "order": 1,  "visible": False},
    "Flush House":      {"mult": 14, "chips": 140, "s_mult": 14, "s_chips": 140, "l_mult": 4, "l_chips": 40,  "order": 2,  "visible": False},
    "Five of a Kind":   {"mult": 12, "chips": 120, "s_mult": 12, "s_chips": 120, "l_mult": 3, "l_chips": 35,  "order": 3,  "visible": False},
    "Straight Flush":   {"mult": 8,  "chips": 100, "s_mult": 8,  "s_chips": 100, "l_mult": 4, "l_chips": 40,  "order": 4,  "visible": True},
    "Four of a Kind":   {"mult": 7,  "chips": 60,  "s_mult": 7,  "s_chips": 60,  "l_mult": 3, "l_chips": 30,  "order": 5,  "visible": True},
    "Full House":       {"mult": 4,  "chips": 40,  "s_mult": 4,  "s_chips": 40,  "l_mult": 2, "l_chips": 25,  "order": 6,  "visible": True},
    "Flush":            {"mult": 4,  "chips": 35,  "s_mult": 4,  "s_chips": 35,  "l_mult": 2, "l_chips": 15,  "order": 7,  "visible": True},
    "Straight":         {"mult": 4,  "chips": 30,  "s_mult": 4,  "s_chips": 30,  "l_mult": 3, "l_chips": 30,  "order": 8,  "visible": True},
    "Three of a Kind":  {"mult": 3,  "chips": 30,  "s_mult": 3,  "s_chips": 30,  "l_mult": 2, "l_chips": 20,  "order": 9,  "visible": True},
    "Two Pair":         {"mult": 2,  "chips": 20,  "s_mult": 2,  "s_chips": 20,  "l_mult": 1, "l_chips": 20,  "order": 10, "visible": True},
    "Pair":             {"mult": 2,  "chips": 10,  "s_mult": 2,  "s_chips": 10,  "l_mult": 1, "l_chips": 15,  "order": 11, "visible": True},
    "High Card":        {"mult": 1,  "chips": 5,   "s_mult": 1,  "s_chips": 5,   "l_mult": 1, "l_chips": 10,  "order": 12, "visible": True},
}

# Order from strongest to weakest (used by hand_level ordering / display).
HAND_ORDER: list[str] = list(dict(sorted(HAND_LEVELS.items(), key=lambda kv: kv[1]["order"])).keys())

# ---------------------------------------------------------------------------
# Ante base chip target (misc_functions.lua:get_blind_amount ~919)
# ---------------------------------------------------------------------------
BLIND_AMOUNT_TABLE = [300, 800, 2000, 5000, 11000, 20000, 35000, 50000]

# Deck back -> starting param deltas (game.lua:628+, P_CENTERS set="Back").
#
# Deprecated view: `engine/backs.py` is the authoritative implementation
# (`backs.deltas_for(deck_key)`), and this table must stay a superset of it
# (pinned by tests/test_vouchers_backs.py). `GameState._apply_deck` folds these in
# ADDITIVELY, so `_apply_deck` must not be combined with `backs.setup(apply=True)`
# for the same run. Note the Lua *assigns* `ante_scaling` rather than adding it
# (back.lua:263) - pass `scaling=2` to GameState for b_plasma.
DECK_DELTAS = {
    "b_red":        {"discards": 1},
    "b_blue":       {"hands": 1},
    "b_yellow":     {"dollars": 10},
    # game.lua:631 -> extra_discard_bonus is 1 ($1 per remaining discard), not 2.
    "b_green":      {"no_interest": True, "extra_hand_bonus": 2, "extra_discard_bonus": 1},
    "b_black":      {"joker_slots": 1, "hands": -1},
    "b_magic":      {"voucher": "v_crystal_ball", "consumables": ["c_fool", "c_fool"]},
    "b_nebula":     {"voucher": "v_telescope", "consumable_slots": -1},
    "b_ghost":      {"spectral_rate": 2, "consumables": ["c_hex"]},
    "b_abandoned":  {"remove_faces": True},
    "b_checkered":  {"checkered_deck": True},
    "b_zodiac":     {"vouchers": ["v_tarot_merchant", "v_planet_merchant", "v_overstock_norm"]},
    "b_painted":    {"hand_size": 2, "joker_slots": -1},
    "b_anaglyph":   {},
    "b_plasma":     {"ante_scaling": 2},
    "b_erratic":    {"randomize_rank_suit": True},
    "b_challenge":  {},
}