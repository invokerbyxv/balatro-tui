"""Textual Pilot 全流程鼠标点击测试:首页 → 选牌组 → 盲注 → 战斗 → 结算 → 商店 → 卡包。

覆盖范围(每一步都尽量用 pilot.click 模拟真实鼠标点击):
- 首页按钮导航(开始游戏 / 收藏 / 收藏分类详情)
- 选牌组界面左右箭头切换 + 确认开局
- 盲注选择:跳过拿标签、开打、重掷 BOSS(Director's Cut)
- 战斗:点选牌预览牌型、出牌、弃牌、排序、游戏信息、消耗品(带目标)使用流、
  小丑出售对话框(确认/取消)
- 结算:提现 → 商店、失败 → 回首页、ante 8 通关 → 无尽模式
- 商店:买商品、买卡包(选卡/跳过)、重掷、卖小丑、使用星球牌、下一回合

胜负场景用引擎作弊开关(the_blind.chips)保证确定性,其余交互全部走 UI。
"""

import asyncio
import os

from textual.widgets import Static

# 屏幕推入/切换有滑动过渡动画;动画期间控件 region 在移动,pilot.click 会点空。
os.environ.setdefault("TEXTUAL_ANIMATIONS", "none")

from balatro_tui.app import BalatroApp
from balatro_tui.game_engine import RunState
from balatro_tui.screens.battle import BattleScreen, HandCard
from balatro_tui.screens.boosters import BoostersScreen, PackChoice
from balatro_tui.screens.collection import CollectionScreen, CollectionDetailScreen, CollectionList
from balatro_tui.screens.common import (
    ConsumableHorizontalScroll,
    SellDialog,
    JokerHorizontalScroll,
)
from balatro_tui.screens.deck_select import DeckSelectScreen, SelectionRow
from balatro_tui.screens.game_info import GameInfoScreen
from balatro_tui.screens.home import HomeScreen
from balatro_tui.screens.preparation import Blind, OfferRow, PreparationScreen
from balatro_tui.screens.settlement import SettlementScreen
from balatro_tui.screens.shop import ShopScreen, ShopGoodsItem, GoodsRow, PackRow

SEED = "20261001"


def _run(coro):
    return asyncio.run(coro)


async def click_when_ready(pilot, widget, timeout_s: float = 2.0) -> bool:
    """等控件布局就绪(region 非零)且动画结束再点击。"""
    waited = 0.0
    step = 0.05
    while widget.region.width == 0 and waited < timeout_s:
        await asyncio.sleep(step)
        waited += step
    await pilot.wait_for_scheduled_animations()
    return await pilot.click(widget)


async def pause(pilot, t: float = 0.2):
    await pilot.pause(t)


def static_text(w) -> str:
    """Textual Static 内容(兼容不同版本的内部字段)。"""
    for attr in ("content", "_content", "renderable"):
        if hasattr(w, attr):
            return str(getattr(w, attr))
    return ""


def live_hand_cards(battle, run_state) -> list:
    """过滤仍在对局手牌中的控件(刚卸载的旧控件可能仍在 query 结果里)。"""
    live_ids = {id(c) for c in run_state.hand}
    return [w for w in battle.query(HandCard) if id(w.card) in live_ids]


async def new_app(pilot_factory_size=(140, 44)):
    app = BalatroApp()
    return app


async def start_run_and_enter_prep(app, seed: str = SEED) -> RunState:
    """直接构造一局红牌白注并把 PreparationScreen 推上屏(牌组选择另有专测)。"""
    run = RunState(seed)
    run.start_run("b_red", 1)
    app.run_state = run
    app.push_screen(PreparationScreen(run))
    return run


async def enter_battle(pilot, app, seed: str = SEED) -> tuple[BattleScreen, RunState]:
    """进盲注选择 → 点击【选择】开打。"""
    run = await start_run_and_enter_prep(app, seed)
    await pause(pilot, 0.3)
    select_btn = next(b for b in app.screen.query(".blind_select_btn") if not b.disabled)
    assert await click_when_ready(pilot, select_btn)
    await pause(pilot, 0.3)
    assert isinstance(app.screen, BattleScreen)
    return app.screen, run


