from textual.app import ComposeResult
from textual.containers import Center, Container, Horizontal, VerticalGroup
from textual.widgets import Button, Header, Footer, Static

from .common import (
    GameLayout,
    GameScreen,
    PreparationButton,
    RightRow1,
    Tag,
)


class Blind(Horizontal):

    def compose(self) -> ComposeResult:
        yield VerticalGroup(
            Center(PreparationButton("选择", id=f"{self.id}_select")),
            Static("盲注"),
            Static("300"),
            Static("$$$"),
            Horizontal(Static("[双倍]"), PreparationButton("跳过盲注", id=f"{self.id}_skip")),
        )


class Boss(Horizontal):

    def compose(self) -> ComposeResult:
        yield VerticalGroup(
            Static("下一回合"),
            Static("窗口"),
            Static("所有方片牌都被削弱"),
            Static("300"),
            Static("$$$"),
            Static("刷新盲注")
        )

class RightRow2Sub(Horizontal):

    def compose(self) -> ComposeResult:
        yield Blind(id="blind_1")
        yield Blind(id="blind_2")
        yield Boss()
        yield Tag()


class RightRow2(Container):
    def compose(self) -> ComposeResult:
        yield RightRow2Sub()


class PreparationScreen(GameScreen):
    """盲注选择场景。"""

    CSS_PATH = ["../css/common.tcss", "../css/preparation.tcss"]

    def __init__(self, game_state=None) -> None:
        super().__init__()
        self.game_state = game_state

    def compose(self) -> ComposeResult:
        yield Header()
        yield GameLayout(RightRow1(), RightRow2())
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "blind_1_select":
            from .battle import BattleScreen

            self.app.push_screen(BattleScreen(self.game_state))
