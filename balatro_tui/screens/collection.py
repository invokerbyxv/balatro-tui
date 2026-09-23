from textual.app import ComposeResult
from textual.containers import HorizontalGroup
from textual.widget import Widget
from textual.widgets import Header, Footer, DataTable, Button
from textual.screen import Screen

from ..utils.collection_data import get_rows

COLLECTIONS = {
    "jokers": "小丑牌",
    "decks": "牌组",
    "vouchers": "优惠券",
    "tarots": "塔罗牌",
    "planets": "星球牌",
    "spectrals": "幻灵牌",
    "enhancements": "增强卡牌",
    "seals": "蜡封",
    "editions": "版本",
    "boosters": "补充包",
    "tags": "标签",
    "blinds": "盲注",
}

COLUMNS = ("名称", "描述", "价格", "稀有度")


class CollectionDetailScreen(Screen):

    def __init__(self, *children, id: str, collection_name: str):
        self.collection_name = collection_name
        super().__init__(*children, id=id)

    BINDINGS = [
        ("q", "quit", "退出"),
        ("escape", "go_back", "返回")
    ]

    def action_quit(self):
        self.app.exit()

    def action_go_back(self):
        self.app.pop_screen()

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id=f"{self.collection_name}_table")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(f"#{self.collection_name}_table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.add_columns(*COLUMNS)
        rows = get_rows(self.collection_name)
        table.add_rows(
            [(r["name"], r["desc"], r["price"], r["rarity"]) for r in rows]
        )
        table.focus()


class CollectionList(HorizontalGroup):

    def __init__(self, id: str, keys: list[str], *children: Widget,):
        self.keys = keys
        super().__init__(*children, id=id)

    def compose(self) -> ComposeResult:
        for k in self.keys:
            count = len(get_rows(k))
            label = f"{COLLECTIONS[k]}  {count}/{count}"
            yield Button(label, id=f"{k}_c_btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        category = event.button.id.removesuffix("_c_btn")
        screen = CollectionDetailScreen(id=f"{category}_c_screen", collection_name=category)
        self.app.push_screen(screen)


class CollectionScreen(Screen):

    CSS_PATH = "../css/collection.tcss"

    BINDINGS = [
        ("q", "quit", "退出"),
        ("escape", "go_back", "返回"),
        ("left", "move_focus(-1, 0)", None),
        ("right", "move_focus(1, 0)", None),
        ("up", "move_focus(0, -1)", None),
        ("down", "move_focus(0, 1)", None),
    ]

    def action_quit(self):
        self.app.exit()

    def action_go_back(self):
        self.app.pop_screen()

    def _get_rows(self) -> list[list[Button]]:
        return [list(cl.query(Button)) for cl in self.query(CollectionList)]

    def _find_pos(self, rows: list[list[Button]]) -> tuple[int, int] | None:
        focused = self.focused
        for r, row in enumerate(rows):
            for c, btn in enumerate(row):
                if btn is focused:
                    return r, c
        return None

    def action_move_focus(self, dx: int, dy: int) -> None:
        rows = self._get_rows()
        if not rows:
            return
        pos = self._find_pos(rows)
        if pos is None:
            rows[0][0].focus()
            return
        r, c = pos
        if dx:
            c = (c + dx) % len(rows[r])
        if dy:
            r += dy
            if not 0 <= r < len(rows):
                return
            c = min(c, len(rows[r]) - 1)
        rows[r][c].focus()

    def compose(self) -> ComposeResult:
        all_key = [k for k in COLLECTIONS]
        yield Header()
        yield CollectionList(id="collection1", keys=all_key[:6])
        yield CollectionList(id="collection2", keys=all_key[6:])
        yield Footer()
