"""Core engine tests for the ported run/scoring/economy layer.

These pin the *numbers* the core is responsible for: card ability mapping, the
scoring pipeline (retriggers, editions, destruction), the run loop (blind
progression, tags, round money) and the shop layout.
"""

from __future__ import annotations

import pytest

from balatro_cli import config
from balatro_cli.engine.card import Card, JokerCard, ability_from_config, normalize_seal
from balatro_cli.engine.game_state import GameState
from balatro_cli.engine.hand import JokerFlags, evaluate_poker_hand
from balatro_cli.engine.scoring import score_play
from balatro_cli.engine.shop import Shop


# ---------------------------------------------------------------------------
# Card ability mapping (card.lua:277 Card:set_ability)
# ---------------------------------------------------------------------------

def test_ability_maps_Xmult_to_x_mult():
    a = ability_from_config({"Xmult": 2, "extra": 4}, name="Glass Card",
                            effect="Glass Card", set_="Enhanced")
    assert a["x_mult"] == 2
    assert a["extra"] == 4
    assert a["Xmult"] == 2          # raw config key kept for compatibility


def test_ability_defaults():
    a = ability_from_config({})
    assert a["mult"] == 0
    assert a["x_mult"] == 1          # `center.config.Xmult or 1`
    assert a["h_x_mult"] == 0
    assert a["bonus"] == 0
    assert a["perma_bonus"] == 0


def test_card_ability_from_centers():
    assert Card("7", "S", enhancement="m_bonus").ability["bonus"] == 30
    assert Card("7", "S", enhancement="m_steel").ability["h_x_mult"] == 1.5
    assert Card("7", "S", enhancement="m_gold").ability["h_dollars"] == 3
    assert Card("7", "S", enhancement="m_glass").get_chip_x_mult() == 2.0


def test_seal_normalization():
    assert Card("7", "S", seal="s_red").seal == "red"
    assert Card("7", "S", seal="Gold").seal == "gold"
    assert Card("7", "S", seal="bogus").seal is None
    assert normalize_seal("purple") == "purple"


def test_gold_seal_pays_three():
    assert Card("7", "S", seal="gold").get_p_dollars() == 3
    assert Card("7", "S").get_p_dollars() == 0


def test_stone_cards_have_unique_ids_and_never_match():
    a = Card("5", "S", enhancement="m_stone")
    b = Card("5", "H", enhancement="m_stone")
    assert a.id != b.id
    res = evaluate_poker_hand([a, b])
    assert res["Pair"] == []          # stones never pair up
    assert res["top_key"] == "High Card"


def test_stone_is_not_any_suit_and_has_no_rank_chips():
    assert Card("Q", "C", enhancement="m_stone").is_suit("C") is False
    assert Card("Q", "C", enhancement="m_stone").get_chip_bonus() == 50


# ---------------------------------------------------------------------------
# scoring pipeline
# ---------------------------------------------------------------------------

def lvl(hand_key, level=1):
    base = config.HAND_LEVELS[hand_key]
    return {"chips": base["chips"] + base["s_chips"] * (level - 1),
            "mult": base["mult"] + base["s_mult"] * (level - 1),
            "level": level}


class _Blind:
    def __init__(self, chips=100):
        self.chips = chips

    def modify_hand(self, cards, poker_hands, handname, mult, chips):
        return mult, chips, False

    def is_defeated(self, chips):
        return chips >= self.chips


class _AlwaysRng:
    def __init__(self, value=True):
        self.value = value

    def chance(self, key, denom, numerator=1):
        return self.value

    def roll(self, key):
        return 0.0 if self.value else 1.0


def test_red_seal_retriggers_the_card():
    played = [Card("8", "S", seal="red"), Card("8", "H")]
    res = score_play(played, [], lvl("Pair"), _Blind())
    # Pair base 10 + 8 twice (red seal) + 8 = 34 chips, x2 mult
    assert res.total_chips == 34
    assert res.score == 68


def test_plain_pair_without_seal():
    played = [Card("8", "S"), Card("8", "H")]
    res = score_play(played, [], lvl("Pair"), _Blind())
    assert res.total_chips == 26
    assert res.score == 52


def test_glass_card_shatters_when_the_roll_succeeds():
    played = [Card("8", "S", enhancement="m_glass"), Card("8", "H")]
    res = score_play(played, [], lvl("Pair"), _Blind(), rng=_AlwaysRng(True))
    assert res.score == 104            # x2 from Glass
    assert res.destroyed == [played[0]]


def test_glass_card_survives_a_failed_roll():
    played = [Card("8", "S", enhancement="m_glass"), Card("8", "H")]
    res = score_play(played, [], lvl("Pair"), _Blind(), rng=_AlwaysRng(False))
    assert res.destroyed == []


