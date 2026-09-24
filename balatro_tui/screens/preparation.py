from textual.app import ComposeResult
from textual.containers import Center, Container, Horizontal, VerticalGroup
from textual.widgets import Button, Header, Footer, Static

from .common import (
    GameLayout,
    GameScreen,
    PreparationButton,
    RightRow1,
    Tag,
)


class Blind(Horizontal):
    """一个盲注卡片。selectable=True 时可开打。"""

    selectable = True

    def __init__(self, blind, selectable=True, id=None):
        super().__init__(id=id)
        self.blind = blind
        self.selectable = selectable

    def compose(self) -> ComposeResult:
        role = "开战" if self.selectable else "预告"
        mode = "选择" if self.selectable else "—"
        name = self.blind.name if self.blind else "???"
        target = f"{self.blind.target:,}" if self.blind else "?"
        reward = f"${self.blind.dollars}" if self.blind else "$0"
        key = getattr(self, "id", None)
        yield VerticalGroup(
            Center(PreparationButton(mode, id=f"{key}_select", disabled=not self.selectable)),
            Static(name, classes="blind_name"),
            Static(target),
            Static(reward),
            Center(PreparationButton("跳过盲注", id=f"{key}_skip")),
        )


class Boss(Horizontal):

    def __init__(self, blind):
        super().__init__()
        self.blind = blind

    def compose(self) -> ComposeResult:
        if self.blind is None:
            yield VerticalGroup(
                Static("下一底注"),
                Static("——"),
                Static("boss"),
            )
            return
        yield VerticalGroup(
            Static("Boss 预览"),
            Static(self.blind.name),
            Static(f"{self.blind.target:,}"),
            Static(f"${self.blind.dollars}"),
        )


class RightRow2Sub(Horizontal):

    def __init__(self, choices):
        super().__init__()
        self.choices = choices
        self._ids = ["blind_1", "blind_2", "blind_3"]

    def compose(self) -> ComposeResult:
        selectable = self.choices[0] if self.choices else None
        preview = (self.choices[1] if len(self.choices) > 1 else None)
        boss = (self.choices[2] if len(self.choices) > 2 else None)
        yield Blind(selectable, selectable=True, id="blind_1")
        yield Blind(preview, selectable=False, id="blind_2")
        yield Boss(boss)
        yield Tag()


class RightRow2(Container):

    def __init__(self, choices):
        super().__init__()
        self.choices = choices

    def compose(self) -> ComposeResult:
        yield RightRow2Sub(self.choices)


class PreparationScreen(GameScreen):
    """盲注选择场景。"""

    CSS_PATH = ["../css/common.tcss", "../css/preparation.tcss"]

    def __init__(self, game_state=None) -> None:
        super().__init__()
        self.game_state = game_state

    def compose(self) -> ComposeResult:
        choices = self.game_state.build_blind_choices() if self.game_state else []
        self.choices = choices
        yield Header()
        yield GameLayout(RightRow1(), RightRow2(choices))
        yield Footer()

    def _do_skip(self):
        """跳过当前盲注:奖励金钱并推进。"""
        blind = self.game_state.current_blind or self.game_state.build_blind_choices()[0]
        # 简化:跳过奖励 $5,视为打赢了当前盲注不计分
        self.game_state.dollars += 5
        self.game_state.blind_in_ante = _advance(self.game_state.blind_in_ante)
        from .shop import ShopScreen
        self.app.push_screen(ShopScreen(self.game_state))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        import re
        m = re.match(r"blind_(\d)_select", event.button.id or "")
        if m:
            idx = int(m.group(1)) - 1
            if 0 <= idx < len(self.choices) and idx == 0:
                blind = self.choices[0]
                self.game_state.start_blind(blind)
                from .battle import BattleScreen
                self.app.push_screen(BattleScreen(self.game_state))
        elif event.button.id and event.button.id.endswith("_skip"):
            self._do_skip()


def _advance(v: int) -> int:
    return 1 if v >= 3 else v + 1