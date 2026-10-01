"""Textual Pilot 端到端冒烟:首页 → 选牌组 → 盲注选择 → 战斗。

不追求覆盖所有分支,只保证接线正确(屏幕流转、引擎状态同步、无崩溃)。
"""

import asyncio
import os

# 屏幕推入/切换有滑动过渡动画;动画期间控件 region 在移动,pilot.click 会点空。
os.environ.setdefault("TEXTUAL_ANIMATIONS", "none")

from balatro_tui.app import BalatroApp
from balatro_tui.screens.battle import BattleScreen, HandCard
from balatro_tui.screens.deck_select import DeckSelectScreen
from balatro_tui.screens.preparation import PreparationScreen


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


def _live_hand_cards(battle, run_state) -> list:
    """过滤仍在对局手牌中的控件(刚卸载的旧控件可能仍在 query 结果里)。"""
    live_ids = {id(c) for c in run_state.hand}
    return [w for w in battle.query(HandCard) if id(w.card) in live_ids]


def test_app_smoke_home_to_battle():
    async def main():
        app = BalatroApp()
        async with app.run_test() as pilot:
            await click_when_ready(pilot, app.screen.query_one("#start_btn"))
            await pilot.pause(0.2)
            assert isinstance(app.screen, DeckSelectScreen)

            await pilot.press("enter")          # 确认:红牌 + 白注
            await pilot.pause(0.2)
            assert app.run_state is not None
            assert isinstance(app.screen, PreparationScreen)
            assert app.run_state.phase == "blind_select"
            assert app.run_state.blind_choices

            # 跳过小盲 → 盲注列重建(即时型标签当场结算,故 tags 可能为空)
            skip_btn = app.screen.query_one(".blind_skip_btn")
            assert await click_when_ready(pilot, skip_btn)
            await pilot.pause(0.2)
            assert app.run_state.skips == 1, "跳过应记一次"
            assert app.run_state.phase == "blind_select"

            # 开打当前盲注
            select_btn = next(b for b in app.screen.query(".blind_select_btn")
                              if not b.disabled)
            assert await click_when_ready(pilot, select_btn)
            await pilot.pause(0.2)
            assert isinstance(app.screen, BattleScreen)
            assert app.run_state.phase == "round"

            battle = app.screen
            widgets = _live_hand_cards(battle, app.run_state)
            assert len(widgets) == app.run_state.hand_size

            battle.toggle_card(widgets[0])
            battle.toggle_card(widgets[1])
            assert len(battle._selected_cards()) == 2

            await click_when_ready(pilot, battle.query_one("#play_hand"))
            await pilot.pause(0.2)
            assert app.run_state.hands_left == 3
            assert app.run_state.last_score_display is not None

            # 弃牌(红牌 4 - 1 = 3)
            widgets = _live_hand_cards(battle, app.run_state)
            battle.toggle_card(widgets[0])
            await click_when_ready(pilot, battle.query_one("#discard_hand"))
            await pilot.pause(0.2)
            assert app.run_state.discards_left == 3

    _run(main())


def test_app_smoke_run_info_and_collection():
    async def main():
        app = BalatroApp()
        async with app.run_test() as pilot:
            await click_when_ready(pilot, app.screen.query_one("#collection_btn"))
            await pilot.pause(0.2)
            await pilot.press("escape")
            await pilot.pause(0.2)

    _run(main())
