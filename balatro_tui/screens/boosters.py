from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalGroup
from textual.widgets import Button, Header, Footer, Static

from .common import (
    FocusableStatic,
    GameLayout,
    GameScreen,
    PreparationButton,
    RightRow1,
)

from ..utils.lua_data import load_definitions, get_config
from ..utils.loc_text import loc_name
from ..utils.collection_data import joker_vars, tarot_vars, planet_vars, _desc, RARITY_ZH

PACK_TITLES = {
    "buffoon": "小丑包",
    "arcana": "秘法包",
    "celestial": "星球包",
}


class PackChoice(FocusableStatic):

    def __init__(self, kind: str, item: dict, **kwargs) -> None:
        super().__init__(item["label"], **kwargs)
        self.kind = kind
        self.item = item
        self.tooltip = item.get("desc") or ""

    def on_click(self, event) -> None:
        self.screen.select(self)


class PackCards(Horizontal):

    def __init__(self, options, **kwargs):
        super().__init__(**kwargs)
        self.options = options

    def compose(self) -> ComposeResult:
        for i, (kind, item) in enumerate(self.options, start=1):
            yield PackChoice(kind, item, id=f"pack_card_{i}")


class PackBar(Horizontal):

    def compose(self) -> ComposeResult:
        yield PreparationButton("选择", id="pack_select")
        yield PreparationButton("跳过", id="pack_skip")


class BoostersArea(VerticalGroup):

    def __init__(self, title, options, **kwargs):
        super().__init__(**kwargs)
        self.title = title
        self.options = options

    def compose(self) -> ComposeResult:
        yield Static(f"{self.title} 选择 1", id="pack_name")
        yield PackCards(self.options)
        yield PackBar()


class RightRow2Sub(Horizontal):

    def __init__(self, title, options, **kwargs):
        super().__init__(**kwargs)
        self.title = title
        self.options = options

    def compose(self) -> ComposeResult:
        yield BoostersArea(self.title, self.options)


class BoostersScreen(GameScreen):
    """补充包选择场景。"""

    CSS_PATH = ["../css/common.tcss", "../css/boosters.tcss"]

    BINDINGS = [
        ("left", "focus_prev_card", None),
        ("right", "focus_next_card", None),
        *GameScreen.BINDINGS,
    ]

    def __init__(self, game_state=None, pack_key="buffoon", cost=4) -> None:
        super().__init__()
        self.game_state = game_state
        self.pack_key = pack_key
        self.cost = cost
        self.selected_index = 0
        self.options = self._make_options()

    def _make_options(self) -> list:
        defs = load_definitions()
        loc_joker = loc_name
        options = []
        if self.pack_key == "buffoon":
            pool = list((defs.get("Joker") or {}).keys())
            import random
            picks = random.sample(pool, 2)
            for k in picks:
                options.append(("joker", _joker_from_key(k)))
        elif self.pack_key == "arcana":
            pool = list((defs.get("Tarot") or {}).keys())
            import random
            for k in random.sample(pool, 2):
                options.append(("tarot", _consumable_from_key("Tarot", k)))
        elif self.pack_key == "celestial":
            pool = list((defs.get("Planet") or {}).keys())
            import random
            for k in random.sample(pool, 2):
                options.append(("planet", _consumable_from_key("Planet", k)))
        return options

    def compose(self) -> ComposeResult:
        title = PACK_TITLES.get(self.pack_key, "补充包")
        yield Header()
        yield GameLayout(RightRow1(), RightRow2Sub(title, self.options))
        yield Footer()

    def on_mount(self):
        self.refresh_run_ui()
        self._sync_selection()

    def select(self, widget) -> None:
        self.selected_index = int(widget.id.rsplit("_", 1)[1]) - 1
        self._sync_selection()

    def _sync_selection(self) -> None:
        card1 = self.query_one("#pack_card_1", PackChoice)
        card2 = self.query_one("#pack_card_2", PackChoice)
        card1.set_class(self.selected_index == 0, "selected")
        card2.set_class(self.selected_index == 1, "selected")

    def action_focus_prev_card(self):
        self.selected_index = 0
        self._sync_selection()
        self.query_one("#pack_card_1", PackChoice).focus()

    def action_focus_next_card(self):
        self.selected_index = 1
        self._sync_selection()
        self.query_one("#pack_card_2", PackChoice).focus()

    def _apply(self) -> None:
        kind, item = self.options[self.selected_index]
        if kind == "joker":
            self.game_state.jokers.append(item)
        elif kind == "tarot":
            self.game_state.consumables.setdefault("tarots", []).append(item)
        elif kind == "planet":
            self.game_state.consumables.setdefault("planets", []).append(item)
        self.app.pop_screen()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "pack_select":
            self._apply()
        elif event.button.id == "pack_skip":
            self.app.pop_screen()


def _joker_from_key(k: str) -> dict:
    from ..utils.collection_data import joker_item
    return joker_item(k)


def _consumable_from_key(set_name: str, k: str) -> dict:
    defs = load_definitions()
    loc = loc_name
    c = (defs.get(set_name) or {}).get(k) or {}
    cfg = get_config(c)
    name = loc_name(set_name, k)
    if set_name == "Tarot":
        vars_ = tarot_vars(k, cfg)
    else:
        vars_ = planet_vars(cfg, defs.get("_hands") or {})
    return {
        "key": k,
        "label": f"[{name}]",
        "desc": _desc(set_name, k, vars_),
        "cost": c.get("cost") or 1,
    }