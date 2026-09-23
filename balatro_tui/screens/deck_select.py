from textual.app import ComposeResult
from textual.containers import HorizontalGroup
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Header, Footer, Button, Static

from balatro_tui.screens.preparation import PreparationScreen
from balatro_tui.utils.collection_data import get_rows


class SelectionRow(HorizontalGroup):

    def __init__(self, row, id):
        super().__init__(id=id)
        self.row = row
        self.index = 0
        self.can_focus = True

    def compose(self) -> ComposeResult:
        yield Button("<", flat=True, id=f"{self.id}_left")
        yield Static(self.current_text, id=f"{self.id}_static")
        yield Button(">", flat=True,  id=f"{self.id}_right")

    @property
    def current_text(self) -> str:
        entry = self.row[self.index]
        return f"{entry['name']} {entry['desc']}"

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

    def compose(self) -> ComposeResult:
        yield Header()
        yield SelectionRow(id="deck_select", row=get_rows("decks"))
        yield SelectionRow(id="stake_select", row=get_rows("stake"))
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
        self.app.push_screen(PreparationScreen(self.game_state))


