from textual.app import ComposeResult
from textual.containers import Horizontal, HorizontalScroll, VerticalGroup
from textual.widgets import Button, Header, Footer, Static

from ..game_engine import card_label, carrier_label
from .common import (
    FocusableStatic,
    FocusNavigationScroll,
    GameLayout,
    GameScreen,
    HorizontalMouseScroll,
    PreparationButton,
    RightRow1,
    ScrollInteraction,
    Tag,
)

PACK_KIND_ZH = {
    "Buffoon": "小丑包",
    "Arcana": "秘法包",
    "Celestial": "星球包",
    "Spectral": "妖法包",
    "Standard": "标准包",
}

KIND_MARK = {"consumable": "◆", "playing_card": "🂠", "booster": "包", "voucher": "券"}


def _item_label(item) -> tuple[str, str]:
    """ShopItem → (显示文本, tooltip)。"""
    if item.kind in ("joker", "consumable"):
        # card 仅在标签塞入免费小丑时才有;常规进货的卡对象在 data 里
        card = item.card if item.card is not None else item.data
        info = carrier_label(card)
        return f"${item.cost} {info['label']}", info["desc"]
    if item.kind == "playing_card":
        text, color = card_label(item.card)
        return f"${item.cost} {text}", "一张打牌强化过的扑克牌"
    if item.kind == "booster":
        name = PACK_KIND_ZH.get(item.name, item.name)
        cfg = item.data.get("config") or {}
        extra, choose = cfg.get("extra"), cfg.get("choose")
        return f"${item.cost} [{name}]", f"打开{name}:含 {extra} 张,可选 {choose} 张"
    if item.kind == "voucher":
        from ..utils.loc_text import loc_name
        from ..utils.collection_data import voucher_vars
        from ..utils.lua_data import get_config, load_definitions
        from ..utils.collection_data import _desc
        name = loc_name("Voucher", item.key) or item.name
        c = (load_definitions().get("Voucher") or {}).get(item.key) or {}
        desc = _desc("Voucher", item.key, voucher_vars(get_config(c)))
        return f"${item.cost} [券:{name}]", desc
    return f"${item.cost} ?", ""


class ShopGoodsItem(FocusableStatic):
    """一件在售商品(小丑/消耗牌/扑克牌/卡包/优惠券)。"""

    def __init__(self, index: int, item, **kwargs) -> None:
        label, tip = _item_label(item)
        super().__init__(label, **kwargs)
        self.index = index
        self.tooltip = tip or "商品"

    def on_click(self, event) -> None:
        self.screen.run_worker(self.screen.buy(self.index))
        event.stop()


class GoodsRow(ScrollInteraction, FocusNavigationScroll, HorizontalMouseScroll, HorizontalScroll):
    """卡牌位(小丑/消耗牌/扑克牌);列宽不足时可横向滚动。"""


class PackRow(Horizontal):
    """卡包位。"""


class VoucherRow(Horizontal):
    """优惠券位。"""


class ShopGoods(VerticalGroup):

    def compose(self) -> ComposeResult:
        yield GoodsRow()
        yield PackRow()
        yield VoucherRow()

    def _rebuild(self):
        """购买/重掷后重建三行商品(用单调 id 避免重建冲突)。"""
        self._uid = getattr(self, "_uid", 0)
        items = self.screen.run_state.shop_items()
        goods = self.query_one(GoodsRow)
        goods.remove_children()
        for item in items:
            if item.kind == "booster":
                continue
            self._uid += 1
            goods.mount(ShopGoodsItem(item.index, item, id=f"shop_item_{self._uid}"))
        packs = self.query_one(PackRow)
        packs.remove_children()
        for item in items:
            if item.kind != "booster":
                continue
            self._uid += 1
            packs.mount(ShopGoodsItem(item.index, item, id=f"pack_{self._uid}"))
        vouchers = self.query_one(VoucherRow)
        vouchers.remove_children()
        for item in items:
            if item.kind != "voucher":
                continue
            self._uid += 1
            vouchers.mount(ShopGoodsItem(item.index, item, id=f"voucher_{self._uid}"))


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
    """商店场景:买小丑/消耗牌/卡包/优惠券、重掷、卖卡、下一回合。"""

    CSS_PATH = ["../css/common.tcss", "../css/shop.tcss"]

    BINDINGS = [*GameScreen.BINDINGS]

    # 三行商品需要的高度比其它场景多,提前两行进入紧凑模式
    COMPACT_HEIGHT = 17

    def __init__(self, run_state=None) -> None:
        super().__init__(run_state)

    def compose(self) -> ComposeResult:
        yield Header()
        yield GameLayout(RightRow1(), RightRow2Sub())
        yield Footer()

    async def on_mount(self) -> None:
        await self.refresh_run_ui()
        self.query_one(ShopGoods)._rebuild()
        self._sync_reroll_label()
        try:
            self.query_one("#next_round", PreparationButton).focus()
        except Exception:
            pass

    def _sync_reroll_label(self) -> None:
        try:
            self.query_one("#reroll", PreparationButton).label = f"重掷 ${self.run_state.reroll_cost}"
        except Exception:
            pass

    def _notice(self, text: str) -> None:
        self.query_one("#next_round", PreparationButton).tooltip = text

    async def buy(self, index: int) -> None:
        result = self.run_state.buy(index)
        if not result.get("ok"):
            return
        pack = result.get("pack")
        if pack:
            from .boosters import BoostersScreen
            self.app.push_screen(BoostersScreen(self.run_state, pack=pack))
        self.query_one(ShopGoods)._rebuild()
        await self.refresh_run_ui()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "next_round":
            self.run_state.advance_from_shop()
            from .preparation import PreparationScreen
            self.swap_screen(PreparationScreen(self.run_state))
        elif bid == "reroll":
            result = self.run_state.reroll()
            if result.get("ok"):
                self.query_one(ShopGoods)._rebuild()
                self._sync_reroll_label()
                await self.refresh_run_ui()

    def use_consumable_flow(self, index: int) -> None:
        """商店里使用不需要目标的消耗品(星球升级等)。"""
        run = self.run_state
        rng = run.consumable_target_range(run.consumeables[index])
        if rng is not None:
            self._notice("该消耗品需要手牌目标,请在战斗中使用")
            return
        from ..game_engine import carrier_label
        name = carrier_label(run.consumeables[index])["name"]
        result = run.use_consumable(index, [])
        if result.get("ok"):
            self._notice(f"使用了 {name}")
            self.run_worker(self.refresh_run_ui())
        else:
            self._notice(f"无法使用 {name}: {result.get('error', '')}")
