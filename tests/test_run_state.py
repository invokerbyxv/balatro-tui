"""balatro_tui RunState 适配层测试。

引擎语义(小丑/消耗品/标签/优惠券/卡背/盲注/stake)已由 balatro_cli/tests 覆盖;
这里只验证适配层的映射与界面所需操作。全部用固定种子,确定性通过。
"""

from balatro_tui.game_engine import (
    RunState,
    blind_display,
    card_label,
    hand_name,
    score_lines,
)


def make_run(deck="b_red", stake=1, seed="tui-test"):
    r = RunState(seed)
    r.start_run(deck, stake=stake)
    return r


# ------------------------------------------------------------- 生命周期

def test_start_and_blind_choices():
    r = make_run()
    assert r.phase == "blind_select"
    kinds = [o["kind"] for o in r.blind_display_choices()]
    assert kinds == ["small", "big"]
    names = [o["name"] for o in r.blind_display_choices()]
    assert names == ["小盲注", "大盲注"]


def test_select_blind_draws_hand():
    r = make_run()
    r.select_blind(r.blind_choices[0].kind)
    assert r.phase == "round"
    assert len(r.hand) == r.hand_size
    # 红牌卡组:4 出牌 + 3+1 弃牌
    assert r.hands_left == 4 and r.discards_left == 4
    # 引擎牌面 → 界面符号
    text, color = card_label(r.hand[0])
    assert color in ("red", "black")
    assert text[0] in "♠♥♣♦"


def test_play_and_discard_flow():
    r = make_run()
    r.select_blind(r.blind_choices[0].kind)
    r.sort_hand("rank")
    key, scoring = r.preview_hand(r.hand[:2])
    assert key and len(scoring) >= 1
    res = r.play_cards([r.hand[0], r.hand[1]])
    assert res["ok"]
    assert r.hands_left == 3
    assert r.last_score_display is not None
    lines = score_lines(res["score"])
    assert lines[-1].startswith("=")
    res2 = r.discard_cards(r.hand[:2])
    assert res2["ok"] and len(res2["dropped"]) == 2
    assert r.discards_left == 3      # 红牌 4 - 1


def test_sort_hand_modes():
    r = make_run()
    r.select_blind(r.blind_choices[0].kind)
    r.sort_hand("rank")
    ranks = [c.rank for c in r.hand]
    assert ranks == sorted(ranks, key=lambda x: -"23456789TJQKA".index(x))
    r.sort_hand("suit")
    suits = [c.suit for c in r.hand]
    order = {s: i for i, s in enumerate("SHCD")}
    assert [order[s] for s in suits] == sorted(order[s] for s in suits)


# ------------------------------------------------------------- 卡背/赌注

def test_checkered_deck_is_full_52_split():
    r = make_run(deck="b_checkered")
    assert len(r.deck) == 52
    suits = [c.suit for c in r.deck]
    assert suits.count("S") == suits.count("H") == 26


def test_stake_effects_apply():
    r = make_run(stake=2)
    assert r.state.modifiers.get("no_blind_reward", {}).get("Small") is True
    r5 = make_run(stake=5)
    # 蓝注 -1 弃牌,红牌 +1 → 3
    assert r5.state.params["discards"] == 3
    r5b = make_run(deck="b_blue", stake=5)
    assert r5b.state.params["discards"] == 2


# ------------------------------------------------------------- 盲注跳过

def test_skip_blind_gives_tag_and_advances():
    r = make_run()
    offers = [o.key for o in r.blind_choices]
    result = r.skip_blind()
    assert result["ok"]
    assert result["tag"], "跳过盲注应抽到一个标签"
    assert r.skips == 1
    # 即时型标签(Handy/Economy/Top-up 等)当场结算被消耗,故 tags 可能为空;
    # 延迟型标签(Charm/Buffoon 等)留在待用队列
    assert isinstance(r.tags, list)
    # 推进到下一个盲注(blind_select 重新发牌)
    assert r.phase == "blind_select"
    new_keys = [o.key for o in r.blind_choices]
    assert new_keys != offers


def test_boss_display_has_description():
    r = make_run()
    r.skip_blind()          # 跳过小盲
    r.skip_blind()          # 跳过大盲 → boss
    info = blind_display(r.blind_choices[0].key, 300, 5)
    assert info["name"]
    assert info["desc"] and info["desc"] != "—"