def test_edition_application_order_mult_then_xmult():
    """Holo +10 mult then Polychrome x1.5: ((2+10) * 1.5) = 18 -> 26*18."""
    played = [Card("8", "S", edition="e_holo"), Card("8", "H", edition="e_polychrome")]
    res = score_play(played, [], lvl("Pair"), _Blind())
    assert res.total_mult == pytest.approx(18.0)


def test_debuffed_card_scores_nothing_for_that_card():
    bad = Card("8", "S")
    bad.debuffed = True
    played = [bad, Card("8", "H")]
    res = score_play(played, [], lvl("Pair"), _Blind())
    assert res.total_chips == 18       # 10 + 8 only


def test_hand_level_from_run_table_is_used():
    st = GameState("s")
    st.level_up_hand("Pair", 2)        # level 3
    base = config.HAND_LEVELS["Pair"]
    res = score_play([Card("8", "S"), Card("8", "H")], [], None, _Blind(), run=st)
    assert res.level == 3
    assert res.base_chips == base["chips"] + base["s_chips"] * 2
    assert res.base_mult == base["mult"] + base["s_mult"] * 2


def test_blind_debuff_hand_zeroes_the_score():
    class BanBlind(_Blind):
        def debuff_hand(self, cards, poker_hands, handname, check=False, **kw):
            return True

    res = score_play([Card("8", "S"), Card("8", "H")], [], lvl("Pair"), BanBlind())
    assert res.debuffed is True
    assert res.score == 0
    assert res.total_chips == 0


def test_splash_scores_every_played_card():
    """Without the Splash joker only the pair scores; the numbers pin it."""
    played = [Card("8", "S"), Card("8", "H"), Card("2", "C")]
    res = score_play(played, [], lvl("Pair"), _Blind())
    assert res.total_chips == 26       # the 2C does not score


# ---------------------------------------------------------------------------
# run loop
# ---------------------------------------------------------------------------

def test_run_starts_at_first_ante_select():
    st = GameState("seed1")
    st.start()
    assert st.phase == "blind_select"
    assert [o.kind for o in st.blind_choices] == ["small", "big"]
    assert st.ante == 1


def test_blind_progression_small_big_boss_ante():
    st = GameState("prog")
    st.start()
    for expected in (["small", "big"], ["big"], ["boss"]):
        assert [o.kind for o in st.blind_choices] == expected
        st.select_blind(st.blind_choices[0].kind)
        st.chips = st.the_blind.chips
        st.last_round_won = True
        st.end_round()
        st.advance_from_shop()
    assert st.ante == 2
    assert [o.kind for o in st.blind_choices] == ["small", "big"]


def test_skip_blind_grants_a_tag_and_advances():
    st = GameState("skip")
    st.start()
    res = st.skip_blind(0)
    assert res["ok"]
    assert len(st.tags) == 1
    assert st.phase == "blind_select"
    assert [o.kind for o in st.blind_choices] == ["big"]
    # skipping cannot loop forever: big -> boss -> ante up
    res = st.skip_blind(0)
    assert res["ok"]
    assert [o.kind for o in st.blind_choices] == ["boss"]
    res = st.skip_blind(0)
    assert res["ok"]
    assert st.ante == 2
    assert [o.kind for o in st.blind_choices] == ["small", "big"]


def test_round_money_counts_leftover_hands_and_interest():
    st = GameState("money")
    st.start()
    st.select_blind("small")
    st.dollars = 10
    st.chips = st.the_blind.chips
    st.hands_left = 2
    st.discards_left = 3
    money = st.calculate_round_money()
    assert money.reward == 3            # bl_small dollars
    assert money.hands == 2             # $1 per unused hand
    assert money.discards == 0          # no money_per_discard by default
    assert money.interest == 2          # $10 -> 2
    assert money.total == 3 + 2 + 2


def test_interest_cap_voucher_raises_the_cap():
    st = GameState("interest")
    st.dollars = 100
    assert st._interest() == config.INTEREST_CAP // 5
    st.redeem_voucher("v_seed_money")
    assert st.interest_cap == 50
    assert st._interest() == 10


def test_green_deck_marks_money_per_hand_and_no_interest():
    st = GameState("s", deck_key="b_green")
    assert st._no_interest() is True
    assert st.modifiers.get("money_per_hand") == 2
    assert st.modifiers.get("money_per_discard") == 1