async def win_quickly(pilot, battle, run: RunState) -> SettlementScreen:
    """作弊把盲注目标降到 1,点一张牌出牌即可获胜,进入结算。"""
    run.state.the_blind.chips = 1
    widget = live_hand_cards(battle, run)[0]
    assert await click_when_ready(pilot, widget)
    await pause(pilot)
    assert await click_when_ready(pilot, battle.query_one("#play_hand"))
    await pause(pilot, 0.4)
    assert isinstance(app_screen := battle.app.screen, SettlementScreen)
    return app_screen


# ===========================================================================
# 首页 / 收藏
# ===========================================================================

def test_home_buttons_and_collection():
    async def main():
        app = BalatroApp()
        async with app.run_test(size=(140, 44)) as pilot:
            assert isinstance(app.screen, HomeScreen)

            # 开始游戏 → 选牌组
            await click_when_ready(pilot, app.screen.query_one("#start_btn"))
            await pause(pilot)
            assert isinstance(app.screen, DeckSelectScreen)
            await pilot.press("escape")
            await pause(pilot)
            assert isinstance(app.screen, HomeScreen)

            # 收藏 → 分类列表
            await click_when_ready(pilot, app.screen.query_one("#collection_btn"))
            await pause(pilot)
            coll = app.screen
            assert isinstance(coll, CollectionScreen)
            btns = list(coll.query(CollectionList).first().query("Button"))
            assert len(btns) == 6

            # 点击「小丑牌」分类 → 详情表有数据行
            await click_when_ready(pilot, coll.query_one("#jokers_c_btn"))
            await pause(pilot, 0.3)
            assert isinstance(app.screen, CollectionDetailScreen)
            table = app.screen.query_one("DataTable")
            assert table.row_count > 0
            await pilot.press("escape")
            await pause(pilot)
            assert isinstance(app.screen, CollectionScreen)
            await pilot.press("escape")
            await pause(pilot)
            assert isinstance(app.screen, HomeScreen)

    _run(main())


# ===========================================================================
# 选牌组
# ===========================================================================

def test_deck_select_arrows_and_confirm():
    async def main():
        app = BalatroApp()
        async with app.run_test(size=(140, 44)) as pilot:
            await click_when_ready(pilot, app.screen.query_one("#start_btn"))
            await pause(pilot)
            deck_row = app.screen.query_one("#deck_select", SelectionRow)
            stake_row = app.screen.query_one("#stake_select", SelectionRow)

            # 鼠标点 ">" 换牌组(循环 2 步),点 ">" 换赌注到红注
            await click_when_ready(pilot, app.screen.query_one("#deck_select_right"))
            await pause(pilot)
            idx_after_one = deck_row.index
            await click_when_ready(pilot, app.screen.query_one("#deck_select_right"))
            await pause(pilot)
            assert deck_row.index == (idx_after_one + 1) % len(deck_row.row)
            await click_when_ready(pilot, app.screen.query_one("#stake_select_right"))
            await pause(pilot)
            assert stake_row.index == 1

            # 点选行本身(模拟用户点在行区域)让焦点离开 ">" 按钮,回车才是确认开局
            await click_when_ready(pilot, deck_row)
            await pause(pilot, 0.1)
            await pilot.press("enter")
            await pause(pilot, 0.3)
            assert isinstance(app.screen, PreparationScreen)
            assert app.run_state is not None
            assert app.run_state.phase == "blind_select"
            assert app.run_state.state.stake == 2
            assert app.run_state.state.deck_key == deck_row.row[deck_row.index]["key"]

    _run(main())


# ===========================================================================
# 盲注选择
# ===========================================================================

def test_blind_skip_gains_tag_and_rebuilds():
    async def main():
        app = BalatroApp()
        async with app.run_test(size=(140, 44)) as pilot:
            run = await start_run_and_enter_prep(app)
            await pause(pilot, 0.3)
            assert run.skips == 0

            skip_btn = app.screen.query_one(".blind_skip_btn")
            await click_when_ready(pilot, skip_btn)
            await pause(pilot, 0.3)

            assert run.skips == 1, "跳过应记一次"
            notice = static_text(app.screen.query_one("#notice"))
            assert notice.startswith("跳过"), f"公告应提示跳过结果,实际: {notice!r}"
            # 跳过后盲注列重建:小盲被跳过,当前可选的应是大盲/后续
            kinds = [o["kind"] for o in app.screen.offers]
            assert "small" not in kinds
            # 即时型标签当场结算,待用标签条不保证非空,只验证重建无残留
            assert len(app.screen.query(".blind_select_btn")) == len(app.screen.offers)

    _run(main())