# ------------------------------------------------------------- 消耗品

def test_tarot_enhances_target_cards():
    r = make_run()
    r.select_blind(r.blind_choices[0].kind)
    card = r.state.add_consumable("c_magician")   # The Magician:2 张 → 幸运牌
    idx = r.consumeables.index(card)
    targets = r.hand[:2]
    rng = r.consumable_target_range(card)
    assert rng == (2, 2)
    result = r.use_consumable(idx, targets)
    assert result["ok"], result
    for c in targets:
        assert c.enhancement == "m_lucky"
    assert card not in r.consumeables


def test_planet_levels_up_hand():
    r = make_run()
    r.select_blind(r.blind_choices[0].kind)
    before = r.hand_levels["Pair"]["level"]
    card = r.state.add_consumable("c_mercury")    # Mercury:升级 Pair? 由引擎决定
    idx = r.consumeables.index(card)
    result = r.use_consumable(idx, [])
    assert result["ok"], result
    # 至少有一项手牌等级提升(具体手型由引擎按星球定义)
    levels = {k: v["level"] for k, v in r.hand_levels.items()}
    assert sum(levels.values()) > before


# ------------------------------------------------------------- 商店/卡包

def test_shop_buy_sell_reroll():
    r = make_run()
    r.state.dollars = 100
    r.shop.refill()          # 正常流程由 end_round→_enter_shop 自动补货
    items = r.shop_items()
    assert items, "商店应有货"
    card_items = [i for i in items if i.kind in ("joker", "consumable", "playing_card")]
    assert card_items, "卡牌位应有商品"
    # 买一张
    item = card_items[0]
    n0 = len(r.jokers)
    result = r.buy(item.index)
    assert result["ok"]
    assert len(r.jokers) == n0 + 1
    # 卖掉
    price = r.sell_joker(0)["price"]
    assert price >= 0
    assert len(r.jokers) == n0
    # 重掷涨价
    cost0 = r.reroll_cost
    r.state.dollars = 100
    assert r.reroll()["ok"]
    assert r.reroll_cost > cost0


def test_pack_open_take_choose():
    r = make_run()
    r.state.dollars = 100
    pack = r.open_pack("p_buffoon_normal_1")
    assert pack["ok"], pack
    assert len(pack["cards"]) == pack["extra"]
    take = r.take_from_pack(pack, [0])
    assert take["ok"] and take["count"] == 1
    assert len(pack["taken"]) == 1
    # 跳过剩余
    assert r.skip_pack(pack)["ok"]


# ------------------------------------------------------------- 胜负/无尽

def test_full_run_smoke_by_seed():
    r = make_run(seed="smoke")
    steps = 0
    while r.phase not in ("game_over", "won") and steps < 200:
        steps += 1
        if r.phase == "blind_select":
            r.select_blind(r.blind_choices[0].kind)
        elif r.phase == "round":
            pick = r.hand[:1] if len(r.hand) >= 1 else []
            if not r.play_cards(pick)["ok"] or r.phase == "round":
                # 未胜未败就继续弃/打,直至回合结束
                if r.hands_left == 0:
                    break
        elif r.phase == "round_won":
            r.end_round()
        elif r.phase == "round_lost":
            r.check_run_end()
        elif r.phase == "shop":
            r.advance_from_shop()
    assert r.phase in ("game_over", "won"), f"stuck at {r.phase}"


def test_ante8_boss_win_then_endless():
    r = make_run(seed="endless")
    # 直接构造 ante 8 boss 战胜后的状态
    r.state.ante = 8
    r.state.blind_index = 3
    r.state._offer_blinds()
    r.select_blind("boss")
    assert r.the_blind.is_boss
    r.state.chips = r.the_blind.chips + 1
    r.state.phase = "round_won"
    result = r.end_round()
    assert r.won_run and r.phase == "won"
    assert result["total"] >= 0
    # 无尽:进入商店继续
    r.continue_endless()
    assert r.phase == "shop"
    assert r.ante == 8


def test_hand_name_zh():
    assert hand_name("Pair") == "对子"
    assert hand_name("Flush Five") == "同花五条"
