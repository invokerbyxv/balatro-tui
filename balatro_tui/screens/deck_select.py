from textual.app import ComposeResult
from textual.containers import HorizontalGroup
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Header, Footer, Button, Static

from balatro_tui.screens.preparation import PreparationScreen
from balatro_tui.utils.lua_data import load_definitions
from balatro_tui.utils.loc_text import loc_name, describe


def _ref_name(ref: str) -> str:
    """把优惠券/消耗牌引用键转成其本地化名称,无法解析时原样返回。"""
    set_name = "Voucher" if ref.startswith("v_") else ("Tarot" if ref.startswith("c_") else "")
    name = loc_name(set_name, ref) if set_name else ""
    return name or ref


def _deck_vars(key: str, cfg: dict) -> list:
    """按描述文本 #n# 占位顺序,从卡组 config 中提取填充值。"""
    if key == "b_anaglyph":
        # 该标签是在一局内动态获得的,这里用其名称占位
        return [loc_name("Tag", "tag_double")]
    if not cfg:
        return []
    abs_ = lambda v: abs(v) if isinstance(v, (int, float)) else v

    if key == "b_red":
        return [cfg.get("discards")]
    if key == "b_blue":
        return [cfg.get("hands")]
    if key == "b_yellow":
        return [cfg.get("dollars")]
    if key == "b_green":
        return [cfg.get("extra_hand_bonus"), cfg.get("extra_discard_bonus")]
    if key == "b_black":
        # 描述文本自带 "-#2#" 符号,config.hands 又是负数,取其绝对值避免 "--1"
        return [cfg.get("joker_slot"), abs_(cfg.get("hands"))]
    if key == "b_magic":
        return [_ref_name(cfg.get("voucher")), _ref_name((cfg.get("consumables") or [None])[0])]
    if key == "b_nebula":
        return [_ref_name(cfg.get("voucher")), cfg.get("consumable_slot")]
    if key == "b_zodiac":
        return [_ref_name(r) for r in (cfg.get("vouchers") or [])[:3]]
    if key == "b_painted":
        return [cfg.get("hand_size"), cfg.get("joker_slot")]
    if key == "b_plasma":
        return [cfg.get("ante_scaling")]
    return []


def _deck_options() -> list[dict]:
    defs = (load_definitions().get("Back") or {})
    out = []
    for key, c in defs.items():
        if c.get("omit") or key == "b_challenge":
            continue
        name = loc_name("Back", key) or c.get("name") or key
        desc = describe("Back", key, _deck_vars(key, c.get("config") or {})) or c.get("name", "")
        out.append({"key": key, "name": name, "desc": desc})
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