def test_blind_cards_layout_boss_preview_and_tag_hint():
    async def main():
        app = BalatroApp()
        async with app.run_test(size=(140, 44)) as pilot:
            run = await start_run_and_enter_prep(app)
            await pause(pilot, 0.3)

            # 三张盲注卡全部可见:小盲(可选)、大盲、BOSS 预览(不可选)
            assert [o["kind"] for o in app.screen.offers] == ["small", "big", "boss"]
            blinds = list(app.screen.query(OfferRow).first().query(Blind))
            assert len(blinds) == 3
            assert blinds[0].selectable is True
            assert all(b.selectable is False for b in blinds[1:])

            # 名称/过关需求/奖励同一行;非 BOSS 无效果行,BOSS 有
            assert len(list(blinds[0].query(".blind_stats Static"))) == 3
            assert not list(blinds[0].query(".blind_effect"))
            assert list(blinds[2].query(".blind_effect"))

            # 跳过按钮提前展示将获得的标签(与引擎预览一致,含 tooltip 说明)
            skip_btn = app.screen.query_one(".blind_skip_btn")
            preview = run.skip_tag_preview("small")
            assert preview, "引擎应返回标签预览"
            assert preview["name"] in str(skip_btn.label)
            assert skip_btn.tooltip == preview["desc"]

            # 跳过后重建的卡片继续带下一个盲注的标签预览
            await click_when_ready(pilot, skip_btn)
            await pause(pilot, 0.4)
            assert run.skips == 1
            next_preview = run.skip_tag_preview(app.screen.offers[0]["kind"])
            new_btn = app.screen.query_one(".blind_skip_btn")
            assert next_preview["name"] in str(new_btn.label)

    _run(main())


def test_boss_reroll_button_flow():
    async def main():
        app = BalatroApp()
        async with app.run_test(size=(140, 44)) as pilot:
            run = await start_run_and_enter_prep(app)
            await pause(pilot, 0.3)

            # 默认没有 Director's Cut,重掷按钮隐藏
            reroll = app.screen.query_one("#reroll_boss")
            assert reroll.display is False

            # 跳过小盲、大盲,让 BOSS 成为当前可选盲注
            for _ in range(2):
                skip_btn = app.screen.query_one(".blind_skip_btn")
                await click_when_ready(pilot, skip_btn)
                await pause(pilot, 0.4)
            assert run.blind_choices[0].kind == "boss"

            # 作弊:给重掷能力(引擎按 boss_reroll_limit 判定)
            run.state.boss_reroll_limit = 2
            run.state.boss_reroll_cost = 5
            run.state.dollars = 50
            old_boss = next(o.key for o in run.blind_choices if o.kind == "boss")
            app.screen._sync_reroll()
            assert reroll.display is True
            assert "重掷" in str(reroll.label)

            await click_when_ready(pilot, reroll)
            await pause(pilot, 0.4)
            assert static_text(app.screen.query_one("#notice")) == "已重掷 BOSS"
            new_boss = next(o.key for o in run.blind_choices if o.kind == "boss")
            assert new_boss != old_boss, "重掷后 BOSS 应换人"
            assert run.state.dollars == 45

    _run(main())


# ===========================================================================
# 战斗
# ===========================================================================

