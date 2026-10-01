"""RunState — balatro_tui 界面与 balatro_cli.engine 之间的适配层。

引擎语义(小丑/消耗品/标签/优惠券/卡背/盲注/stake/计分管线)全部由
balatro_cli.engine 提供;本模块只做三件事:
1. 把「界面持有 Card 对象」翻译成引擎的「indices」接口;
2. 补齐引擎手牌排序、预览等界面专用小操作;
3. 提供显示映射(牌面符号、中文名/描述、逐小丑计分行)。

前端职责:选中状态、Shop 实例由本适配器代管(开局创建一次,
引擎在进入商店时自动补货)。
"""

from __future__ import annotations

import random

from balatro_cli.engine.game_state import GameState
from balatro_cli.engine.hand import get_poker_hand_info
from balatro_cli.engine.shop import Shop, ShopItem

from ..utils.collection_data import (
    _desc,
    blind_vars,
    consume_set_of,
    consumable_item,
    joker_item,
)
from ..utils.loc_text import loc_name
from ..utils.lua_data import load_definitions

# 引擎牌面(花色字母/点数字母)→ 显示
SUIT_SYMBOL = {"S": "♠", "H": "♥", "C": "♣", "D": "♦"}
RED_SUITS = ("H", "D")
RANK_DISPLAY = {"T": "10"}
RANK_ORDER = ["2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K", "A"]
SUIT_ORDER = {"S": 0, "H": 1, "C": 2, "D": 3}

HAND_ZH = {
    "High Card": "高牌", "Pair": "对子", "Two Pair": "两对",
    "Three of a Kind": "三条", "Straight": "顺子", "Flush": "同花",
    "Full House": "葫芦", "Four of a Kind": "四条",
    "Straight Flush": "同花顺", "Five of a Kind": "五条",
    "Flush House": "同花葫芦", "Flush Five": "同花五条",
}

EDITION_MARK = {
    "e_foil": "箔",
    "e_holo": "镭",
    "e_polychrome": "彩",
    "e_negative": "负",
}

SET_MARK = {"Tarot": "塔罗", "Planet": "星球", "Spectral": "幻灵", "Joker": ""}


def hand_name(key: str) -> str:
    return HAND_ZH.get(key, key or "")


def card_label(card) -> tuple[str, str]:
    """引擎 playing card → (显示文本, 颜色类)。

    返回如 ("♠A", "red");enhancement/edition/seal 以尾缀标注。
    """
    rank = RANK_DISPLAY.get(card.rank, card.rank)
    suit = SUIT_SYMBOL.get(card.suit, "?")
    marks = []
    if card.enhancement:
        marks.append(loc_name("Enhanced", card.enhancement)[:1])
    if card.seal:
        seals = {"red": "红", "blue": "蓝", "gold": "金", "purple": "紫"}
        marks.append(seals.get(card.seal, "印"))
    text = suit + rank + ("".join(marks))
    return text, ("red" if card.suit in RED_SUITS else "black")


def carrier_label(card) -> dict:
    """小丑/消耗品(JokerCard)→ 中文名、描述、价格、稀有度。"""
    key = card.key
    if card.is_joker:
        info = joker_item(key)
        name, desc, rarity = info["name"], info["desc"], info["rarity"]
    else:
        set_name = consume_set_of(key) or "Joker"
        info = consumable_item(set_name, key)
        name, desc = info["name"], info["desc"]
        rarity = SET_MARK.get(set_name, "")
    edition = getattr(card, "edition", None)
    if edition:
        name = f"{EDITION_MARK.get(edition, '')}{name}"
        extra_desc = loc_name("Edition", edition)
        if extra_desc:
            desc = f"{desc}({extra_desc})"
    return {
        "key": key,
        "name": name or key,
        "label": f"[{name or key}]",
        "desc": desc,
        "rarity": rarity,
        "cost": getattr(card, "cost", 0) or getattr(card, "sell_cost", 0),
    }


def blind_display(key: str, chips: int, dollars: int) -> dict:
    """盲注键 → 界面展示数据(中文名、目标、奖励、效果描述)。"""
    defs = load_definitions().get("Blind") or {}
    entry = defs.get(key) or {}
    name = loc_name("Blind", key) or entry.get("name") or key
    desc = _desc("Blind", key, blind_vars(entry)) if entry else ""
    return {"key": key, "name": name, "chips": chips, "dollars": dollars, "desc": desc}


