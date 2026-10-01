"""Shared widgets for the in-run scenes (blind choice, battle, shop, settlement, boosters).

对局界面全部经由 RunState 适配层读取 balatro_cli.engine。
"""

from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Grid, Horizontal, HorizontalScroll, VerticalGroup, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import Screen, ModalScreen
from textual.widget import Widget
from textual.widgets import Button, DataTable, Static

from ..game_engine import carrier_label
from ..utils.helpers import format_number


class FocusableStatic(Static):
    can_focus = True


class PreparationButton(Button):
    can_focus = True


class FocusNavigationScroll:
    """Use horizontal keys for focus navigation while inside a scroll area."""

    def action_scroll_left(self) -> None:
        self._focus_scroll_child(-1)

    def action_scroll_right(self) -> None:
        self._focus_scroll_child(1)

    def _focus_scroll_child(self, step: int) -> None:
        children = list(self.query(FocusableStatic))
        current = self.screen.focused
        if not children or current not in children:
            return

        child_index = children.index(current) + step
        if 0 <= child_index < len(children):
            target = children[child_index]
            target.focus()
            target.scroll_visible()
        elif step < 0:
            self.screen.action_focus_left()
        else:
            self.screen.action_focus_right()


class HorizontalMouseScroll:
    """Map the regular mouse wheel to horizontal scrolling."""

    def _on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        if self.allow_horizontal_scroll:
            if self._scroll_right_for_pointer(animate=False):
                event.stop()

    def _on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        if self.allow_horizontal_scroll:
            if self._scroll_left_for_pointer(animate=False):
                event.stop()


class ScrollInteraction:
    """Make the scroll area itself the target of mouse clicks."""

    def on_click(self, event: events.Click) -> None:
        self.focus()
        event.stop()


def run_of(screen: Screen):
    return getattr(screen, "run_state", None)