def test_battle_click_select_preview_play_discard_sort():
    async def main():
        app = BalatroApp()
        async with app.run_test(size=(140, 44)) as pilot:
            battle, run = await enter_battle(pilot, app)
            assert run.phase == "round"
            assert len(live_hand_cards(battle, run)) == run.hand_size

            # 鼠标点两张牌 → selected 高亮 + 预览牌型
            widgets = live_hand_cards(battle, run)
            await click_when_ready(pilot, widgets[0])
            await pause(pilot, 0.1)
            await click_when_ready(pilot, widgets[1])
            await pause(pilot, 0.1)
            assert len(battle._selected_cards()) == 2
            preview = static_text(battle.query_one("#played_area"))
            assert preview.startswith("当前组合"), preview

            # 花色排序按钮 → 引擎手牌顺序变化
            await click_when_ready(pilot, battle.query_one("#sort_suit"))
            await pause(pilot, 0.2)
            suits_order = {"S": 0, "H": 1, "C": 2, "D": 3}
            ranks = ["2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K", "A"]
            keys = [(suits_order[c.suit], -ranks.index(c.rank)) for c in run.state.hand]
            assert keys == sorted(keys), "点花色排序后手牌应按花色分组"

            # 出牌 → 出牌数-1、分数入账、左侧信息栏刷新
            hands_before = run.hands_left
            await click_when_ready(pilot, battle.query_one("#play_hand"))
            await pause(pilot, 0.4)
            assert run.hands_left == hands_before - 1
            assert run.chips > 0
            assert run.last_score_display is not None
            played_text = static_text(battle.query_one("#played_area"))
            assert "=" in played_text, "出牌后应展示计分汇总行"

            # 弃牌 → 弃牌数-1
            widgets = live_hand_cards(battle, run)
            await click_when_ready(pilot, widgets[0])
            await pause(pilot, 0.1)
            discards_before = run.discards_left
            await click_when_ready(pilot, battle.query_one("#discard_hand"))
            await pause(pilot, 0.4)
            assert run.discards_left == discards_before - 1

    _run(main())


def test_battle_consumable_target_flow():
    async def main():
        app = BalatroApp()
        async with app.run_test(size=(140, 44)) as pilot:
            battle, run = await enter_battle(pilot, app)
            # 作弊塞一张【战车】(选 1 张牌变黑桃)
            run.state.add_consumable("c_chariot")
            await battle.refresh_run_ui()
            await pause(pilot, 0.3)

            # 点击消耗品条进入目标选择模式
            cons_scroll = battle.query(ConsumableHorizontalScroll).first()
            cons_widget = next(w for w in cons_scroll.children if isinstance(w, Static))
            await click_when_ready(pilot, cons_widget)
            await pause(pilot, 0.2)
            assert battle.target_mode is not None
            confirm = battle.query_one("#confirm_use")
            assert confirm.display is True

            # 未选目标直接点确认 → 不生效
            await click_when_ready(pilot, confirm)
            await pause(pilot, 0.2)
            assert len(run.consumeables) == 1
            assert battle.target_mode is not None

            # 点 1 张手牌 → 确认使用 → 消耗品消失
            widget = live_hand_cards(battle, run)[0]
            await click_when_ready(pilot, widget)
            await pause(pilot, 0.1)
            await click_when_ready(pilot, confirm)
            await pause(pilot, 0.4)
            assert len(run.consumeables) == 0
            assert battle.target_mode is None
            assert confirm.display is False
            assert "使用了" in static_text(battle.query_one("#played_area"))
            # 战车把选中的牌变黑桃
            assert widget.card.suit == "S"

    _run(main())


def test_battle_joker_sell_dialog_cancel_and_confirm():
    async def main():
        app = BalatroApp()
        async with app.run_test(size=(140, 44)) as pilot:
            battle, run = await enter_battle(pilot, app)
            joker = run.state.add_joker("j_joker")
            price = run.state.sell_value(joker)
            await battle.refresh_run_ui()
            await pause(pilot, 0.3)

            joker_widget = next(
                w for w in battle.query(JokerHorizontalScroll).first().children
                if isinstance(w, Static))
            dollars_before = run.dollars

            # 点击小丑 → 出售对话框;取消 → 原样保留
            await click_when_ready(pilot, joker_widget)
            await pause(pilot, 0.3)
            assert isinstance(app.screen, SellDialog)
            assert "出售" in static_text(app.screen.query("SellDialog Static").first())
            await click_when_ready(pilot, app.screen.query_one("#sell_cancel"))
            await pause(pilot, 0.3)
            assert isinstance(app.screen, BattleScreen)
            assert len(run.jokers) == 1

            # 再点 → 确认出售 → 金钱增加、小丑消失
            await click_when_ready(pilot, joker_widget)
            await pause(pilot, 0.3)
            await click_when_ready(pilot, app.screen.query_one("#sell_ok"))
            await pause(pilot, 0.4)
            assert isinstance(app.screen, BattleScreen)
            assert len(run.jokers) == 0
            assert run.dollars == dollars_before + price

    _run(main())


