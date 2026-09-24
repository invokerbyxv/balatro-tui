"""核心引擎单元测试:盲注缩放、牌型识别、结算经济、底注推进。"""

from balatro_tui.game_engine import (
    GameState, get_blind_amount, small_blind, big_blind, pick_boss,
)
from balatro_tui.game_engine.hand import HandEvaluator
from balatro_tui.game_engine.card import Card


def test_blind_amount_base():
    assert get_blind_amount(1) == 300
    assert get_blind_amount(4) == 5000
    assert get_blind_amount(8) == 50000
    # 第 9 底注以上按扩展公式,数值大于第 8 关
    assert get_blind_amount(9) > get_blind_amount(8)


def test_small_big_boss_targets():
    small = small_blind(2, 1)
    big = big_blind(2, 1)
    assert small.target == 800          # ante2 基值 800
    assert big.target == int(800 * 1.5)
    assert big.dollars == 4
    # 高低底注 scaling 2 更高
    assert get_blind_amount(3, 2) > get_blind_amount(3, 1)


def test_pick_boss_filters_by_ante():
    b = pick_boss(1, 1, [])
    assert b is not None and b.is_boss
    assert b.target == get_blind_amount(1, 1) * b.mult


def test_hand_evaluation():
    flush = [Card("Hearts", r) for r in ["2", "4", "6", "Ace", "King"]]
    key, scoring = HandEvaluator(flush).evaluate()
    assert key == "Flush"
    flush_five = [
        Card("Hearts", "Ace"), Card("Hearts", "Ace"), Card("Hearts", "Ace"),
        Card("Hearts", "Ace"), Card("Hearts", "Ace"),
    ]
    assert HandEvaluator(flush_five).evaluate()[0] == "Flush Five"
    pair = [Card("Clubs", "Ace"), Card("Diamonds", "Ace"), Card("Spades", "King")]
    assert HandEvaluator(pair).evaluate()[0] == "Pair"
    high = [Card("Spades", "Ace"), Card("Clubs", "King")]
    assert HandEvaluator(high).evaluate()[0] == "High Card"


def test_play_and_score_accumulates():
    s = GameState()
    s.set_deck("b_red")
    s.start_blind(small_blind(1, s.ante_scaling))
    s.hand = [Card("Hearts", r) for r in ["2", "3", "4", "5"]]
    calc = s.play_cards(s.hand)
    assert calc is not None
    assert s.score_chips == calc["score"]
    assert s.hands_left == s.params["hands"] - 1


def test_deck_back_modifiers():
    red = GameState(); red.set_deck("b_red")
    assert red.discards_left == 4            # 默认 3 + 1
    assert len(red.deck) == 52
    blue = GameState(); blue.set_deck("b_blue")
    assert blue.hands_left == 5              # 默认 4 + 1
    checkered = GameState(); checkered.set_deck("b_checkered")
    assert len(checkered.deck) == 26         # 仅黑桃/红桃


def test_round_money_on_win():
    s = GameState()
    s.set_deck("b_red")
    s.start_blind(small_blind(1, s.ante_scaling))
    s.dollars = 0
    s.score_chips = s.blind_target + 1       # 已达标
    s.won_blind = True
    s.hands_left = 2
    money = s.calculate_round_money()
    assert money["blind_reward"] == 3        # 小盲奖励
    assert money["hands_money"] == 2         # 剩余出牌 ×1
    assert money["total"] == 3 + 2 + money["interest"]


def test_advance_ante_blind_progression():
    s = GameState(); s.set_deck("b_red")
    s.ante, s.blind_in_ante = 1, 1
    s.advance_ante_blind()                   # 打小盲(非boss)
    assert (s.ante, s.blind_in_ante) == (1, 2)
    s.advance_ante_blind()                   # 大盲
    assert (s.ante, s.blind_in_ante) == (1, 3)
    # 打 boss
    from balatro_tui.game_engine.blind import Blind
    s.current_blind = Blind("bl_hook", "钩子", 2, 5, get_blind_amount(1, 1), boss={"min": 1, "max": 10})
    s.advance_ante_blind()
    assert (s.ante, s.blind_in_ante) == (2, 1)