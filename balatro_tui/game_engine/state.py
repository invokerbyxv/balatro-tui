"""对局状态:牌组、盲注、回合、计分、经济、商店。

单一真实来源,供各对局界面读取与刷新。
参考 balatro_source_code 的 game.lua / blind.lua / functions/*.lua 口径。
"""

from __future__ import annotations

import random

from .hand import HandEvaluator
from .score import ScoreCalculator
from ..utils.lua_data import load_definitions, get_config

DEFAULT_PARAMS = {
    "dollars": 4,
    "hand_size": 8,
    "discards": 3,
    "hands": 4,
    "reroll_cost": 5,
    "joker_slots": 5,
    "consumables": 2,
    "ante_scaling": 1,
}

# 牌组 def 对起始参数的叠加(参照 P_BACKS)
_BACK_ADJUST = {
    "b_red": {"discards": 1},
    "b_blue": {"hands": 1},
    "b_yellow": {"dollars": 10},
    "b_green": {"no_interest": True, "extra_hand_bonus": 2},
    "b_black": {"hands": -1, "joker_slots": 1},
    "b_magic": {},
    "b_nebula": {},
    "b_ghost": {},
    "b_abandoned": {"remove_faces": True},
    "b_checkered": {"checkered": True},
    "b_zodiac": {},
    "b_painted": {"hand_size": 2, "joker_slots": -1},
    "b_anaglyph": {},
    "b_plasma": {"ante_scaling": 2},
    "b_erratic": {},
}