def test_battle_game_info_screen():
    async def main():
        app = BalatroApp()
        async with app.run_test(size=(140, 44)) as pilot:
            battle, run = await enter_battle(pilot, app)

            await click_when_ready(pilot, battle.query_one("#info"))
            await pause(pilot, 0.3)
            info = app.screen
            assert isinstance(info, GameInfoScreen)
            assert "累计出牌" in static_text(info.query_one("#run_stats"))
            # 默认牌型页;按 v 切优惠券页,再切回
            assert info.query_one("#hand_panel").display is True
            await pilot.press("v")
            await pause(pilot, 0.1)
            assert info.query_one("#voucher_panel").display is True
            assert info.query_one("#hand_panel").display is False
            await pilot.press("h")
            await pause(pilot, 0.1)
            assert info.query_one("#hand_panel").display is True

            await pilot.press("escape")
            await pause(pilot, 0.3)
            assert isinstance(app.screen, BattleScreen)

    _run(main())


# ===========================================================================
# 结算:提现 / 失败 / ante 8 通关无尽
# ===========================================================================

def test_win_round_settlement_then_shop():
    async def main():
        app = BalatroApp()
        async with app.run_test(size=(140, 44)) as pilot:
            battle, run = await enter_battle(pilot, app)
            settlement = await win_quickly(pilot, battle, run)

            # 提现明细:标题 + 盲注奖励行
            assert "提现" in static_text(settlement.query_one("#cash_out"))
            row_labels = [static_text(w) for w in settlement.query(".row_label")]
            assert any("盲注奖励" in t for t in row_labels)
            dollars_after_cash_out = run.dollars
            assert dollars_after_cash_out > 4, "提现应发放盲注奖励"

            # 点击【收下】→ 商店
            await click_when_ready(pilot, settlement.query_one("#collect"))
            await pause(pilot, 0.4)
            assert isinstance(app.screen, ShopScreen)
            assert run.phase == "shop"

    _run(main())


def test_round_lost_settlement_back_home():
    async def main():
        app = BalatroApp()
        async with app.run_test(size=(140, 44)) as pilot:
            battle, run = await enter_battle(pilot, app)
            # 作弊:目标设为天文数字,打完所有出牌必输
            run.state.the_blind.chips = 10 ** 12
            for _ in range(10):
                if run.phase != "round":
                    break
                widget = live_hand_cards(battle, run)[0]
                await click_when_ready(pilot, widget)
                await pause(pilot, 0.1)
                await click_when_ready(pilot, battle.query_one("#play_hand"))
                await pause(pilot, 0.4)
            assert run.phase in ("round_lost", "game_over")
            assert isinstance(app.screen, SettlementScreen)
            assert "未达成目标" in static_text(app.screen.query_one("#cash_out"))

            # 失败结算点【返回首页】
            await click_when_ready(pilot, app.screen.query_one("#collect"))
            await pause(pilot, 0.4)
            assert isinstance(app.screen, HomeScreen)

    _run(main())


def test_ante8_boss_win_endless_mode():
    async def main():
        app = BalatroApp()
        async with app.run_test(size=(140, 44)) as pilot:
            run = await start_run_and_enter_prep(app, seed="88888888")
            run.state.ante = 8          # 作弊:直接跳到 ante 8
            await pause(pilot, 0.3)

            # 跳过小盲、大盲,直接打 BOSS
            for _ in range(2):
                skip_btn = app.screen.query_one(".blind_skip_btn")
                await click_when_ready(pilot, skip_btn)
                await pause(pilot, 0.4)
            assert run.skips == 2
            select_btn = next(b for b in app.screen.query(".blind_select_btn")
                              if not b.disabled)
            await click_when_ready(pilot, select_btn)
            await pause(pilot, 0.4)
            assert isinstance(app.screen, BattleScreen)
            battle = app.screen

            # 作弊获胜 → ante 8 BOSS 通关 → 结算显示「通关胜利!」
            settlement = await win_quickly(pilot, battle, run)
            assert settlement.mode == "won"
            assert "通关胜利" in static_text(settlement.query_one("#cash_out"))

            # 【继续(无尽模式)】→ 商店,ante 推进到 9
            await click_when_ready(pilot, settlement.query_one("#collect"))
            await pause(pilot, 0.4)
            assert isinstance(app.screen, ShopScreen)
            await click_when_ready(pilot, app.screen.query_one("#next_round"))
            await pause(pilot, 0.4)
            assert isinstance(app.screen, PreparationScreen)
            assert run.ante == 9, "无尽模式下一 ante 应为 9"

    _run(main())


