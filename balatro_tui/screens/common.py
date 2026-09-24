"""Shared widgets for the in-run scenes (blind choice, battle, shop, settlement, boosters)."""

from textual import events
from textual.app import ComposeResult
from textual.containers import Center, Container, Horizontal, HorizontalScroll, VerticalGroup, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Button, DataTable, Static


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


class LeftContent(VerticalGroup):

    def compose(self) -> ComposeResult:
        yield Horizontal(
            Static("大盲注", id="level"),
            Static("至少得分: 75,000", id="require"),
            id="row_1"
        )
        yield Horizontal(
            Static("奖励: $$$$", id="rewards"),
            Static("回合分数: 0", id="score"),
            id="row_2"
        )
        yield Horizontal(
            Static("0", id="chips"),
            Static("0", id="mult"),
            id="calculation"
        )
        tb_1 = DataTable(id="left_content_tb_1",)
        tb_1.add_column("出牌", key="plays")
        tb_1.add_column("弃牌", key="discards")
        tb_1.add_column("底注", key="ante")
        tb_1.add_column("回合", key="round")
        tb_1.add_column("钱", key="money")
        tb_1.add_row(0, 0, "8/8", 29, "$190")
        tb_1.cursor_type = "none"
        yield tb_1

        yield Horizontal(
            PreparationButton("游戏信息", id="info"),
            Static("卡组: [52/52]", id="card_deck")
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "info":
            from .game_info import GameInfoScreen

            self.app.push_screen(GameInfoScreen())
            event.stop()

class LeftContainer(Container):

    def compose(self) -> ComposeResult:
        yield LeftContent()

class JokerHorizontalScroll(
    ScrollInteraction, FocusNavigationScroll, HorizontalMouseScroll, HorizontalScroll
):

    def compose(self) -> ComposeResult:
        self.can_focus = True
        self.can_focus_children = True
        j_photograph = FocusableStatic("[照片]", id="joker_1")
        j_photograph.tooltip = "打出的第一张人头牌在计分时会给予 X2 倍率"

        yield j_photograph
        for index, label in enumerate((
            "[幻视]", "[帕奇欧]", "[爆米花]", "[致胜之拳]", "[拉面]",
            "[红牌]", "[私人车位]", "[搭乘巴士]", "[乌合之众]", "[马戏团长]",
            "[火箭]", "[璞玉]", "[跑步选手]", "[卫星]",
        ), start=2):
            yield FocusableStatic(label, id=f"joker_{index}")

class ConsumableHorizontalScroll(
    ScrollInteraction, FocusNavigationScroll, HorizontalMouseScroll, HorizontalScroll
):

    def compose(self) -> ComposeResult:
        self.can_focus = True
        self.can_focus_children = True
        for index, label in enumerate((
            "[愚者]", "|[愚者]", "[愚者]", "[地球]", "[地球]",
            "[阋神星]", "[阋神星]", "[阋神星]", "[木星]", "[木星]",
            "[木星]", "[木星]",
        ), start=1):
            yield FocusableStatic(label, id=f"consumable_{index}")


class RightRow1Sub(Horizontal):

    def compose(self) -> ComposeResult:
        yield JokerHorizontalScroll()
        yield Static("[14/14]", id="joker_count")
        yield ConsumableHorizontalScroll()
        yield Static("[11/11]", id="consumable_count")

class RightRow1(Container):
    def compose(self) -> ComposeResult:
        yield RightRow1Sub()


class Tag(ScrollInteraction, FocusNavigationScroll, VerticalScroll):

    def compose(self) -> ComposeResult:
        self.can_focus = True
        self.can_focus_children = True
        for index, label in enumerate((
            "[负片]", "[负片]", "[负片]", "[负片]", "[负片]", "[双倍]", "[双倍]",
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

    def on_mount(self) -> None:
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
