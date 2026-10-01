from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalGroup
from textual.widgets import Button, Header, Footer, Static

from ..game_engine import carrier_label
from .common import (
    GameLayout,
    GameScreen,
    PreparationButton,
    RightRow1,
    Tag,
)

_ROW_ZH = {
    "blind": "盲注奖励",
    "hands": "剩余出牌",
    "discards": "剩余弃牌",
    "tags": "标签奖励",
    "interest": "利息",
    "gold": "金币牌",
}


def _row_label(key: str) -> str:
    if key.startswith("joker:"):
        jk = key.split(":", 1)[1]
        try:
            return f"小丑 {carrier_label_by_key(jk)['name']}"
        except Exception:
            return "小丑奖励"
    return _ROW_ZH.get(key, key)


def carrier_label_by_key(key: str) -> dict:
    from ..utils.collection_data import joker_item
    return joker_item(key)


class SettlementPanel(VerticalGroup):

    def __init__(self, mode, result=None, **kwargs):
        super().__init__(**kwargs)
        self.mode = mode              # "cash_out" | "won" | "lost"
        self.result = result or {}

    def compose(self) -> ComposeResult:
        if self.mode == "lost":
            yield Static("未达成目标", id="cash_out")
            yield Static("本局失败 · 没有金钱奖励", classes="fail_text", markup=False)
        else:
            total = self.result.get("total", 0)
            title = "通关胜利!" if self.mode == "won" else f"提现: ${total}"
            yield Static(title, id="cash_out", markup=False)
            rows = self.result.get("rows") or []
            for key, amount in rows:
                yield Horizontal(
                    Static(_row_label(key), classes="row_label"),
                    Static(f"${amount}", classes="row_amount"),
                    classes="settlement_row",
                )
        yield Static("· " * 16, id="settlement_divider")
        label = {"lost": "返回首页", "won": "继续(无尽模式)"}.get(self.mode, "收下")
        yield PreparationButton(label, id="collect")


class RightRow2Sub(Horizontal):

    def __init__(self, mode, result=None, **kwargs):
        super().__init__(**kwargs)
        self.mode = mode
        self.result = result

    def compose(self) -> ComposeResult:
        yield SettlementPanel(self.mode, self.result)
        yield Tag()


class SettlementScreen(GameScreen):
    """结算场景:提现明细 / ante 8 通关胜利(可无尽) / 失败回首页。"""

    CSS_PATH = ["../css/common.tcss", "../css/settlement.tcss"]
    BINDINGS = [
        ("enter", "collect_btn", "确认"),
        *GameScreen.BINDINGS,
    ]

    initial_focus_id = "collect"

    def __init__(self, run_state=None) -> None:
        super().__init__(run_state)
        run = self.run_state
        self.mode = "cash_out"
        self.result: dict = {}
        if run is not None:
            if run.phase == "round_won":
                # end_round 恰好调用一次:发钱、进入商店(或 ante8 通关)
                self.result = run.end_round()
                if run.phase == "won":
                    self.mode = "won"
            elif run.phase == "round_lost":
                run.check_run_end()
                self.mode = "lost"
            elif run.phase == "won":
                self.mode = "won"

    def compose(self) -> ComposeResult:
        yield Header()
        yield GameLayout(RightRow1(), RightRow2Sub(self.mode, self.result))
        yield Footer()

    def action_collect_btn(self) -> None:
        self._done()

    def _done(self) -> None:
        run = self.run_state
        if self.mode == "lost":
            from .home import HomeScreen
            self.app.switch_screen(HomeScreen())
            return
        if self.mode == "won":
            run.continue_endless()
        from .shop import ShopScreen
        self.swap_screen(ShopScreen(run))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "collect":
            self._done()