class LeftContent(VerticalGroup):

    def compose(self) -> ComposeResult:
        run = run_of(self.screen)
        blind = run.the_blind if run else None
        yield Horizontal(
            Static("小盲注", id="level"),
            Static("目标: 300", id="require"),
            id="row_1"
        )
        yield Horizontal(
            Static("奖励: $3", id="rewards"),
            Static("得分: 0", id="score"),
            id="row_2"
        )
        yield Horizontal(
            Static("0", id="chips"),
            Static("0", id="mult"),
            id="calculation"
        )
        yield Static("", id="blind_effect")
        tb_1 = DataTable(id="left_content_tb_1")
        tb_1.add_column("出牌", key="plays")
        tb_1.add_column("弃牌", key="discards")
        tb_1.add_column("底注", key="ante")
        tb_1.add_column("回合", key="round")
        tb_1.add_column("钱", key="money")
        st = run
        tb_1.add_row(
            st.hands_left if st else 0,
            st.discards_left if st else 0,
            f"1/{st.ante if st else 8}",
            st.round_num if st else 1,
            f"${st.dollars if st else 4}",
        )
        tb_1.cursor_type = "none"
        yield tb_1

        yield Horizontal(
            PreparationButton("游戏信息", id="info"),
            Static("[0/52]", id="card_deck"),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "info":
            from .game_info import GameInfoScreen
            self.app.push_screen(GameInfoScreen(run_of(self.screen)))
            event.stop()

    async def refresh_run(self, state=None) -> None:
        run = state or run_of(self.screen)
        if run is None:
            return
        blind = run.the_blind
        if blind is not None:
            from ..game_engine import blind_display
            info = blind_display(blind.key, blind.chips, blind.dollars)
            self.query_one("#level", Static).update(info["name"])
            self.query_one("#require", Static).update(f"目标: {format_number(info['chips'])}")
            self.query_one("#rewards", Static).update(f"奖励: ${info['dollars']}")
            effect = info.get("desc") or ""
            self.query_one("#blind_effect", Static).update(
                f"效果: {effect}" if blind.is_boss and effect else ""
            )
        else:
            self.query_one("#level", Static).update(f"底注 {run.ante}")
            self.query_one("#require", Static).update("目标: --")
            self.query_one("#rewards", Static).update("奖励: $0")
            self.query_one("#blind_effect", Static).update("")
        self.query_one("#score", Static).update(f"得分: {format_number(run.chips)}")
        # 上一手的实时结算(适配器缓存 ScoreResult 汇总)
        calc = getattr(run, "last_score_display", None)
        if calc:
            self.query_one("#chips", Static).update(f"{format_number(calc[0])}")
            self.query_one("#mult", Static).update(f"× {format_number(calc[1])}")
        else:
            self.query_one("#chips", Static).update("0")
            self.query_one("#mult", Static).update("0")
        tbl = self.query_one("#left_content_tb_1", DataTable)
        if tbl.row_count:
            tbl.update_cell_at((0, 0), run.hands_left)
            tbl.update_cell_at((0, 1), run.discards_left)
            tbl.update_cell_at((0, 2), f"{run.ante}/{8}")
            tbl.update_cell_at((0, 3), run.round_num)
            tbl.update_cell_at((0, 4), f"${run.dollars}")
        self.query_one("#card_deck", Static).update(
            f"[{len(run.deck)}]/[{run.state.starting_deck_size}]"
        )


class LeftContainer(Container):

    def compose(self) -> ComposeResult:
        yield LeftContent()


class JokerHorizontalScroll(
    ScrollInteraction, FocusNavigationScroll, HorizontalMouseScroll, HorizontalScroll
):
    """持有小丑条:显示中文名,点击弹出出售确认。"""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._n = 0

    def compose(self) -> ComposeResult:
        self.can_focus = True
        self.can_focus_children = True
        yield from self._children()

    def _children(self):
        run = run_of(self.screen)
        jokers = run.jokers if run else []
        for i, joker in enumerate(jokers):
            self._n += 1
            info = carrier_label(joker)
            item = FocusableStatic(info["label"], id=f"joker_{self._n}")
            item.tooltip = f"{info['desc']}\n点击出售(得 ${run.state.sell_value(joker)})"
            item.index = i
            yield item

    async def _rebuild(self) -> None:
        if self.children:
            await self.remove_children()
        for w in self._children():
            await self.mount(w)

    async def refresh_run(self, state=None) -> None:
        await self._rebuild()

    def on_click(self, event: events.Click) -> None:
        widget = event.widget
        if isinstance(widget, FocusableStatic) and widget.id and widget.id.startswith("joker_"):
            screen = self.screen
            if hasattr(screen, "open_sell"):
                screen.open_sell("joker", widget.index)
                event.stop()


class ConsumableHorizontalScroll(
    ScrollInteraction, FocusNavigationScroll, HorizontalMouseScroll, HorizontalScroll
):
    """消耗品条:显示真名,点击进入使用流程(由所在屏实现 use_consumable_flow)。"""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._n = 0

    def compose(self) -> ComposeResult:
        self.can_focus = True
        self.can_focus_children = True
        yield from self._children()

    def _children(self):
        run = run_of(self.screen)
        items = run.consumeables if run else []
        for i, card in enumerate(items):
            self._n += 1
            info = carrier_label(card)
            fs = FocusableStatic(info["label"], id=f"consumable_{self._n}")
            fs.tooltip = info["desc"]
            fs.index = i
            yield fs

    async def _rebuild(self) -> None:
        if self.children:
            await self.remove_children()
        for w in self._children():
            await self.mount(w)

    async def refresh_run(self, state=None) -> None:
        await self._rebuild()

    def on_click(self, event: events.Click) -> None:
        widget = event.widget
        if isinstance(widget, FocusableStatic) and widget.id and widget.id.startswith("consumable_"):
            screen = self.screen
            if hasattr(screen, "use_consumable_flow"):
                screen.use_consumable_flow(widget.index)
                event.stop()


class RightRow1Sub(Horizontal):

    def compose(self) -> ComposeResult:
        yield JokerHorizontalScroll()
        yield Static("[0/0]", id="joker_count")
        yield ConsumableHorizontalScroll()
        yield Static("[0/0]", id="consumable_count")


class RightRow1(Container):

    def compose(self) -> ComposeResult:
        yield RightRow1Sub()


class Tag(ScrollInteraction, FocusNavigationScroll, VerticalScroll):
    """待用标签条:显示真实标签名,悬停看效果。触发由引擎在对应时机自动完成。"""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._n = 0

    def compose(self) -> ComposeResult:
        self.can_focus = True
        self.can_focus_children = True
        yield from self._children()

    def _children(self):
        run = run_of(self.screen)
        tags = run.tags if run else []
        if not tags:
            yield FocusableStatic("[无标签]", id="tag_empty")
            return
        from ..utils.collection_data import tag_item
        for key in tags:
            self._n += 1
            item = tag_item(key)
            fs = FocusableStatic(item["label"], id=f"tag_{self._n}")
            fs.tooltip = item["desc"]
            yield fs

    async def _rebuild(self) -> None:
        if self.children:
            await self.remove_children()
        for w in self._children():
            await self.mount(w)

    async def refresh_run(self, state=None) -> None:
        await self._rebuild()


class RightContainer(Container):
    pass


class GameLayout(Horizontal):
    """Left info panel plus the scene-specific right side."""

    def __init__(self, *right_children: Widget) -> None:
        super().__init__(LeftContainer(), RightContainer(*right_children))


class SellDialog(ModalScreen):
    """出售确认:展示名称与可得金额。"""

    CSS = """
    SellDialog {
        align: center middle;
    }
    #sell_box {
        width: 60;
        height: auto;
        border: round $primary;
        background: $surface;
        padding: 1 2;
    }
    #sell_buttons { height: auto; align-horizontal: center; }
    """

    BINDINGS = [("escape", "cancel", "取消")]

    def __init__(self, kind: str, index: int, name: str, price: int, **kwargs) -> None:
        super().__init__(**kwargs)
        self.kind = kind
        self.index = index
        # Screen.name 在 Textual 8 是只读属性,不能占用
        self.item_name = name
        self.price = price

    def compose(self) -> ComposeResult:
        with Grid(id="sell_box"):
            yield Static(f"出售 {self.item_name} ?")
            yield Static(f"可得 ${self.price}")
            with Horizontal(id="sell_buttons"):
                yield PreparationButton("确认出售", id="sell_ok")
                yield PreparationButton("取消", id="sell_cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "sell_ok")


class GameScreen(Screen):
    """Common bindings and directional focus navigation for the run scenes."""

    BINDINGS = [
        ("q", "quit", "退出"),
        ("escape", "go_back", "返回"),
        ("up", "focus_up", None),
        ("down", "focus_down", None),
        ("left", "focus_left", None),
        ("right", "focus_right", None),
    ]

    initial_focus_id = "info"

    def __init__(self, run_state=None, *children, **kwargs) -> None:
        super().__init__(*children, **kwargs)
        self.run_state = run_state

    def action_quit(self):
        self.app.exit()

    def action_go_back(self):
        self.app.pop_screen()

    def swap_screen(self, screen) -> None:
        """流程前进:弹出当前屏再推入新屏,避免屏幕栈随回合无限增长。"""
        self.app.pop_screen()
        self.app.push_screen(screen)

    def open_sell(self, kind: str, index: int) -> None:
        """点击小丑/消耗品弹出售确认;确认后真正卖掉。"""
        run = self.run_state
        if run is None:
            return
        if kind == "joker":
            cards = run.jokers
        else:
            cards = run.consumeables
        if not 0 <= index < len(cards):
            return
        card = cards[index]
        info = carrier_label(card)
        price = run.state.sell_value(card)

        def _do(sold: bool) -> None:
            if not sold:
                return
            if kind == "joker":
                run.sell_joker(index)
            else:
                run.sell_consumable(index)
            self.run_worker(self.refresh_run_ui())

        self.app.push_screen(SellDialog(kind, index, info["name"], price), _do)

    async def refresh_run_ui(self) -> None:
        """刷新左侧信息栏与小丑/消耗品/标签条。"""
        for cls in (LeftContent, JokerHorizontalScroll, ConsumableHorizontalScroll, Tag):
            for widget in self.query(cls):
                try:
                    await widget.refresh_run()
                except NoMatches:
                    pass
        self._refresh_counts()

    def _refresh_counts(self) -> None:
        run = run_of(self)
        if run is None:
            return
        self.refresh_joker_count()
        self.refresh_consumable_count()

    def refresh_joker_count(self) -> None:
        run = run_of(self)
        if run is None:
            return
        try:
            self.query_one("#joker_count", Static).update(
                f"[{len(run.jokers)}/{run.joker_slots}]"
            )
        except NoMatches:
            pass

    def refresh_consumable_count(self) -> None:
        run = run_of(self)
        if run is None:
            return
        try:
            self.query_one("#consumable_count", Static).update(
                f"[{len(run.consumeables)}/{run.consumable_slots}]"
            )
        except NoMatches:
            pass

    async def on_mount(self) -> None:
        await self.refresh_run_ui()
        try:
            self.query_one(f"#{self.initial_focus_id}", PreparationButton).focus()
        except NoMatches:
            focusables = self._focusable_widgets()
            if focusables:
                focusables[0].focus()

    def _focusable_widgets(self) -> list[Widget]:
        return [*self.query(FocusableStatic), *self.query(PreparationButton)]

    def _move_directional_focus(self, direction: str) -> None:
        widgets = self._focusable_widgets()
        current = self.focused
        if not widgets:
            return
        if current not in widgets:
            widgets[0].focus()
            return

        current_region = current.region
        current_x = current_region.x + current_region.width / 2
        current_y = current_region.y + current_region.height / 2
        candidates = []
        for widget in widgets:
            if widget is current:
                continue
            region = widget.region
            widget_x = region.x + region.width / 2
            widget_y = region.y + region.height / 2
            delta_x = widget_x - current_x
            delta_y = widget_y - current_y
            if direction == "left" and delta_x >= 0:
                continue
            if direction == "right" and delta_x <= 0:
                continue
            if direction == "up" and delta_y >= 0:
                continue
            if direction == "down" and delta_y <= 0:
                continue
            primary = abs(delta_x) if direction in ("left", "right") else abs(delta_y)
            secondary = abs(delta_y) if direction in ("left", "right") else abs(delta_x)
            candidates.append((primary * 1000 + secondary, widget))

        if candidates:
            _, target = min(candidates, key=lambda item: item[0])
            target.focus()
            target.scroll_visible()

    def action_focus_up(self) -> None:
        self._move_directional_focus("up")

    def action_focus_down(self) -> None:
        self._move_directional_focus("down")

    def action_focus_left(self) -> None:
        self._move_directional_focus("left")

    def action_focus_right(self) -> None:
        self._move_directional_focus("right")