# ===========================================================================
# 商店
# ===========================================================================

async def goto_shop(pilot, app, seed: str = SEED):
    run = await start_run_and_enter_prep(app, seed)
    await pause(pilot, 0.3)
    select_btn = next(b for b in app.screen.query(".blind_select_btn") if not b.disabled)
    await click_when_ready(pilot, select_btn)
    await pause(pilot, 0.3)
    battle = app.screen
    settlement = await win_quickly(pilot, battle, run)
    await click_when_ready(pilot, settlement.query_one("#collect"))
    await pause(pilot, 0.4)
    assert isinstance(app.screen, ShopScreen)
    return app.screen, run


def test_shop_buy_goods_reroll_and_next_round():
    async def main():
        app = BalatroApp()
        async with app.run_test(size=(140, 44)) as pilot:
            shop, run = await goto_shop(pilot, app)
            run.state.dollars = 100
            await shop.refresh_run_ui()
            await pause(pilot, 0.3)

            # --- 买第一件卡牌位商品(小丑/消耗牌/扑克牌都可能) ---
            inv_before = (len(run.jokers), len(run.consumeables), len(run.deck))
            goods = list(shop.query(GoodsRow).first().query(ShopGoodsItem))
            assert goods, "卡牌位应有商品"
            target = goods[0]
            label = static_text(target)
            await click_when_ready(pilot, target)
            await pause(pilot, 0.5)
            inv_after = (len(run.jokers), len(run.consumeables), len(run.deck))
            assert inv_after != inv_before, f"买下 {label!r} 后库存应变化"
            assert run.dollars < 100, "购买应扣钱"

            # --- 重掷 → 扣钱、商品重建 ---
            dollars_before = run.dollars
            await click_when_ready(pilot, shop.query_one("#reroll"))
            await pause(pilot, 0.5)
            assert run.dollars < dollars_before
            assert run.shop.reroll_cost > 5, "重掷后价格应上涨"

            # --- 下一回合 → 盲注选择 ---
            await click_when_ready(pilot, shop.query_one("#next_round"))
            await pause(pilot, 0.4)
            assert isinstance(app.screen, PreparationScreen)
            assert run.phase == "blind_select"

    _run(main())


def test_shop_pack_open_take_and_skip():
    async def main():
        app = BalatroApp()
        async with app.run_test(size=(140, 44)) as pilot:
            shop, run = await goto_shop(pilot, app)
            run.state.dollars = 100
            await shop.refresh_run_ui()
            await pause(pilot, 0.3)

            packs = list(shop.query(PackRow).first().query(ShopGoodsItem))
            if not packs:
                # 该种子商店没刷卡包:重掷一次再试
                await click_when_ready(pilot, shop.query_one("#reroll"))
                await pause(pilot, 0.5)
                packs = list(shop.query(PackRow).first().query(ShopGoodsItem))
            assert packs, "商店应能刷出卡包"

            # --- 买卡包 → 补充包界面,点选 1 张 → 选择,直至选满自动关闭 ---
            await click_when_ready(pilot, packs[0])
            await pause(pilot, 0.5)
            assert isinstance(app.screen, BoostersScreen)
            boost = app.screen
            choose = boost.pack.get("choose", 1)
            for _ in range(choose + 2):
                if not isinstance(app.screen, BoostersScreen):
                    break
                boost = app.screen
                cards = list(boost.query(PackChoice))
                assert cards, "补充包里应有卡"
                await click_when_ready(pilot, cards[0])
                await pause(pilot, 0.2)
                await click_when_ready(pilot, boost.query_one("#pack_select"))
                await pause(pilot, 0.4)
            assert isinstance(app.screen, ShopScreen), "选满后应自动回到商店"

            # --- 再买一包,直接点【跳过】 → 回商店 ---
            packs = list(shop.query(PackRow).first().query(ShopGoodsItem))
            if packs:
                dollars_before = run.dollars
                await click_when_ready(pilot, packs[0])
                await pause(pilot, 0.5)
                if isinstance(app.screen, BoostersScreen):
                    await click_when_ready(pilot, app.screen.query_one("#pack_skip"))
                    await pause(pilot, 0.4)
                    assert isinstance(app.screen, ShopScreen)
                    assert run.dollars < dollars_before

    _run(main())


