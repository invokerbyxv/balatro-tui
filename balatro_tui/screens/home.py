from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Header, Footer, Button
from textual.screen import Screen

from .deck_select import DeckSelectScreen
from ..game_engine.state import GameState
from .collection import CollectionScreen

class HomeScreen(Screen):
    CSS_PATH = "../css/home.tcss"
    
    BINDINGS = [
        ("enter", "start_game", "开始游戏"),
        ("c", "open_collection", "收藏"),
        ("left", "focus_prev", None),
        ("right", "focus_next", None),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Horizontal(
                Button("开始游戏", id="start_btn"),
                Button("收藏", id="collection_btn"),
                id="buttons"
            ),
            id="home-container"
        )
        yield Footer()

    def action_quit(self):
        self.app.exit()

    def _button_ids(self) -> list[str]:
        return ["start_btn", "collection_btn"]

    def action_focus_next(self):
        self._move_focus(1)

    def action_focus_prev(self):
        self._move_focus(-1)

    def _move_focus(self, step: int):
        ids = self._button_ids()
        current = self.focused
        if current is not None and current.id in ids:
            idx = (ids.index(current.id) + step) % len(ids)
        else:
            idx = 0
        self.query_one(f"#{ids[idx]}", Button).focus()

    def action_start_game(self):
        self.app.push_screen(DeckSelectScreen(GameState()))

    def action_open_collection(self):
        self.app.push_screen(CollectionScreen())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "exit_btn":
            self.app.exit()
        elif event.button.id == "start_btn":
            self.app.push_screen(DeckSelectScreen(GameState()))
        elif event.button.id == "collection_btn":
            self.app.push_screen(CollectionScreen())