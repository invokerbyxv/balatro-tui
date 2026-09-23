from textual import events
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

JOKERS_ON_SALE = [
    ("$2", "[小丑]", "打出时给予 X4 倍率"),
    ("$4", "[小丑]", "已打出的牌每有一张 方片，+3 倍率"),
]

PACKS_ON_SALE = [
    ("$10", "[底注1优惠券]", "使底注的利息上限提高 $2"),
    ("$4", "[小丑包]", "从 2 张小丑牌中选择 1 张"),
    ("$4", "[秘法包]", "从 2 张塔罗牌中选择 1 张"),
]


def _shop_item(index: int, price: str, label: str, tooltip: str) -> VerticalGroup:
    item = FocusableStatic(label, id=f"shop_item_{index}")
    item.tooltip = tooltip
    return VerticalGroup(Static(price, classes="price"), item, classes="item")


class GoodsRow(Horizontal):

    def compose(self) -> ComposeResult:
        for index, (price, label, tooltip) in enumerate(JOKERS_ON_SALE, start=1):
            yield _shop_item(index, price, label, tooltip)


class PackRow(Horizontal):

    def compose(self) -> ComposeResult:
        for index, (price, label, tooltip) in enumerate(PACKS_ON_SALE, start=3):
            yield _shop_item(index, price, label, tooltip)


class ShopGoods(VerticalGroup):

    def compose(self) -> ComposeResult:
        yield GoodsRow()
        yield PackRow()


class ShopPanel(Horizontal):

    def compose(self) -> ComposeResult:
        yield VerticalGroup(
            PreparationButton("下一个回合", id="next_round"),
            PreparationButton("重掷 $5", id="reroll"),
            id="shop_actions"
        )
        yield ShopGoods()


class ShopScreen(GameScreen):
    """商店场景。"""

    CSS_PATH = ["../css/common.tcss", "../css/shop.tcss"]

    def __init__(self, game_state=None) -> None:
        super().__init__()
        self.game_state = game_state

    def compose(self) -> ComposeResult:
        yield Header()
        yield GameLayout(RightRow1(), ShopPanel())
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "next_round":
            from .preparation import PreparationScreen

            self.app.push_screen(PreparationScreen(self.game_state))

    def on_click(self, event: events.Click) -> None:
        if event.control.id in ("shop_item_4", "shop_item_5"):
            from .boosters import BoostersScreen

            self.app.push_screen(BoostersScreen(self.game_state))
