from textual.app import ComposeResult
from textual.containers import Center, Horizontal, HorizontalScroll, Vertical, VerticalGroup
from textual.widgets import Button, Header, Footer, Static

from ..game_engine import card_label, hand_name, score_lines
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


class HandCard(FocusableStatic):
    """一张可选中(高亮)的手牌。"""

    can_focus = True

    def __init__(self, card, **kwargs) -> None:
        text, color = card_label(card)
        super().__init__(text, **kwargs)
        self.card = card
        self.add_class(color)
        if getattr(card, "debuffed", False):
            self.add_class("debuffed")

    def on_click(self, event) -> None:
        self.screen.toggle_card(self)
        event.stop()


class HandHorizontalScroll(
    ScrollInteraction, FocusNavigationScroll, HorizontalMouseScroll, HorizontalScroll
):

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.can_focus = True
        self.can_focus_children = True


class ActionBar(Horizontal):

    def compose(self) -> ComposeResult:
        yield Center(PreparationButton("出牌", id="play_hand"))
        yield VerticalGroup(
            Center(Static("理牌")),
            Horizontal(
                PreparationButton("点数", id="sort_rank"),
                PreparationButton("花色", id="sort_suit"),
                id="sort_buttons"
            ),
            id="sort_group"
        )
        yield Center(PreparationButton("弃牌", id="discard_hand"))
        yield Center(PreparationButton("确认使用", id="confirm_use"))


class BattleArea(Vertical):

    def compose(self) -> ComposeResult:
        yield Static("选择手牌后按 出牌 / 弃牌", id="played_area", markup=False)
        yield HandHorizontalScroll(id="hand_scroll")
        yield ActionBar()


class RightRow2Sub(Horizontal):

    def compose(self) -> ComposeResult:
        yield BattleArea()
        yield Tag()


