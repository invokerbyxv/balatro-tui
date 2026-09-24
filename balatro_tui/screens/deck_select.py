from textual.app import ComposeResult
from textual.containers import HorizontalGroup
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Header, Footer, Button, Static

from balatro_tui.screens.preparation import PreparationScreen
from balatro_tui.utils.lua_data import load_definitions
from balatro_tui.utils.loc_text import loc_name


def _deck_options() -> list[dict]:
    defs = (load_definitions().get("Back") or {})
    out = []
    for key, c in defs.items():
        if c.get("omit") or key == "b_challenge":
            continue
        name = loc_name("Back", key) or c.get("name") or key
        out.append({"key": key, "name": name, "desc": c.get("name", "")})
    return out


def _stake_options() -> list[dict]:
    return [
        {"key": "stake_1", "name": "白色底注", "desc": "标准规则"},
        {"key": "stake_2", "name": "红色底注", "desc": "小盲不奖励金钱"},
        {"key": "stake_3", "name": "绿色底注", "desc": "目标分增长更快"},
        {"key": "stake_4", "name": "黑色底注", "desc": "商店可能出永恒小丑"},
    ]


class SelectionRow(HorizontalGroup):

    def __init__(self, row, id):
        super().__init__(id=id)
        self.row = row
        self.index = 0
        self.can_focus = True

    def compose(self) -> ComposeResult:
        yield Button("<", flat=True, id=f"{self.id}_left")
        yield Static(self.current_text, id=f"{self.id}_static")
        yield Button(">", flat=True, id=f"{self.id}_right")

    @property
    def current_text(self) -> str:
        entry = self.row[self.index]
        return f"{entry.get('name')} {entry.get('desc', '')}"

    def step(self, delta: int):
        self.index = (self.index + delta) % len(self.row)
        self.query_one(f"#{self.id}_static", Static).update(self.current_text)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id.endswith("_left"):
            self.step(-1)
        elif event.button.id.endswith("_right"):
            self.step(1)


class DeckSelectScreen(Screen):

    CSS_PATH = "../css/selection.tcss"

    BINDINGS = [
        ("q", "quit", "退出"),
        ("escape", "go_back", "返回"),
        ("enter", "confirm_selection", "确认选择"),

        ("up", "up", ""),
        ("down", "down", ""),
        ("left", "left", ""),
        ("right", "right", ""),
    ]

    def __init__(self, game_state):
        super().__init__()
        self.game_state = game_state
        self.deck_options = _deck_options()
        self.stake_options = _stake_options()

    def compose(self) -> ComposeResult:
        yield Header()
        yield SelectionRow(id="deck_select", row=self.deck_options)
        yield SelectionRow(id="stake_select", row=self.stake_options)
        yield Footer()

    def on_mount(self):
        self.query_one("#deck_select", SelectionRow).focus()

    def action_quit(self):
        self.app.exit()

    def action_go_back(self):
        self.app.pop_screen()

    def _active_row(self) -> SelectionRow | None:
        widget: Widget | None = self.focused
        while widget is not None:
            if isinstance(widget, SelectionRow):
                return widget
            widget = widget.parent
        return None

    def action_up(self):
        self.query_one("#deck_select", SelectionRow).focus()

    def action_down(self):
        self.query_one("#stake_select", SelectionRow).focus()

    def action_left(self):
        row = self._active_row()
        if row:
            row.step(-1)

    def action_right(self):
        row = self._active_row()
        if row:
            row.step(1)

    def action_confirm_selection(self):
        deck_row = self.query_one("#deck_select", SelectionRow)
        stake_row = self.query_one("#stake_select", SelectionRow)
        deck_entry = deck_row.row[deck_row.index]
        self.game_state.stake = stake_row.index + 1
        self.game_state.set_deck(deck_entry["key"])
        self.app.push_screen(PreparationScreen(self.game_state))