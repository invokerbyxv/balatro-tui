from textual.app import ComposeResult
from textual.containers import Center, Horizontal, HorizontalScroll, Vertical, VerticalGroup
from textual.widgets import Button, Header, Footer, Static

from .common import (
    FocusableStatic,
    FocusNavigationScroll,
    GameLayout,
    GameScreen,
    HorizontalMouseScroll,
    PreparationButton,
    RightRow1,
    ScrollInteraction, Tag,
)

from ..game_engine.hand import HandEvaluator

HAND_ZH = {
    "High Card": "高牌", "Pair": "对子", "Two Pair": "两对",
    "Three of a Kind": "三条", "Straight": "顺子", "Flush": "同花",
    "Full House": "葫芦", "Four of a Kind": "四条",
    "Straight Flush": "同花顺", "Five of a Kind": "五条",
    "Flush House": "同花葫芦", "Flush Five": "同花五条",
}


class HandCard(FocusableStatic):
    """一张可选中(高亮)的手牌。"""

    can_focus = True

    def __init__(self, card, **kwargs) -> None:
        super().__init__(card.display(), **kwargs)
        self.card = card

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


class BattleArea(Vertical):

    def compose(self) -> ComposeResult:
        yield Static("选择手牌后按 [1] 出牌 / [2] 弃牌", id="played_area")
        yield HandHorizontalScroll(id="hand_scroll")
        yield ActionBar()


class RightRow2Sub(Horizontal):

    def compose(self) -> ComposeResult:
        yield BattleArea()
        yield Tag()


class BattleScreen(GameScreen):
    """对战场景:选牌、出牌、弃牌、实时计分。"""

    CSS_PATH = ["../css/common.tcss", "../css/battle.tcss"]

    BINDINGS = [
        ("space", "toggle_card", "选牌"),
        *GameScreen.BINDINGS,
    ]

    def __init__(self, game_state=None) -> None:
        super().__init__()
        self.game_state = game_state
        self.selected: set = set()
        self._hand_widgets = {}
        self._uid = 0

    def compose(self) -> ComposeResult:
        yield Header()
        yield GameLayout(RightRow1(), RightRow2Sub())
        yield Footer()

    def on_mount(self) -> None:
        self._render_hand()
        self.refresh_run_ui()
        try:
            self.query_one("#play_hand", PreparationButton).focus()
        except Exception:
            pass

    # ------------------------------------------------------------- 渲染

    def _render_hand(self) -> None:
        """根据 game_state.hand 重建手牌列表,保留仍存在的选中。"""
        scroll = self.query_one("#hand_scroll")
        # 记录仍被选中的牌
        still = set()
        for cid, card in self._hand_widgets.items():
            if card in self.game_state.hand and cid in self.selected:
                still.add(card)
        self.selected = still
        scroll.remove_children()
        self._hand_widgets = {}
        for card in self.game_state.hand:
            self._uid += 1
            widget = HandCard(card, id=f"hand_{self._uid}")
            self._hand_widgets[id(widget)] = widget
        scroll.mount(*self._hand_widgets.values())
        self._refresh_select_classes()
        self._update_preview()

    def _refresh_select_classes(self) -> None:
        for cid, widget in self._hand_widgets.items():
            if cid in self.selected:
                widget.add_class("selected")
            else:
                widget.remove_class("selected")

    def _update_preview(self) -> None:
        cards = [w.card for cid, w in self._hand_widgets.items() if cid in self.selected]
        area = self.query_one("#played_area", Static)
        if not cards:
            area.update("选择手牌后 出牌 / 弃牌")
            return
        key, scoring = HandEvaluator(cards).evaluate()
        name = HAND_ZH.get(key, key)
        area.update(f"当前组合: {name} ({len(scoring)} 张计分)")

    # ------------------------------------------------------------- 交互

    def toggle_card(self, widget: HandCard | None = None) -> None:
        widget = widget or self._focused_card()
        if widget is None:
            return
        cid = id(widget)
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

    def _selected_cards(self) -> list:
        return [w.card for cid, w in self._hand_widgets.items() if cid in self.selected]

    def _play(self) -> None:
        cards = self._selected_cards()
        calc = self.game_state.play_cards(cards)
        if calc:
            self.query_one("#played_area", Static).update(
                f"打出: {HAND_ZH.get(calc['hand_key'], calc['hand_key'])} "
                f"{calc['chips']}×{calc['mult']} = {calc['score']}"
            )
        self._render_hand()
        self.refresh_run_ui()
        self._resolve()

    def _discard(self) -> None:
        cards = self._selected_cards()
        ok = self.game_state.discard_cards(cards)
        if ok:
            self.query_one("#played_area", Static).update("已弃牌")
        self._render_hand()
        self.refresh_run_ui()

    def _sort(self, key) -> None:
        self.game_state.hand.sort(key=key)
        self._render_hand()

    def _sort_rank(self) -> None:
        self._sort(lambda c: (-c.nominal, c.suit_order()))

    def _sort_suit(self) -> None:
        self._sort(lambda c: (c.suit_order(), -c.nominal))

    def _resolve(self) -> None:
        """胜利进结算;失败(出牌用尽且未达标)也进结算,由结算判断。"""
        if self.game_state.round_lost or self.game_state.won_blind:
            from .settlement import SettlementScreen
            self.app.push_screen(SettlementScreen(self.game_state))

    # ------------------------------------------------------------- 事件

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "play_hand":
            self._play()
        elif bid == "discard_hand":
            self._discard()
        elif bid == "sort_rank":
            self._sort_rank()
        elif bid == "sort_suit":
            self._sort_suit()