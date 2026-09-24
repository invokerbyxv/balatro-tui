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
from ..utils.collection_data import joker_vars, tarot_vars, planet_vars, spectral_vars, _desc, RARITY_ZH

PACK_TITLES = {
    "buffoon": "小丑包",
    "arcana": "秘法包",
    "celestial": "星球包",
    "spectral": "妖法包",
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
        yield Static(self.title, id="pack_name")
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
    """补充包选择场景(支持普通/妖法包与 variable extra/choose)。"""

    CSS_PATH = ["../css/common.tcss", "../css/boosters.tcss"]

    BINDINGS = [
        ("left", "focus_prev_card", None),
        ("right", "focus_next_card", None),
        *GameScreen.BINDINGS,
    ]

    def __init__(self, game_state=None, pack=None) -> None:
        super().__init__()
        self.game_state = game_state
        self.pack = pack or {}
        self.pack_key = (self.pack.get("kind") or "buffoon").lower()
        self.extra = self.pack.get("extra") or 2
        self.choose = self.pack.get("choose") or 1
        self.selected_index = 0
        self.options = self._make_options()

    def _make_options(self) -> list:
        import random
        defs = load_definitions()
        pool = list((defs.get(self._set_name()) or {}).keys())
        picks = random.sample(pool, min(self.extra, len(pool)))
        kind = "joker" if self.pack_key == "buffoon" else self.pack_key
        return [(kind, _item(self.pack_key, k)) for k in picks]

    def _set_name(self) -> str:
        return {
            "buffoon": "Joker",
            "arcana": "Tarot",
            "celestial": "Planet",
            "spectral": "Spectral",
        }.get(self.pack_key, "Joker")

    def compose(self) -> ComposeResult:
        title = PACK_TITLES.get(self.pack_key, "补充包")
        yield Header()
        yield GameLayout(RightRow1(), RightRow2Sub(f"{title} 选择 {self.choose}", self.options))
        yield Footer()

    async def on_mount(self):
        await self.refresh_run_ui()
        self._sync_selection()

    def select(self, widget) -> None:
        self.selected_index = int(widget.id.rsplit("_", 1)[1]) - 1
        self._sync_selection()

    def _sync_selection(self) -> None:
        for i in range(1, self.extra + 1):
            try:
                card = self.query_one(f"#pack_card_{i}", PackChoice)
                card.set_class(self.selected_index == i - 1, "selected")
            except Exception:
                return

    def action_focus_prev_card(self):
        self.selected_index = 0
        self._sync_selection()
        self.query_one("#pack_card_1", PackChoice).focus()

    def action_focus_next_card(self):
        self.selected_index = self.extra - 1
        self._sync_selection()
        self.query_one(f"#pack_card_{self.extra}", PackChoice).focus()

    def _apply(self) -> None:
        kind, item = self.options[self.selected_index]
        if kind == "joker":
            self.game_state.jokers.append(item)
        else:
            self.game_state.consumables.setdefault(kind + "s", []).append(item)
        self.app.pop_screen()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "pack_select":
            self._apply()
        elif event.button.id == "pack_skip":
            self.app.pop_screen()


def _item(pack_key: str, k: str) -> dict:
    from ..utils.collection_data import joker_item
    if pack_key == "buffoon":
        return joker_item(k)
    return _consumable_from_key(pack_key, k)


def _consumable_from_key(set_name: str, k: str) -> dict:
    set_name_map = {"arcana": "Tarot", "celestial": "Planet", "spectral": "Spectral"}
    set_full = set_name_map.get(set_name, set_name)
    defs = load_definitions()
    c = (defs.get(set_full) or {}).get(k) or {}
    cfg = get_config(c)
    name = loc_name(set_full, k)
    if set_full == "Tarot":
        vars_ = tarot_vars(k, cfg)
    elif set_full == "Planet":
        vars_ = planet_vars(cfg, defs.get("_hands") or {})
    else:
        vars_ = spectral_vars(k, cfg)
    return {
        "key": k,
        "label": f"[{name}]",
        "desc": _desc(set_full, k, vars_),
        "cost": c.get("cost") or 1,
    }