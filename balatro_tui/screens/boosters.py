from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalGroup
from textual.widgets import Button, Header, Footer, Static

from .common import (
    FocusableStatic,
    GameLayout,
    GameScreen,
    PreparationButton,
    RightRow1,
)

PACK_CARDS = [
    ("[小丑]", "打出时给予 X4 倍率"),
    ("[小丑]", "已打出的牌每有一张 方片，+3 倍率"),
]


class PackCards(Horizontal):

    def compose(self) -> ComposeResult:
        for index, (label, tooltip) in enumerate(PACK_CARDS, start=1):
            card = FocusableStatic(label, id=f"pack_card_{index}")
            card.tooltip = tooltip
            yield card


class PackBar(Horizontal):

    def compose(self) -> ComposeResult:
        yield Static("小丑包 选择 1", id="pack_name")
        yield PreparationButton("选择", id="pack_select")
        yield PreparationButton("跳过", id="pack_skip")


class BoostersArea(VerticalGroup):

    def compose(self) -> ComposeResult:
        yield PackCards()
        yield PackBar()


class BoostersScreen(GameScreen):
    """补充包选择场景。"""

    CSS_PATH = ["../css/common.tcss", "../css/boosters.tcss"]

    def __init__(self, game_state=None) -> None:
        super().__init__()
        self.game_state = game_state

    def compose(self) -> ComposeResult:
        yield Header()
        yield GameLayout(RightRow1(), BoostersArea())
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id in ("pack_select", "pack_skip"):
            self.app.pop_screen()
