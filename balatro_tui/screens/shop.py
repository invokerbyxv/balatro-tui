from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalGroup, HorizontalGroup
from textual.widgets import Button, Header, Footer, Static

from .common import (
    FocusableStatic,
    GameLayout,
    GameScreen,
    PreparationButton,
    RightRow1, Tag,
)

# 卡包 kind -> 本地化名(含妖法包)
PACK_KIND_ZH = {
    "buffoon": "小丑包",
    "arcana": "秘法包",
    "celestial": "星球包",
    "spectral": "妖法包",
}

# 小丑栏单格类型标记(消耗牌前缀,便于区分)
_ITEM_MARK = {
    "joker": "",
    "tarot": "◆",
    "planet": "☄",
    "spectral": "妖",
}


class ShopItem(FocusableStatic):
    """小丑栏的一件在售商品(小丑或消耗牌)。"""

    def __init__(self, index: int, item: dict, **kwargs) -> None:
        kind = item.get("kind", "joker")
        mark = _ITEM_MARK.get(kind, "")
        label = f"${item['cost']} {mark}{item['label']}" if mark else f"${item['cost']} {item['label']}"
        super().__init__(label, **kwargs)
        self.index = index
        self.kind = kind
        self.tooltip = item.get("desc") or "小丑牌"

    def on_click(self, event) -> None:
        self.screen.run_worker(self.screen.buy_joker(self.index))
        event.stop()


class PackItem(FocusableStatic):

    def __init__(self, pack_index: int, pack: dict, **kwargs) -> None:
        name = PACK_KIND_ZH.get(pack.get("kind"), pack.get("name") or "补充包")
        super().__init__(f"${pack['cost']} [{name}]", **kwargs)
        self.pack_index = pack_index
        self.pack = pack
        self.tooltip = f"打开{name},选择{name}内容"

    def on_click(self, event) -> None:
        self.screen.run_worker(self.screen.buy_pack(self.pack_index))
        event.stop()


class VoucherItem(FocusableStatic):

    def __init__(self, voucher: dict, **kwargs) -> None:
        super().__init__(f"${voucher['cost']} [{voucher['name']}]", **kwargs)
        self.voucher = voucher
        self.tooltip = f"购买优惠券 {voucher['name']}"

    def on_click(self, event) -> None:
        self.screen.run_worker(self.screen.buy_voucher())
        event.stop()


class GoodsRow(Horizontal):

    def compose(self) -> ComposeResult:
        # 商品在 on_mount 时由 ShopGoods._rebuild 填充
        yield from ()


class PackRow(Horizontal):

    def compose(self) -> ComposeResult:
        # 卡包在 on_mount 时由 ShopGoods._rebuild 填充
        yield from ()


class VoucherRow(Horizontal):

    def compose(self) -> ComposeResult:
        # 优惠券在 on_mount 时由 ShopGoods._rebuild 填充
        yield from ()


class ShopGoods(VerticalGroup):

    def compose(self) -> ComposeResult:
        yield GoodsRow()
        yield PackRow()
        yield VoucherRow()

    def _rebuild(self):
        """购买/重掷后重建三行商品(用单调 id 避免重建冲突)。"""
        self._uid = getattr(self, "_uid", 0)
        goods = self.query_one(GoodsRow)
        goods.remove_children()
        for index, item in enumerate(self.screen.game_state.shop_jokers):
            self._uid += 1
            goods.mount(ShopItem(index, item, id=f"shop_item_{self._uid}"))
        packs = self.query_one(PackRow)
        packs.remove_children()
        for index, pack in enumerate(self.screen.game_state.shop_packs):
            self._uid += 1
            packs.mount(PackItem(index, pack, id=f"pack_{self._uid}"))
        vouchers = self.query_one(VoucherRow)
        vouchers.remove_children()
        voucher = self.screen.game_state.shop_voucher
        if voucher:
            self._uid += 1
            vouchers.mount(VoucherItem(voucher, id=f"voucher_{self._uid}"))


class ShopPanel(Horizontal):

    def compose(self) -> ComposeResult:
        yield VerticalGroup(
            PreparationButton("下一个回合", id="next_round"),
            PreparationButton("重掷", id="reroll"),
            id="shop_actions"
        )
        yield ShopGoods()


class RightRow2Sub(Horizontal):

    def compose(self) -> ComposeResult:
        yield ShopPanel()
        yield Tag()


class ShopScreen(GameScreen):
    """商店场景:买小丑/消耗牌、买卡包、买优惠券、重掷、下一回合。"""

    CSS_PATH = ["../css/common.tcss", "../css/shop.tcss"]

    BINDINGS = [*GameScreen.BINDINGS]

    def __init__(self, game_state=None) -> None:
        super().__init__()
        self.game_state = game_state

    def compose(self) -> ComposeResult:
        yield Header()
        yield GameLayout(RightRow1(), RightRow2Sub())
        yield Footer()

    async def on_mount(self) -> None:
        if not getattr(self.game_state, "shop_jokers", None):
            self.game_state.generate_shop()
        await self.refresh_run_ui()
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

    async def buy_joker(self, index: int) -> None:
        if self.game_state.buy_joker(index):
            self.query_one(ShopGoods)._rebuild()
            await self.refresh_run_ui()

    async def buy_pack(self, index: int) -> None:
        pack = self.game_state.buy_pack(index)
        if not pack:
            return
        await self.refresh_run_ui()
        from .boosters import BoostersScreen
        self.app.push_screen(BoostersScreen(self.game_state, pack=pack))

    async def buy_voucher(self) -> None:
        if self.game_state.buy_voucher():
            self.query_one(ShopGoods)._rebuild()
            await self.refresh_run_ui()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
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
                await self.refresh_run_ui()