class GameState:
    def __init__(self):
        self.deck_key = "b_red"
        self.stake = 1
        self.params = dict(DEFAULT_PARAMS)
        self.back_mods: dict = {}

        self.deck: list = []
        self.hand: list = []

        self.jokers: list[dict] = []
        self.vouchers: list[str] = []
        self.consumables = {"tarots": [], "planets": [], "spectrals": []}

        # 经济
        self.dollars = 0
        self.interest_cap = 25
        self.interest_amount = 1
        self.inflation = 0
        self.no_interest = False
        self.reroll_cost = self.params["reroll_cost"]

        # 底注 / 盲注
        self.ante = 1
        self.blind_in_ante = 1          # 1=小 2=大 3=boss
        self.ante_scaling = 1
        self.current_blind = None
        self.used_bosses: list[str] = []

        # 回合
        self.hands_left = self.params["hands"]
        self.discards_left = self.params["discards"]
        self.hands_played = 0
        self.discards_used = 0
        self.score_chips = 0
        # 每手实时计算
        self.last_calc = None

        self.run_over = False
        self.won_blind = False

        # 商店
        self.shop_jokers: list[dict] = []

        self._load_hand_levels()

    # ------------------------------------------------------------- 初始化

    def _load_hand_levels(self):
        hands = load_definitions().get("_hands") or {}
        self.hand_levels = {}
        for key, h in hands.items():
            self.hand_levels[key] = {
                "chips": h.get("s_chips", 0),
                "mult": h.get("s_mult", 1),
                "l_chips": h.get("l_chips", 0),
                "l_mult": h.get("l_mult", 0),
                "level": h.get("level", 1),
            }

    def level_of(self, hand_key: str) -> dict:
        lv = self.hand_levels.get(hand_key, {"chips": 0, "mult": 0, "level": 1, "l_chips": 0, "l_mult": 0})
        return {
            "chips": lv["chips"] + lv.get("l_chips", 0) * (lv.get("level", 1) - 1),
            "mult": lv["mult"] + lv.get("l_mult", 0) * (lv.get("level", 1) - 1),
            "level": lv.get("level", 1),
        }

    def set_deck(self, deck_key: str):
        self.deck_key = deck_key
        self.back_mods = dict(_BACK_ADJUST.get(deck_key, {}))
        self.params = dict(DEFAULT_PARAMS)
        for k, v in self.back_mods.items():
            if k in ("no_interest", "checkered", "remove_faces"):
                continue
            if k in self.params:
                self.params[k] += v
        self.ante_scaling = self.params["ante_scaling"]
        single = self.back_mods.get("ante_scaling")
        if isinstance(single, int) and single:
            self.ante_scaling = single
        self.create_deck(self.deck_key)
        # 初始金钱=起始参数
        self.dollars = self.params["dollars"]
        self.reset_round()

    def create_deck(self, deck_type="standard"):
        from .card import Card
        suits = ["Spades", "Hearts", "Clubs", "Diamonds"]
        ranks = ["2", "3", "4", "5", "6", "7", "8", "9", "10",
                 "Jack", "Queen", "King", "Ace"]
        cards = [Card(suit, rank) for suit in suits for rank in ranks]
        if self.back_mods.get("checkered"):
            cards = [c for c in cards if c.suit in ("Spades", "Hearts")]
        if self.back_mods.get("remove_faces"):
            cards = [c for c in cards if c.rank not in ("Jack", "Queen", "King")]
        random.shuffle(cards)
        self.deck = cards

    # ------------------------------------------------------------- 回合

    def reset_round(self):
        self.hands_left = self.params["hands"]
        self.discards_left = self.params["discards"]
        self.hands_played = 0
        self.discards_used = 0
        self.score_chips = 0
        self.last_calc = None
        self.hand.clear()
        self.reroll_cost = self.params["reroll_cost"] + self.inflation

    def draw_hand(self, size: int | None = None):
        size = size if size is not None else self.params["hand_size"]
        missing = size - len(self.hand)
        if missing <= 0 or not self.deck:
            return
        picked = random.sample(self.deck, min(missing, len(self.deck)))
        for c in picked:
            self.deck.remove(c)
        self.hand.extend(picked)
        self.hand.sort(key=lambda c: (c.suit_order(), -c.nominal))

    # ------------------------------------------------------------- 盲注

    def start_blind(self, blind) -> None:
        """开打某个盲注:记录之,重置得分,抽满手牌。"""
        self.current_blind = blind
        self.score_chips = 0
        self.hands_left = self.params["hands"]
        self.discards_left = self.params["discards"]
        self.hands_played = 0
        self.discards_used = 0
        self.last_calc = None
        self.hand.clear()
        self.draw_hand()

    def build_blind_choices(self) -> list:
        """返回本底注可选的三个盲注(small/big/boss)。"""
        from .blind import small_blind, big_blind, pick_boss, get_blind_amount
        base = get_blind_amount(self.ante, self.ante_scaling)
        small = small_blind(self.ante, self.ante_scaling)
        big = big_blind(self.ante, self.ante_scaling)
        boss = pick_boss(self.ante, self.ante_scaling, self.used_bosses)
        # 依当前所处的盲注位置给出「可选」与「预告」
        order = {
            1: (small, big, boss),
            2: (big, boss, None),
            3: (boss, None, None),
        }
        return list(order.get(self.blind_in_ante, (small, big, boss)))

    def advance_ante_blind(self):
        """打赢当前盲注后推进。boss 击败后 ante+1 回到小盲。"""
        if self.current_blind and self.current_blind.is_boss:
            self.used_bosses.append(self.current_blind.key)
            self.ante += 1
        self.blind_in_ante += 1
        if self.blind_in_ante > 3:
            self.blind_in_ante = 1
        if self.ante > 8:
            self.run_over = True

    # ------------------------------------------------------------- 出牌/弃牌

    def play_cards(self, selected):
        """打出选中的牌,返回本手计分 dict(或 None)。"""
        if not selected or self.hands_left <= 0:
            return None
        evaluator = HandEvaluator(selected)
        hand_key, scoring = evaluator.evaluate()
        if hand_key is None:
            return None
        level = self.level_of(hand_key)
        calc = ScoreCalculator(hand_key, scoring, level, self.jokers).calculate()
        self.score_chips += calc["score"]
        self.hands_left -= 1
        self.hands_played += 1
        self.last_calc = calc
        # 从手牌移除打出的牌,补抽
        for c in selected:
            if c in self.hand:
                self.hand.remove(c)
        self.draw_hand()
        self.won_blind = self.score_chips >= (self.current_blind.target if self.current_blind else 1)
        # 记录该牌型使用次数
        self.hand_levels.setdefault(hand_key, {}).setdefault("level", 1)
        return calc

    def discard_cards(self, selected):
        """弃掉选中的牌,消耗一次弃牌,补抽。"""
        if not selected or self.discards_left <= 0:
            return False
        for c in selected:
            if c in self.hand:
                self.hand.remove(c)
        self.discards_left -= 1
        self.discards_used += 1
        self.draw_hand()
        return True

    @property
    def blind_target(self) -> int:
        return self.current_blind.target if self.current_blind else 0

    @property
    def round_lost(self) -> bool:
        return self.hands_left <= 0 and self.score_chips < self.blind_target and not self.won_blind

    # ------------------------------------------------------------- 经济

    def calculate_round_money(self) -> dict:
        """结算金额:盲注奖励 + 剩余出牌×1 + 利息。"""
        blind_reward = self.current_blind.dollars if self.current_blind and self.won_blind else 0
        hands_money = max(self.hands_left, 0) * 1
        dollars = 0 if self.no_interest else min(self.dollars // 5,
                                                 self.interest_cap // 5) * self.interest_amount
        if self.no_interest:
            dollars = 0
        return {
            "blind_reward": blind_reward,
            "hands_money": hands_money,
            "interest": dollars,
            "total": blind_reward + hands_money + dollars,
        }

    def collect_money(self) -> dict:
        money = self.calculate_round_money()
        self.dollars += money["total"]
        return money

    def can_afford(self, cost: int) -> bool:
        return cost <= self.dollars

    def spend(self, cost: int) -> bool:
        if not self.can_afford(cost):
            return False
        self.dollars -= cost
        return True

    # ------------------------------------------------------------- 商店

    def generate_shop(self, count=2):
        from ..utils.collection_data import joker_item
        defs = load_definitions().get("Joker") or {}
        pool = list(defs.keys())
        pick = random.sample(pool, min(count, len(pool))) if len(pool) >= count else pool
        self.shop_jokers = [joker_item(k) for k in pick]

    def reroll_shop(self) -> bool:
        if not self.spend(self.reroll_cost):
            return False
        self.reroll_cost += 1
        self.inflation += 0
        self.generate_shop()
        return True

    def buy_joker(self, index: int) -> bool:
        if not (0 <= index < len(self.shop_jokers)):
            return False
        item = self.shop_jokers[index]
        if not self.spend(item["cost"]):
            return False
        self.shop_jokers.pop(index)
        self.jokers.append(item)
        return True

    def add_consumable(self, consumable_type, data):
        self.consumables.setdefault(consumable_type, []).append(data)

    def use_consumable(self, consumable_type, index):
        lst = self.consumables.get(consumable_type, [])
        if index < len(lst):
            return lst.pop(index)
        return None