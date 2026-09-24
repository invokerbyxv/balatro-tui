from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalGroup
from textual.widgets import Button, Header, Footer, Static

from .common import (
    FocusableStatic,
    GameLayout,
    GameScreen,
    PreparationButton,
    RightRow1, Tag,
)

# 固定在售的补充包类型 (key, 中文名, 价格)
PACKS_ON_SALE = [
    ("buffoon", "小丑包", 4),
    ("arcana", "秘法包", 4),
    ("celestial", "星球包", 4),
]


class ShopItem(FocusableStatic):
    """一件在售小丑。"""

    def __init__(self, index: int, joker: dict, **kwargs) -> None:
        super().__init__(f"${joker['cost']} {joker['label']}", **kwargs)
        self.index = index
        self.joker = joker
        self.tooltip = joker.get("desc") or "小丑牌"

    def on_click(self, event) -> None:
        self.screen.buy_joker(self.index)
        event.stop()


class PackItem(FocusableStatic):

    def __init__(self, pack_index: int, ui_index: int, name: str, cost: int, **kwargs) -> None:
        super().__init__(f"${cost} [{name}]", **kwargs)
        self.pack_index = pack_index
        self.pack_key = PACKS_ON_SALE[pack_index][0]
        self.pack_name = name
        self.pack_cost = cost
        self.tooltip = f"打开{name},选择{name}内容"

    def on_click(self, event) -> None:
        self.screen.buy_pack(self.pack_index)
        event.stop()


class GoodsRow(Horizontal):

    def compose(self) -> ComposeResult:
        # 商品在 on_mount 时由 ShopGoods._rebuild 填充
        yield from ()


class PackRow(Horizontal):

    def compose(self) -> ComposeResult:
        # 补充包在 on_mount 时由 ShopGoods._rebuild 填充
        yield from ()


class ShopGoods(VerticalGroup):

    def compose(self) -> ComposeResult:
        yield Static("小丑在售", classes="goods_label")
        yield GoodsRow()
        yield Static("补充包在售", classes="goods_label")
        yield PackRow()

    def _rebuild(self):
        """购买/重掷后重建当前商品行(用单调 id 避免重建冲突)。"""
        self._uid = getattr(self, "_uid", 0)
        goods = self.query_one(GoodsRow)
        goods.remove_children()
        for index, joker in enumerate(self.screen.game_state.shop_jokers):
            self._uid += 1
            goods.mount(ShopItem(index, joker, id=f"shop_item_{self._uid}"))
        packs = self.query_one(PackRow)
        packs.remove_children()
        for pack_index, (key, name, cost) in enumerate(PACKS_ON_SALE):
            self._uid += 1
            packs.mount(PackItem(pack_index, pack_index, name, cost, id=f"pack_{self._uid}"))


class ShopPanel(Horizontal):

    def compose(self) -> ComposeResult:
        yield VerticalGroup(
            PreparationButton("下一个回合", id="next_round"),
            PreparationButton("重掷", id="reroll"),
            id="shop_actions"
        )
        yield ShopGoods()
        yield Tag()


class RightRow2Sub(Horizontal):

    def compose(self) -> ComposeResult:
        yield ShopPanel()
        yield Tag()


class ShopScreen(GameScreen):
    """商店场景:买小丑、买包、重掷、下一回合。"""

    CSS_PATH = ["../css/common.tcss", "../css/shop.tcss"]

    BINDINGS = [*GameScreen.BINDINGS]

    def __init__(self, game_state=None) -> None:
        super().__init__()
        self.game_state = game_state

    def compose(self) -> ComposeResult:
        yield Header()
        yield GameLayout(RightRow1(), RightRow2Sub())
        yield Footer()

    def on_mount(self) -> None:
        if not getattr(self.game_state, "shop_jokers", None):
            self.game_state.generate_shop()
        self.refresh_run_ui()
        self.query_one(ShopGoods)._rebuild()
        self._sync_reroll_label()
        try:
            self.query_one("#next_round", PreparationButton).focus()
        except Exception:
            pass

    def _sync_reroll_label(self) -> None:
        try:
            self.query_one("#reroll", PreparationButton).label = f"重掷 ${self.game_state.reroll_cost}"
        except Exception:
            pass

    def buy_joker(self, index: int) -> None:
        if self.game_state.buy_joker(index):
            self.query_one(ShopGoods)._rebuild()
            self.refresh_run_ui()

    def buy_pack(self, index: int) -> None:
        key, name, cost = PACKS_ON_SALE[index]
        if not self.game_state.spend(cost):
            return
        self.refresh_run_ui()
        from .boosters import BoostersScreen
        self.app.push_screen(BoostersScreen(self.game_state, pack_key=key, cost=cost))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "next_round":
            self.game_state.advance_ante_blind()
            self.game_state.generate_shop()
            from .preparation import PreparationScreen
            self.app.push_screen(PreparationScreen(self.game_state))
        elif bid == "reroll":
            if self.game_state.reroll_shop():
                self.query_one(ShopGoods)._rebuild()
                self._sync_reroll_label()
                self.refresh_run_ui()