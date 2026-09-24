from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalGroup
from textual.widgets import Button, Header, Footer, Static

from .common import GameLayout, GameScreen, PreparationButton, RightRow1, Tag


class SettlementPanel(VerticalGroup):

    def __init__(self, state, collected, failed, **kwargs):
        super().__init__(**kwargs)
        self.state = state
        self.collected = collected        # 本次结算的金钱 dict
        self.failed = failed

    def compose(self) -> ComposeResult:
        if self.failed:
            yield Static("未达成目标", id="cash_out")
            yield Static("本局失败 · 没有金钱奖励", classes="fail_text")
        else:
            yield Static(f"提现: ${self.collected['total']}", id="cash_out")
            yield Horizontal(
                Static(f"盲注奖励: ${self.collected['blind_reward']}", id="blind_reward"),
                Static(f"剩余出牌: ${self.collected['hands_money']}", id="hands_money"),
                id="settlement_row_1",
            )
            yield Static(f"利息: ${self.collected['interest']}", id="settlement_interest")
        yield Static("· " * 16, id="settlement_divider")
        label = "返回首页" if self.failed else "收下"
        yield PreparationButton(label, id="collect")


class SettlementArea(VerticalGroup):

    def __init__(self, state, collected, failed, **kwargs):
        super().__init__(**kwargs)
        self.state = state
        self.collected = collected
        self.failed = failed

    def compose(self) -> ComposeResult:
        yield SettlementPanel(self.state, self.collected, self.failed)


class RightRow2Sub(Horizontal):

    def __init__(self, state, collected, failed, **kwargs):
        super().__init__(**kwargs)
        self.state = state
        self.collected = collected
        self.failed = failed

    def compose(self) -> ComposeResult:
        yield SettlementPanel(self.state, self.collected, self.failed)
        yield Tag()


class SettlementScreen(GameScreen):
    """结算场景:胜利展示提现金额,失败返回首页。"""

    CSS_PATH = ["../css/common.tcss", "../css/settlement.tcss"]
    BINDINGS = [
        ("enter", "collect_btn", "确认"),
        *GameScreen.BINDINGS,
    ]

    initial_focus_id = "collect"

    def __init__(self, game_state=None) -> None:
        super().__init__()
        self.game_state = game_state
        self.failed = bool(game_state) and not game_state.won_blind
        self.collected = game_state.collect_money() if (game_state and not self.failed) else {
            "total": 0, "blind_reward": 0, "hands_money": 0, "interest": 0,
        }

    def compose(self) -> ComposeResult:
        yield Header()
        yield GameLayout(RightRow1(), RightRow2Sub(self.game_state, self.collected, self.failed))
        yield Footer()

    def action_collect_btn(self) -> None:
        self._done()

    def _done(self) -> None:
        if self.failed:
            from .home import HomeScreen
            self.app.push_screen(HomeScreen())
        else:
            from .shop import ShopScreen
            self.app.push_screen(ShopScreen(self.game_state))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "collect":
            self._done()