def score_lines(result) -> list[str]:
    """ScoreResult → 逐行计分转写(基础 → 逐牌 → 逐小丑 → 汇总)。"""
    lines = [
        f"{hand_name(result.hand_key)} Lv{result.level}: "
        f"{int(result.base_chips)} × {result.base_mult:g}",
    ]
    for d in result.card_deltas:
        bits = []
        if d.chips:
            bits.append(f"+{int(d.chips)}筹码")
        if d.mult:
            bits.append(f"+{d.mult:g}倍率")
        if d.x_mult != 1.0:
            bits.append(f"×{d.x_mult:g}倍率")
        if bits:
            text, _ = card_label(d.card)
            lines.append(f"  {text}: {' '.join(bits)}")
    for jd in result.joker_deltas:
        info = joker_item(jd.key) if not jd.key.startswith("c_") else None
        name = info["name"] if info else jd.name
        bits = []
        if jd.chips:
            bits.append(f"+{int(jd.chips)}筹码")
        if jd.mult:
            bits.append(f"+{jd.mult:g}倍率")
        if jd.x_mult != 1.0:
            bits.append(f"×{jd.x_mult:g}倍率")
        lines.append(f"  {name or jd.key}: {' '.join(bits) if bits else '触发'}")
    for event, eff in result.effects_log:
        if eff.message:
            lines.append(f"  · {eff.message}")
    lines.append(
        f"= {int(result.total_chips)} × {result.total_mult:g} = {result.score}"
    )
    return lines


