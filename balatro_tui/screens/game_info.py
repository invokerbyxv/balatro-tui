from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Header, Footer, DataTable, Static

from ..utils.collection_data import get_hand_levels, get_vouchers


class HandLevelTable(Horizontal):

    def compose(self) -> ComposeResult:
        yield DataTable(id="hand_level_left")
        yield DataTable(id="hand_level_right")

    def on_mount(self) -> None:
        rows = get_hand_levels()
        mid = (len(rows) + 1) // 2
        for side, chunk in (
            ("hand_level_left", rows[:mid]),
            ("hand_level_right", rows[mid:]),
        ):
            tb = self.query_one(f"#{side}", DataTable)
            tb.cursor_type = "row"
            tb.add_columns("牌型", "等级", "筹码", "倍率")
            tb.add_rows([(r["name"], r["level"], r["chips"], r["mult"]) for r in chunk])


class Voucher(Vertical):

    def compose(self) -> ComposeResult:
        for index in range(2):
            yield Horizontal(
                Static("???"), Static("???"),
                Static("???"), Static("???"),
                Static("???"), Static("???"),
                Static("???"), Static("???"),
                classes="voucher_slot",
                id=f"voucher_{index}"
            )

    def on_mount(self) -> None:
        rows = get_vouchers()
        slots = list(self.query(".voucher_slot"))
        for slot in slots:
            index = int(slot.id.split("_")[1])
            cells = list(slot.query(Static))
            for cell, row in zip(cells, rows[index:8 + index]):
                cell.update(row["name"])


class GameInfoScreen(Screen):

    CSS_PATH = "../css/game_info.tcss"

    BINDINGS = [
        ("q", "quit", "退出"),
        ("escape", "go_back", "返回"),
        ("h", "hand", "牌型"),
        ("v", "voucher", "优惠券"),
    ]

    def __init__(self, *children, **kwargs):
        self.mode = "hand"  # "hand" / "voucher",默认牌型
        super().__init__(*children, **kwargs)

    def action_quit(self):
        self.app.exit()

    def action_go_back(self):
        self.app.pop_screen()

    def compose(self) -> ComposeResult:
        yield Header()
        yield HandLevelTable(id="hand_panel")
        yield Voucher(id="voucher_panel")
        yield Footer()

    def on_mount(self) -> None:
        self._apply_mode()

    def _apply_mode(self) -> None:
        self.query_one("#hand_panel").display = self.mode == "hand"
        self.query_one("#voucher_panel").display = self.mode == "voucher"

    def action_hand(self) -> None:
        self.mode = "hand"
        self._apply_mode()

    def action_voucher(self) -> None:
        self.mode = "voucher"
        self._apply_mode()