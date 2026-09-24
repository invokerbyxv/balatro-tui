from textual.app import ComposeResult
from textual.containers import Center, Horizontal, HorizontalScroll, Vertical, VerticalGroup
from textual.widgets import Button, Header, Footer, Static

from .common import (
    FocusableStatic,
    FocusNavigationScroll,
    GameLayout,
    GameScreen,
    HorizontalMouseScroll,
    PreparationButton,
    RightRow1,
    ScrollInteraction, Tag,
)

RANK_ORDER = {
    "A": 14, "K": 13, "Q": 12, "J": 11, "10": 10,
    "9": 9, "8": 8, "7": 7, "6": 6, "5": 5, "4": 4, "3": 3, "2": 2,
}
SUIT_ORDER = {"♠": 0, "♥": 1, "♣": 2, "♦": 3}

HAND_CARDS = [
    "♠A 闪箔\n倍率 红蜡",
    "♥K",
    "♥K",
    "♥9",
    "♥5",
    "♣K",
    "♣7",
    "♣6",
    "♦K 钢铁",
]


def _card_key(text: str) -> tuple[int, int]:
    token = text.split("\n", 1)[0].split()[0]
    suit, rank = token[0], token[1:]
    return SUIT_ORDER[suit], RANK_ORDER[rank]


class Card(FocusableStatic):
    """A hand card rendered as plain text."""

    def __init__(self, text: str, **kwargs) -> None:
        super().__init__(text, **kwargs)
        self.card_text = text


class HandHorizontalScroll(
    ScrollInteraction, FocusNavigationScroll, HorizontalMouseScroll, HorizontalScroll
):

    def compose(self) -> ComposeResult:
        self.can_focus = True
        self.can_focus_children = True
        for index, text in enumerate(HAND_CARDS, start=1):
            yield Card(text, id=f"hand_{index}")


class ActionBar(Horizontal):

    def compose(self) -> ComposeResult:
        yield Center(PreparationButton("出牌", id="play_hand"))
        yield VerticalGroup(
            Center(Static("理牌")),
            Horizontal(
                PreparationButton("点数", id="sort_rank"),
                PreparationButton("花色", id="sort_suit"),
                id="sort_buttons"
            ),
            id="sort_group"
        )
        yield Center(PreparationButton("弃牌", id="discard_hand"))


class BattleArea(Vertical):

    def compose(self) -> ComposeResult:
        yield HandHorizontalScroll()
        yield ActionBar()


class RightRow2Sub(Horizontal):

    def compose(self) -> ComposeResult:
        yield BattleArea()
        yield Tag()

class BattleScreen(GameScreen):
    """对战场景。"""

    CSS_PATH = ["../css/common.tcss", "../css/battle.tcss"]

    def __init__(self, game_state=None) -> None:
        super().__init__()
        self.game_state = game_state

    def compose(self) -> ComposeResult:
        yield Header()
        yield GameLayout(RightRow1(), RightRow2Sub())
        yield Footer()

    def _sort_hand(self, key) -> None:
        hand = self.query_one(HandHorizontalScroll)
        cards = sorted(hand.query(Card), key=lambda x: key(x.card_text))
        if cards and cards[0] is not hand.children[0]:
            hand.move_child(cards[0], before=hand.children[0])
        for previous, card in zip(cards, cards[1:]):
            hand.move_child(card, after=previous)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "play_hand":
            from .settlement import SettlementScreen

            self.app.push_screen(SettlementScreen(self.game_state))
        elif event.button.id == "sort_rank":
            self._sort_hand(lambda text: _card_key(text)[::-1])
        elif event.button.id == "sort_suit":
            self._sort_hand(_card_key)