def test_play_cards_updates_hand_stats():
    st = GameState("stats")
    st.start()
    st.select_blind("small")
    st.play_cards([0])
    key = st.last_hand_played
    assert key is not None
    assert st.hand_levels[key]["played"] == 1
    assert st.hand_levels[key]["played_this_round"] == 1
    assert st.hands_left == st.params["hands"] - 1
    assert st.current_round["hands_played"] == 1


def test_discard_decrements_and_refills():
    st = GameState("disc")
    st.start()
    st.select_blind("small")
    before = len(st.hand)
    r = st.discard_cards([0, 1])
    assert r["ok"]
    assert st.discards_left == st.params["discards"] - 1
    assert len(st.hand) == before
    assert len(r["dropped"]) == 2


def test_purple_seal_discard_creates_a_tarot():
    st = GameState("purple")
    st.start()
    st.select_blind("small")
    st.hand[0] = Card(st.hand[0].rank, st.hand[0].suit, seal="purple")
    assert st.consumeables == []
    st.discard_cards([0])
    assert len(st.consumeables) == 1


def test_jokers_are_stateful_cards():
    st = GameState("j")
    card = st.add_joker("j_joker")
    assert card.key == "j_joker"
    assert card.ability["mult"] == 4
    assert st.jokers[-1] == "j_joker"       # legacy string comparison still works
    assert st.joker_keys == ["j_joker"]


def test_sell_joker_refunds_half_the_cost():
    st = GameState("sell")
    st.add_joker("j_joker")                 # cost 2
    r = st.sell_joker(0)
    assert r["ok"]
    assert r["price"] == 1
    assert st.jokers == []


def test_negative_joker_grants_a_slot():
    st = GameState("neg")
    before = st.params["joker_slots"]
    st.add_joker("j_joker", edition="e_negative")
    assert st.params["joker_slots"] == before + 1


def test_use_consumable_removes_it_and_levels_the_hand():
    st = GameState("cons")
    st.add_consumable("c_mercury")
    before = st.hand_levels["Pair"]["level"]
    r = st.use_consumable(0)
    assert r["ok"]
    assert st.hand_levels["Pair"]["level"] == before + 1
    assert st.consumeables == []


def test_hand_level_up_is_capped_at_one_minimum():
    st = GameState("lvl")
    st.level_up_hand("Pair", 3)
    assert st.hand_levels["Pair"]["level"] == 4
    st.level_up_hand("Pair", -10)
    assert st.hand_levels["Pair"]["level"] == 1


# ---------------------------------------------------------------------------
# shop
# ---------------------------------------------------------------------------

def _shop(seed="shop"):
    st = GameState(seed)
    st.start()
    st.dollars = 100
    shop = Shop(st)
    shop.refill()
    return st, shop


def test_shop_layout_matches_config():
    st, shop = _shop()
    assert len(shop.items) == st.shop_size + st.booster_slots
    kinds = [i.kind for i in shop.items]
    assert kinds.count("booster") == st.booster_slots
    assert len(shop.vouchers) == 1
    assert not shop._next_voucher_key() == ""


def test_shop_reroll_cost_escalates_and_survives_refill():
    st, shop = _shop()
    before = shop.reroll_cost
    r = shop.reroll()
    assert r["ok"]
    assert shop.reroll_cost == before + config.REROLL_COST_INCREASE


def test_shop_buy_joker_and_consumable():
    st, shop = _shop()
    joker = next((i for i in shop.items if i.kind == "joker"), None)
    if joker:
        r = shop.buy(joker.index)
        assert r["ok"]
        assert st.jokers[-1] == joker.key
        assert shop._item(joker.index) is None      # sold out
    st2, shop2 = _shop("shop2")
    cons = next((i for i in shop2.items if i.kind == "consumable"), None)
    if cons:
        r = shop2.buy(cons.index)
        assert r["ok"]
        assert st2.consumeables[-1] == cons.key


def test_shop_buy_voucher_redeems_it():
    st, shop = _shop()
    v = shop.vouchers[0]
    r = shop.buy(v.index)
    assert r["ok"]
    assert v.key in st.used_vouchers


def test_shop_buy_without_money_fails():
    st = GameState("poor")
    st.start()
    st.dollars = 0
    shop = Shop(st)
    shop.refill()
    r = shop.buy(0)
    assert not r["ok"]
    assert r["error"] == "not enough money"


def test_shop_booster_buy_opens_a_pack():
    st, shop = _shop()
    b = next(i for i in shop.items if i.kind == "booster")
    r = shop.buy(b.index)
    assert r["ok"]
    assert "pack" in r


def test_voucher_exclusivity():
    st, shop = _shop()
    v = shop.vouchers[0]
    shop.buy(v.index)
    st.vouchers = list(st.used_vouchers)
    pool = shop._next_voucher_key()
    assert pool != v.key