class BattleScreen(GameScreen):
    """对战场景:选牌、出牌、弃牌、消耗品、逐小丑计分转写。"""

    CSS_PATH = ["../css/common.tcss", "../css/battle.tcss"]

    BINDINGS = [
        ("space", "toggle_card", "选牌"),
        *GameScreen.BINDINGS,
    ]

    def __init__(self, run_state=None) -> None:
        super().__init__(run_state)
        self.selected: set[int] = set()      # 选中卡牌的 id(card)
        self._hand_widgets: list[HandCard] = []
        self._uid = 0
        self._sort_mode = "rank"
        self.target_mode: tuple[int, tuple[int, int]] | None = None  # (消耗品idx,(min,max))

    def compose(self) -> ComposeResult:
        yield Header()
        yield GameLayout(RightRow1(), RightRow2Sub())
        yield Footer()

    async def on_mount(self) -> None:
        self.run_state.sort_hand(self._sort_mode)
        self._render_hand()
        await self.refresh_run_ui()
        self.query_one("#confirm_use", PreparationButton).display = False
        try:
            self.query_one("#play_hand", PreparationButton).focus()
        except Exception:
            pass

    # ------------------------------------------------------------- 渲染

    def _render_hand(self) -> None:
        """根据 run_state.hand 重建手牌列表(选中状态跟随卡牌对象)。"""
        scroll = self.query_one("#hand_scroll")
        scroll.remove_children()
        self._hand_widgets = []
        for card in self.run_state.hand:
            self._uid += 1
            widget = HandCard(card, id=f"hand_{self._uid}")
            self._hand_widgets.append(widget)
        scroll.mount(*self._hand_widgets)
        self._refresh_select_classes()
        self._update_preview()

    def _refresh_select_classes(self) -> None:
        for widget in self._hand_widgets:
            widget.set_class(id(widget.card) in self.selected, "selected")

    def _selected_cards(self) -> list:
        return [w.card for w in self._hand_widgets if id(w.card) in self.selected]

    def _update_preview(self) -> None:
        cards = self._selected_cards()
        area = self.query_one("#played_area", Static)
        if self.target_mode is not None:
            _, (mn, mx) = self.target_mode
            area.update(f"选择目标手牌({mn}~{mx}张),已选 {len(cards)} 张,点【确认使用】生效")
            return
        if not cards:
            area.update("选择手牌后 出牌 / 弃牌")
            return
        key, scoring = self.run_state.preview_hand(cards)
        area.update(f"当前组合: {hand_name(key)} ({len(scoring)} 张计分)")

    # ------------------------------------------------------------- 交互

    def toggle_card(self, widget: HandCard | None = None) -> None:
        widget = widget or self._focused_card()
        if widget is None:
            return
        cid = id(widget.card)
        if cid in self.selected:
            self.selected.remove(cid)
        else:
            self.selected.add(cid)
        self._refresh_select_classes()
        self._update_preview()

    def _focused_card(self) -> HandCard | None:
        if self.focused and isinstance(self.focused, HandCard):
            return self.focused
        return None

    def action_toggle_card(self) -> None:
        self.toggle_card(self._focused_card())

    async def _play(self) -> None:
        cards = self._selected_cards()
        result = self.run_state.play_cards(cards)
        if not result.get("ok"):
            return
        score = result["score"]
        self.run_state.record_score(score)
        lines = score_lines(score)
        if result.get("debuffed"):
            lines.append("⚠ 该牌型被 BOSS 封禁,得分无效")
        if result.get("destroyed"):
            names = "、".join(card_label(c)[0] for c in result["destroyed"])
            lines.append(f"销毁: {names}")
        if self.run_state.message:
            lines.append(f"· {self.run_state.message}")
        area = self.query_one("#played_area", Static)
        self.run_state.sort_hand(self._sort_mode)
        self._render_hand()
        # _render_hand 会触发 _update_preview 覆盖该区域,计分行必须在重渲染之后写入
        area.update("\n".join(lines))
        await self.refresh_run_ui()
        self._resolve()

    async def _discard(self) -> None:
        cards = self._selected_cards()
        result = self.run_state.discard_cards(cards)
        area = self.query_one("#played_area", Static)
        if not result.get("ok"):
            area.update(f"无法弃牌: {result.get('error', '')}")
            return
        text = f"已弃牌 {len(result['dropped'])} 张"
        if self.run_state.message:
            text += f"\n· {self.run_state.message}"
        self.run_state.sort_hand(self._sort_mode)
        self._render_hand()
        area.update(text)
        await self.refresh_run_ui()

    def _sort(self, mode) -> None:
        self._sort_mode = mode
        self.run_state.sort_hand(mode)
        self._render_hand()

    def _resolve(self) -> None:
        """胜利进结算;失败(出牌用尽且未达标)也进结算,由结算判断。"""
        if self.run_state.phase in ("round_won", "round_lost"):
            from .settlement import SettlementScreen
            self.swap_screen(SettlementScreen(self.run_state))

    # ------------------------------------------------------- 消耗品使用流

    def use_consumable_flow(self, index: int) -> None:
        run = self.run_state
        rng = run.consumable_target_range(run.consumeables[index])
        if rng is None:
            self._use_consumable(index, [])
            return
        self.target_mode = (index, rng)
        self.query_one("#confirm_use", PreparationButton).display = True
        self._update_preview()

    async def _use_consumable(self, index: int, targets: list) -> None:
        run = self.run_state
        from ..game_engine import carrier_label
        name = carrier_label(run.consumeables[index])["name"]
        result = run.use_consumable(index, targets)
        area = self.query_one("#played_area", Static)
        self.run_state.sort_hand(self._sort_mode)
        self._render_hand()
        message = f"使用了 {name}" if result.get("ok") else f"无法使用 {name}: {result.get('error', '')}"
        area.update(message)
        self.target_mode = None
        self.query_one("#confirm_use", PreparationButton).display = False
        await self.refresh_run_ui()

    def _confirm_use(self) -> None:
        if self.target_mode is None:
            return
        index, (mn, _mx) = self.target_mode
        cards = self._selected_cards()
        if len(cards) < mn:
            return
        self.run_worker(self._use_consumable(index, cards))

    # ------------------------------------------------------------- 事件

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "play_hand":
            await self._play()
        elif bid == "discard_hand":
            await self._discard()
        elif bid == "sort_rank":
            self._sort("rank")
        elif bid == "sort_suit":
            self._sort("suit")
        elif bid == "confirm_use":
            self._confirm_use()