class RunState:
    """对局适配器:界面只跟它说话,不直接 import 引擎。"""

    def __init__(self, seed: str | None = None) -> None:
        self.seed = seed or f"{random.randrange(10**8):08d}"
        self._state: GameState | None = None
        self.shop: Shop | None = None
        self.finished = False          # 胜利/失败后由界面置位
        self.last_score_display: tuple[int, float] | None = None

    def record_score(self, result) -> None:
        """缓存上一手的筹码/倍率,供左侧信息栏显示。"""
        self.last_score_display = (int(result.total_chips), result.total_mult)

    # ------------------------------------------------------------- 生命周期

    def start_run(self, deck_key: str, stake: int = 1) -> None:
        self._state = GameState(self.seed, deck_key=deck_key, stake=stake)
        self.shop = Shop(self._state)
        self._state.start()

    @property
    def state(self) -> GameState:
        if self._state is None:
            raise RuntimeError("run not started: call start_run() first")
        return self._state

    # ------------------------------------------------------------- 透传属性

    @property
    def phase(self) -> str:
        return self.state.phase

    @property
    def ante(self) -> int:
        return self.state.ante

    @property
    def round_num(self) -> int:
        return self.state.round_num

    @property
    def dollars(self) -> int:
        return self.state.dollars

    @property
    def chips(self) -> int:
        return self.state.chips

    @property
    def hand(self) -> list:
        return self.state.hand

    @property
    def deck(self) -> list:
        return self.state.deck

    @property
    def jokers(self) -> list:
        return self.state.jokers

    @property
    def consumeables(self) -> list:
        return self.state.consumeables

    @property
    def vouchers(self) -> list[str]:
        return self.state.vouchers

    @property
    def tags(self) -> list[str]:
        return self.state.tags

    @property
    def tag_log(self) -> list[str]:
        return self.state.tag_log

    @property
    def hand_levels(self) -> dict:
        return self.state.hand_levels

    @property
    def blind_choices(self) -> list:
        return self.state.blind_choices

    @property
    def the_blind(self):
        return self.state.the_blind

    @property
    def hands_left(self) -> int:
        return self.state.hands_left

    @property
    def discards_left(self) -> int:
        return self.state.discards_left

    @property
    def hand_size(self) -> int:
        return self.state.hand_size

    @property
    def reroll_cost(self) -> int:
        if self.shop is not None:
            return self.shop.reroll_cost
        st = self.state
        return max(0, st.params["reroll_cost"]
                   + st.current_round.get("reroll_cost_increase", 0)
                   + getattr(st, "reroll_cost_delta", 0))

    @property
    def won_run(self) -> bool:
        return self.state.won_run

    @property
    def lost_run(self) -> bool:
        return self.state.lost_run

    @property
    def message(self) -> str:
        return self.state.message

    # run 级统计(Run 信息屏)
    @property
    def skips(self) -> int:
        return self.state.skips

    @property
    def hands_played_total(self) -> int:
        return self.state.hands_played_total

    @property
    def unused_discards(self) -> int:
        return self.state.unused_discards

    @property
    def most_played(self) -> str:
        return self.state.current_round.get("most_played_poker_hand", "")

    @property
    def joker_slots(self) -> int:
        return self.state.params.get("joker_slots", 5)

    @property
    def consumable_slots(self) -> int:
        return self.state.params.get("consumable_slots", 2)

    # ------------------------------------------------------------- 盲注选择

    def blind_display_choices(self) -> list[dict]:
        """blind_choices → 界面展示列表(boss 预览含效果描述)。"""
        return [
            blind_display(o.key, o.chips, o.dollars) | {"kind": o.kind}
            for o in self.state.blind_choices
        ]

    def select_blind(self, choice) -> None:
        self.state.select_blind(choice)

    def skip_blind(self) -> dict:
        return self.state.skip_blind(0)

    def boss_reroll_info(self) -> dict:
        return self.state.boss_reroll_info()

    def reroll_boss(self) -> dict:
        return self.state.reroll_boss()

    # ------------------------------------------------------------- 回合内

    def preview_hand(self, cards) -> tuple[str, list]:
        return get_poker_hand_info(list(cards), self.state.joker_flags)

    def _indices(self, cards) -> list[int]:
        by_id = {id(c): i for i, c in enumerate(self.state.hand)}
        return sorted(by_id[id(c)] for c in cards)

    def play_cards(self, cards) -> dict:
        result = self.state.play_cards(self._indices(cards))
        if result.get("ok"):
            self.record_score(result["score"])
        return result

    def discard_cards(self, cards) -> dict:
        return self.state.discard_cards(self._indices(cards))

    def sort_hand(self, mode: str = "rank") -> None:
        if mode == "rank":
            self.state.hand.sort(key=lambda c: (-RANK_ORDER.index(c.rank),
                                                SUIT_ORDER.get(c.suit, 0)))
        else:
            self.state.hand.sort(key=lambda c: (SUIT_ORDER.get(c.suit, 0),
                                                -RANK_ORDER.index(c.rank)))

    # ------------------------------------------------------------- 结算

    def end_round(self) -> dict:
        """提现。若 ante 8 boss 获胜,phase 变为 'won'。"""
        return self.state.end_round()

    def check_run_end(self) -> None:
        self.state.check_run_end()

    def continue_endless(self) -> None:
        """ante 8 胜利后选择无尽:引擎在 won 分支提前返回,这里手动进商店。"""
        st = self.state
        st.phase = "shop"
        st._enter_shop()

    # ------------------------------------------------------------- 商店

    def shop_items(self) -> list[ShopItem]:
        return self.shop.all_items() if self.shop else []

    def buy(self, index: int) -> dict:
        return self.shop.buy(index)

    def reroll(self) -> dict:
        return self.shop.reroll()

    def sell_joker(self, index: int) -> dict:
        return self.state.sell_joker(index)

    def sell_consumable(self, index: int) -> dict:
        return self.state.sell_consumable(index)

    def advance_from_shop(self) -> None:
        self.state.advance_from_shop()

    # ------------------------------------------------------------- 卡包

    def open_pack(self, pack_key: str) -> dict:
        return self.state.open_pack(pack_key)

    def take_from_pack(self, pack_state, indices) -> dict:
        return self.state.take_from_pack(pack_state, indices)

    def skip_pack(self, pack_state) -> dict:
        return self.state.skip_pack(pack_state)

    # ------------------------------------------------------------- 消耗品

    def consumable_target_range(self, card) -> tuple[int, int] | None:
        """需要手牌目标的消耗品 → (min, max),否则 None。"""
        mn = card.ability.get("min_highlighted") or 0
        mx = card.ability.get("max_highlighted") or 0
        if mn or mx:
            return (mn or mx, mx or mn)
        return None

    def use_consumable(self, index: int, targets=None) -> dict:
        return self.state.use_consumable(index, list(targets or []))
