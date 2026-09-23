from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalGroup
from textual.widgets import Button, Header, Footer, Static

from .common import GameLayout, GameScreen, PreparationButton, RightRow1, Tag


class SettlementPanel(VerticalGroup):

    def compose(self) -> ComposeResult:
        yield Static("提现: $5", id="cash_out")
        yield Horizontal(
            Static("大盲注 至少得分: 450", id="blind_result"),
            Static("$$$$", id="blind_reward"),
            id="settlement_row_1"
        )
        yield Static("· " * 16, id="settlement_divider")
        yield Horizontal(
            Static("1 剩余出牌次数（每次$1）", id="hands_left"),
            Static("$", id="hands_money"),
            id="settlement_row_2"
        )
        yield PreparationButton("收下", id="collect")


class SettlementArea(VerticalGroup):

    def compose(self) -> ComposeResult:
        yield SettlementPanel()


class RightRow2Sub(Horizontal):

    def compose(self) -> ComposeResult:
        yield SettlementPanel()
        yield Tag()

class SettlementScreen(GameScreen):
    """结算场景。"""

    CSS_PATH = ["../css/common.tcss", "../css/settlement.tcss"]

    initial_focus_id = "collect"

    def __init__(self, game_state=None) -> None:
        super().__init__()
        self.game_state = game_state

    def compose(self) -> ComposeResult:
        yield Header()
        yield GameLayout(RightRow1(), RightRow2Sub())
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "collect":
            from .shop import ShopScreen

            self.app.push_screen(ShopScreen(self.game_state))
