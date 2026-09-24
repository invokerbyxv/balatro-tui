"""Shared widgets for the in-run scenes (blind choice, battle, shop, settlement, boosters)."""

from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.containers import Center, Container, Horizontal, HorizontalScroll, VerticalGroup, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Button, DataTable, Static

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


def _state(screen: Screen):
    return getattr(screen, "game_state", None)


class LeftContent(VerticalGroup):

    def compose(self) -> ComposeResult:
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
        tb_1 = DataTable(id="left_content_tb_1")
        tb_1.add_column("出牌", key="plays")
        tb_1.add_column("弃牌", key="discards")
        tb_1.add_column("底注", key="ante")
        tb_1.add_column("回合", key="round")
        tb_1.add_column("钱", key="money")
        tb_1.add_row(0, 0, "1/8", 1, "$4")
        tb_1.cursor_type = "none"
        yield tb_1

        yield Horizontal(
            PreparationButton("游戏信息", id="info"),
            Static("[0/52]", id="card_deck"),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "info":
            from .game_info import GameInfoScreen
            self.app.push_screen(GameInfoScreen(_state(self.screen)))
            event.stop()

    def refresh_run(self, state=None) -> None:
        state = state or _state(self.screen)
        if state is None:
            return
        blind = state.current_blind
        level = blind.name if blind else f"底注 {state.ante}"
        self.query_one("#level", Static).update(level)
        require = f"目标: {format_number(state.blind_target)}" if blind else "目标: --"
        self.query_one("#require", Static).update(require)
        reward = f"奖励: ${blind.dollars}" if blind else "奖励: $0"
        self.query_one("#rewards", Static).update(reward)
        self.query_one("#score", Static).update(f"得分: {format_number(state.score_chips)}")
        calc = state.last_calc
        if calc:
            self.query_one("#chips", Static).update(f"{format_number(calc['chips'])}")
            self.query_one("#mult", Static).update(f"× {format_number(calc['mult'])}")
        else:
            self.query_one("#chips", Static).update("0")
            self.query_one("#mult", Static).update("0")
        hands = state.hands_left if hasattr(state, "hands_left") else 0
        discards = state.discards_left if hasattr(state, "discards_left") else 0
        tbl = self.query_one("#left_content_tb_1", DataTable)
        if tbl.row_count:
            tbl.update_cell_at((0, 0), hands)
            tbl.update_cell_at((0, 1), discards)
            tbl.update_cell_at((0, 3), f"<{state.ante}/{8}>")
            tbl.update_cell_at((0, 4), f"${state.dollars}")
        self.query_one("#card_deck", Static).update(
            f"[{len(state.deck)}]/[{52}]"
        )


class LeftContainer(Container):

    def compose(self) -> ComposeResult:
        yield LeftContent()


class JokerHorizontalScroll(
    ScrollInteraction, FocusNavigationScroll, HorizontalMouseScroll, HorizontalScroll
):

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._n = 0

    def compose(self) -> ComposeResult:
        self.can_focus = True
        self.can_focus_children = True
        yield from self._children()

    def _children(self):
        state = _state(self.screen)
        jokers = state.jokers if state else []
        for i, joker in enumerate(jokers, start=1):
            self._n += 1
            item = FocusableStatic(joker.get("label") or "[小丑]", id=f"joker_{self._n}")
            item.tooltip = joker.get("desc") or "小丑牌"
            yield item

    def _rebuild(self) -> None:
        self.remove_children()
        for w in self._children():
            self.mount(w)

    def refresh_run(self, state=None) -> None:
        self._rebuild()


class ConsumableHorizontalScroll(
    ScrollInteraction, FocusNavigationScroll, HorizontalMouseScroll, HorizontalScroll
):

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._n = 0

    def compose(self) -> ComposeResult:
        self.can_focus = True
        self.can_focus_children = True
        yield from self._children()

    def _children(self):
        state = _state(self.screen)
        items = []
        if state:
            for t in ("tarots", "planets", "spectrals"):
                items.extend((t, x) for x in state.consumables.get(t, []))
        for i, (t, item) in enumerate(items, start=1):
            title = {"tarots": "塔罗", "planets": "星球", "spectrals": "幻灵"}.get(t, "消耗品")
            self._n += 1
            fs = FocusableStatic(f"[{title}]", id=f"consumable_{self._n}")
            if isinstance(item, dict):
                fs.tooltip = item.get("desc") or "消耗品"
            yield fs

    def _rebuild(self) -> None:
        self.remove_children()
        for w in self._children():
            self.mount(w)

    def refresh_run(self, state=None) -> None:
        self._rebuild()


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

    def compose(self) -> ComposeResult:
        self.can_focus = True
        self.can_focus_children = True
        for index, label in enumerate((
            "[负片]", "[负片]", "[负片]", "[负片]",
        ), start=1):
            yield FocusableStatic(label, id=f"tag_{index}")


class RightContainer(Container):
    pass


class GameLayout(Horizontal):
    """Left info panel plus the scene-specific right side."""

    def __init__(self, *right_children: Widget) -> None:
        super().__init__(LeftContainer(), RightContainer(*right_children))


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

    def action_quit(self):
        self.app.exit()

    def action_go_back(self):
        self.app.pop_screen()

    def refresh_run_ui(self) -> None:
        """刷新左侧信息栏与小丑/消耗品条。"""
        for cls, method in (
            (LeftContent, "refresh_run"),
            (JokerHorizontalScroll, "refresh_run"),
            (ConsumableHorizontalScroll, "refresh_run"),
        ):
            for widget in self.query(cls):
                try:
                    getattr(widget, method)()
                except NoMatches:
                    pass
        self._refresh_counts()

    def _refresh_counts(self) -> None:
        state = _state(self)
        if state is None:
            return
        for widget in self.query(JokerHorizontalScroll):
            self.refresh_joker_count()
        for widget in self.query(ConsumableHorizontalScroll):
            self.refresh_consumable_count()

    def refresh_joker_count(self) -> None:
        state = _state(self)
        if state is None:
            return
        n = len(state.jokers)
        cap = state.params.get("joker_slots", 5)
        try:
            self.query_one("#joker_count", Static).update(f"[{n}/{cap}]")
        except NoMatches:
            pass

    def refresh_consumable_count(self) -> None:
        state = _state(self)
        if state is None:
            return
        n = sum(len(state.consumables.get(t, [])) for t in ("tarots", "planets", "spectrals"))
        cap = state.params.get("consumables", 2)
        try:
            self.query_one("#consumable_count", Static).update(f"[{n}/{cap}]")
        except NoMatches:
            pass

    def on_mount(self) -> None:
        self.refresh_run_ui()
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