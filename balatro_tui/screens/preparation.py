from textual.app import ComposeResult
from textual.containers import Center, Container, Horizontal, VerticalGroup
from textual.widgets import Button, Header, Footer, Static

from .common import (
    GameLayout,
    GameScreen,
    PreparationButton,
    RightRow1,
    Tag,
    run_of,
)


class Blind(Horizontal):
    """一个盲注卡片。selectable=True 时可开打;boss 附带效果描述。"""

    def __init__(self, info: dict, selectable=True):
        super().__init__()
        self.info = info
        self.selectable = selectable

    def compose(self) -> ComposeResult:
        info = self.info
        mode = "选择" if self.selectable else "—"
        children = [
            Center(PreparationButton(mode, classes="blind_select_btn",
                                     disabled=not self.selectable)),
            Horizontal(
                Static(info["name"], classes="blind_name", markup=False),
                Static(f"{info['chips']:,}", classes="blind_chips"),
                Static(f"${info['dollars']}", classes="blind_reward"),
                classes="blind_stats",
            ),
        ]
        # 只有 BOSS 有特殊效果;小盲/大盲没有效果行
        if info.get("kind") == "boss" and info.get("desc"):
            children.append(Static(f"效果: {info['desc']}", classes="blind_effect", markup=False))
        if self.selectable:
            btn = PreparationButton("跳过盲注", classes="blind_skip_btn")
            run = run_of(self.screen)
            preview = run.skip_tag_preview(info["kind"]) if run else {}
            if preview:
                btn.label = f"跳过盲注 得{preview['name']}"
                btn.tooltip = preview["desc"]
            children.append(Center(btn))
        yield VerticalGroup(*children)


class OfferRow(Horizontal):
    """当前可选盲注(第一个可打,其余为预告)。"""

    def __init__(self, offers):
        super().__init__()
        self.offers = offers

    def compose(self) -> ComposeResult:
        for info in self.offers:
            yield Blind(info, selectable=(info is self.offers[0]))


class RightRow2Sub(Horizontal):
    """盲注卡片行 + 标签条 + 公告/重掷列,三列同一水平行。"""

    def __init__(self, offers):
        super().__init__()
        self.offers = offers

    def compose(self) -> ComposeResult:
        yield OfferRow(self.offers)
        yield Tag()
        yield VerticalGroup(
            Static("", id="notice", markup=False),
            PreparationButton("", id="reroll_boss"),
            id="prep_side",
        )


class RightRow2(Container):

    def __init__(self, offers):
        super().__init__()
        self.offers = offers

    def compose(self) -> ComposeResult:
        yield RightRow2Sub(self.offers)


class PreparationScreen(GameScreen):
    """盲注选择场景:开打 / 跳过(拿标签) / 重掷 BOSS(Director's Cut)。"""

    CSS_PATH = ["../css/common.tcss", "../css/preparation.tcss"]

    def __init__(self, run_state=None) -> None:
        super().__init__(run_state)
        self.offers = run_state.blind_display_choices() if run_state else []

    def compose(self) -> ComposeResult:
        yield Header()
        yield GameLayout(RightRow1(), RightRow2(self.offers))
        yield Footer()

    async def on_mount(self) -> None:
        await super().on_mount()
        self._sync_reroll()

    def _sync_reroll(self) -> None:
        """Director's Cut 有券时允许重掷 BOSS。"""
        run = self.run_state
        info = run.boss_reroll_info() if run else {}
        btn = self.query_one("#reroll_boss", PreparationButton)
        if info.get("available"):
            btn.display = True
            btn.label = f"重掷BOSS ${info.get('cost', 0)}"
        else:
            btn.display = False

    async def _rebuild_offers(self) -> None:
        """跳过/重掷后重建盲注列(引擎已生成新 blind_choices)。"""
        self.offers = self.run_state.blind_display_choices()
        row = self.query_one(OfferRow)
        await row.remove_children()
        for i, info in enumerate(self.offers, start=1):
            await row.mount(Blind(info, selectable=(i == 1)))
        self._sync_reroll()
        await self.refresh_run_ui()

    def _do_skip(self) -> None:
        result = self.run_state.skip_blind()
        if not result.get("ok"):
            return
        notice = self.query_one("#notice", Static)
        text = f"跳过 {result['blind']}:获得 {result['tag_name']}"
        if result.get("dollars"):
            text += f",得 ${result['dollars']}"
        notice.update(text)
        if self.run_state.phase == "shop":
            from .shop import ShopScreen
            self.app.push_screen(ShopScreen(self.run_state))
        else:
            self.run_worker(self._rebuild_offers())

    def _do_reroll_boss(self) -> None:
        result = self.run_state.reroll_boss()
        if result.get("ok"):
            self.query_one("#notice", Static).update("已重掷 BOSS")
            self.run_worker(self._rebuild_offers())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.has_class("blind_select_btn"):
            if self.offers:
                kind = self.run_state.blind_choices[0].kind
                self.run_state.select_blind(kind)
                from .battle import BattleScreen
                self.app.push_screen(BattleScreen(self.run_state))
        elif event.button.has_class("blind_skip_btn"):
            self._do_skip()
        elif event.button.id == "reroll_boss":
            self._do_reroll_boss()
