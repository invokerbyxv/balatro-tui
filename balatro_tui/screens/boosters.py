from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalGroup
from textual.widgets import Button, Header, Footer, Static

from ..game_engine import card_label, carrier_label
from .common import (
    FocusableStatic,
    GameLayout,
    GameScreen,
    PreparationButton,
    RightRow1,
)

PACK_KIND_ZH = {
    "Buffoon": "小丑包",
    "Arcana": "秘法包",
    "Celestial": "星球包",
    "Spectral": "妖法包",
    "Standard": "标准包",
}


def _card_info(card) -> tuple[str, str]:
    """包内一张卡 → (显示文本, tooltip)。"""
    if getattr(card, "is_joker", False) or not hasattr(card, "enhancement"):
        # 小丑/消耗品(JokerCard)
        info = carrier_label(card)
        return info["label"], info["desc"]
    text, _color = card_label(card)
    if card.enhancement:
        from ..utils.loc_text import loc_name
        text += f"({loc_name('Enhanced', card.enhancement)})"
    return text, "扑克牌(选走会加入牌组)"


class PackChoice(FocusableStatic):

    def __init__(self, index: int, card, **kwargs) -> None:
        label, tip = _card_info(card)
        super().__init__(label, **kwargs)
        self.index = index
        self.card = card
        self.tooltip = tip

    def on_click(self, event) -> None:
        self.screen.toggle(self.index)
        event.stop()


class PackCards(Horizontal):
    pass


class PackBar(Horizontal):

    def compose(self) -> ComposeResult:
        yield PreparationButton("选择", id="pack_select")
        yield PreparationButton("跳过", id="pack_skip")


class BoostersArea(VerticalGroup):

    def __init__(self, title, choose, **kwargs):
        super().__init__(**kwargs)
        self.title = title
        self.choose = choose

    def compose(self) -> ComposeResult:
        yield Static(f"{self.title} · 可选 {self.choose} 张", id="pack_name")
        yield PackCards()
        yield PackBar()


class RightRow2Sub(Horizontal):

    def __init__(self, title, choose, **kwargs):
        super().__init__(**kwargs)
        self.title = title
        self.choose = choose

    def compose(self) -> ComposeResult:
        yield BoostersArea(self.title, self.choose)


class BoostersScreen(GameScreen):
    """补充包场景:支持 choose>1(多次取走直至选满)与跳过。"""

    CSS_PATH = ["../css/common.tcss", "../css/boosters.tcss"]

    BINDINGS = [
        ("left", "focus_prev_card", None),
        ("right", "focus_next_card", None),
        *GameScreen.BINDINGS,
    ]

    def __init__(self, run_state=None, pack: dict | None = None) -> None:
        super().__init__(run_state)
        self.pack = pack or {}
        self.selected: set[int] = set()   # 待取走的下标
        self._uid = 0

    # ------------------------------------------------------------- 展示

    @property
    def remaining_choices(self) -> int:
        choose = self.pack.get("choose", 1)
        return choose - len(self.pack.get("taken", [])) - len(self.selected)

    def compose(self) -> ComposeResult:
        kind = self.pack.get("kind", "Buffoon")
        title = PACK_KIND_ZH.get(kind, self.pack.get("name") or "补充包")
        yield Header()
        yield GameLayout(RightRow1(), RightRow2Sub(title, self.pack.get("choose", 1)))
        yield Footer()

    async def on_mount(self):
        await self.refresh_run_ui()
        self._rebuild_cards()
        self._sync_selection()

    def _rebuild_cards(self) -> None:
        row = self.query_one(PackCards)
        row.remove_children()
        for i, card in enumerate(self.pack.get("cards", [])):
            self._uid += 1
            row.mount(PackChoice(i, card, id=f"pack_card_{self._uid}"))
        self._sync_selection()

    def _widgets(self) -> list[PackChoice]:
        return list(self.query(PackChoice))

    def _sync_selection(self) -> None:
        for w in self._widgets():
            w.set_class(w.index in self.selected, "selected")

    # ------------------------------------------------------------- 交互

    def toggle(self, index: int) -> None:
        if index in self.selected:
            self.selected.discard(index)
        elif self.remaining_choices > 0:
            self.selected.add(index)
        self._sync_selection()

    def action_focus_prev_card(self):
        widgets = self._widgets()
        if widgets:
            widgets[0].focus()

    def action_focus_next_card(self):
        widgets = self._widgets()
        if widgets:
            widgets[-1].focus()

    def _take(self) -> None:
        if not self.selected:
            return
        result = self.run_state.take_from_pack(self.pack, sorted(self.selected))
        self.selected = set()
        if not result.get("ok"):
            return
        if self.pack.get("closed") or not self.pack.get("cards"):
            self.app.pop_screen()
            return
        self._rebuild_cards()
        self.run_worker(self.refresh_run_ui())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "pack_select":
            self._take()
        elif event.button.id == "pack_skip":
            self.run_state.skip_pack(self.pack)
            self.app.pop_screen()