def test_shop_sell_joker_and_use_planet():
    async def main():
        app = BalatroApp()
        async with app.run_test(size=(140, 44)) as pilot:
            shop, run = await goto_shop(pilot, app)
            run.state.dollars = 100

            # --- 卖小丑:确保持有,点击 → 对话框 → 确认出售 ---
            joker = run.state.add_joker("j_joker")
            price = run.state.sell_value(joker)
            await shop.refresh_run_ui()
            await pause(pilot, 0.3)
            dollars_before = run.dollars
            joker_widget = next(
                w for w in shop.query(JokerHorizontalScroll).first().children
                if isinstance(w, Static))
            await click_when_ready(pilot, joker_widget)
            await pause(pilot, 0.3)
            assert isinstance(app.screen, SellDialog)
            await click_when_ready(pilot, app.screen.query_one("#sell_ok"))
            await pause(pilot, 0.4)
            assert isinstance(app.screen, ShopScreen)
            assert len(run.jokers) == 0
            assert run.dollars == dollars_before + price

            # --- 商店里点星球牌(无需目标)→ 直接使用,牌型升级 ---
            level_before = run.hand_levels.get("High Card", {}).get("level", 1)
            run.state.add_consumable("c_pluto")
            await shop.refresh_run_ui()
            await pause(pilot, 0.3)
            cons_widget = next(
                w for w in shop.query(ConsumableHorizontalScroll).first().children
                if isinstance(w, Static))
            await click_when_ready(pilot, cons_widget)
            await pause(pilot, 0.4)
            assert len(run.consumeables) == 0
            level_after = run.hand_levels.get("High Card", {}).get("level", 1)
            assert level_after == level_before + 1, "星球牌应升级对应牌型"

            # --- 需要目标的消耗品在商店点不开使用流程,只提示 ---
            run.state.add_consumable("c_chariot")
            await shop.refresh_run_ui()
            await pause(pilot, 0.3)
            cons_widget = next(
                w for w in shop.query(ConsumableHorizontalScroll).first().children
                if isinstance(w, Static))
            await click_when_ready(pilot, cons_widget)
            await pause(pilot, 0.3)
            assert len(run.consumeables) == 1, "商店不应消耗需要目标的消耗品"
            tip = shop.query_one("#next_round").tooltip or ""
            assert "需要手牌目标" in tip

    _run(main())


# ===========================================================================
# 长线 soak:打完一整个 ante(小盲→大盲→BOSS)循环
# ===========================================================================

def test_full_ante_cycle_three_blinds():
    async def main():
        app = BalatroApp()
        async with app.run_test(size=(140, 44)) as pilot:
            run = await start_run_and_enter_prep(app, seed="77777777")
            await pause(pilot, 0.3)

            for expected_kind in ("small", "big", "boss"):
                assert run.phase == "blind_select"
                assert run.blind_choices[0].kind == expected_kind

                # 打当前盲注(作弊保证胜利,专注流程而非数值)
                select_btn = next(b for b in app.screen.query(".blind_select_btn")
                                  if not b.disabled)
                await click_when_ready(pilot, select_btn)
                await pause(pilot, 0.4)
                battle = app.screen
                assert isinstance(battle, BattleScreen)
                run.state.the_blind.chips = 1
                widget = live_hand_cards(battle, run)[0]
                await click_when_ready(pilot, widget)
                await pause(pilot, 0.1)
                await click_when_ready(pilot, battle.query_one("#play_hand"))
                await pause(pilot, 0.5)
                settlement = app.screen
                assert isinstance(settlement, SettlementScreen)

                # 收下 → 商店 → 下一回合(BOSS 打完进入下一 ante)
                await click_when_ready(pilot, settlement.query_one("#collect"))
                await pause(pilot, 0.4)
                assert isinstance(app.screen, ShopScreen)
                await click_when_ready(pilot, app.screen.query_one("#next_round"))
                await pause(pilot, 0.4)
                assert isinstance(app.screen, PreparationScreen)

            # 三个盲注打完,ante 从 1 推进到 2
            assert run.ante == 2
            assert run.blind_choices[0].kind == "small"

    _run(main())
