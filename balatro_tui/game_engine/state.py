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

# 牌组 def,依 balatro_source_code 的 game.lua P_CENTERS.b_* config 与
# back.lua:apply_to_run 口径(即每个卡组的真实效果)。
_BACK_CONFIGS = {
    "b_red": {"discards": 1},
    "b_blue": {"hands": 1},
    "b_yellow": {"dollars": 10},
    "b_green": {"extra_hand_bonus": 2, "extra_discard_bonus": 1, "no_interest": True},
    "b_black": {"hands": -1, "joker_slot": 1},
    "b_magic": {"voucher": "v_crystal_ball", "consumables": ["c_fool", "c_fool"]},
    "b_nebula": {"voucher": "v_telescope", "consumable_slot": -1},
    "b_ghost": {"spectral_rate": 2, "consumables": ["c_hex"]},
    "b_abandoned": {"remove_faces": True},
    "b_checkered": {"checkered": True},
    "b_zodiac": {"vouchers": ["v_tarot_merchant", "v_planet_merchant", "v_overstock_norm"]},
    "b_painted": {"hand_size": 2, "joker_slot": -1},
    "b_anaglyph": {},
    "b_plasma": {"ante_scaling": 2},
    "b_erratic": {"randomize_rank_suit": True},
}

# 数值参数名 -> 起始参数键(部分 def 键名与参数名不同)
_param_map = {
    "hands": "hands",
    "discards": "discards",
    "dollars": "dollars",
    "hand_size": "hand_size",
    "joker_slot": "joker_slots",
    "consumable_slot": "consumables",
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
        self.money_per_hand = 0        # 绿牌:每手奖励(extra_hand_bonus)
        self.money_per_discard = 0     # 绿牌:每弃牌奖励(extra_discard_bonus)
        self.spectral_rate = None      # 幽灵:幻灵牌出现率(当前仅记录,供后续商店使用)
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

        # 标签:跳过盲注时获得的待用标签(HUD 标签条)
        self.tags: list[str] = []

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
        self.back_mods = dict(_BACK_CONFIGS.get(deck_key, {}))
        self.params = dict(DEFAULT_PARAMS)
        # 数值类:累加进起始参数(discards/hands/dollars/hand_size/joker_slot/consumable_slot)
        for k, v in self.back_mods.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool) and k in _param_map:
                self.params[_param_map[k]] += v
        # plasma:直接赋值 ante_scaling
        self.ante_scaling = self.back_mods.get("ante_scaling", self.params["ante_scaling"])
        # 绿牌:无利息 + 每手/弃牌奖金
        self.no_interest = bool(self.back_mods.get("no_interest"))
        self.money_per_hand = self.back_mods.get("extra_hand_bonus", 0)
        self.money_per_discard = self.back_mods.get("extra_discard_bonus", 0)
        # 幽灵:幻灵出现率起点
        self.spectral_rate = self.back_mods.get("spectral_rate")
        self.create_deck(self.deck_key)
        # 初始金钱=起始参数
        self.dollars = self.params["dollars"]
        self.reset_round()
        # 首发优惠券/消耗品(魔术/星云/幽灵/占星)
        self._apply_starting_boons()

    def _apply_starting_boons(self):
        """按卡组 config 填入手局你实际持有的优惠券与消耗品。"""
        for v in self.back_mods.get("vouchers") or []:
            self._give_voucher(v)
        v = self.back_mods.get("voucher")
        if v:
            self._give_voucher(v)
        for ck in self.back_mods.get("consumables") or []:
            self._give_consumable(ck)

    def _give_voucher(self, key: str) -> None:
        if key and key not in self.vouchers:
            self.vouchers.append(key)

    def _give_consumable(self, key: str) -> None:
        from ..utils.collection_data import consume_set_of, consumable_item
        set_name = consume_set_of(key)
        bucket = {"Tarot": "tarots", "Planet": "planets", "Spectral": "spectrals"}.get(set_name)
        if bucket:
            self.consumables.setdefault(bucket, []).append(consumable_item(set_name, key))

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
        if self.back_mods.get("randomize_rank_suit"):
            # 芜杂:52 张随机花色/点数(随机牌堆)
            cards = [Card(random.choice(suits), random.choice(ranks)) for _ in range(52)]
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
        if self.deck_key == "b_plasma":
            # 等离子:最终结算把筹码与倍率拉平为二者均值
            half = (calc["chips"] + calc["mult"]) // 2
            calc["chips"] = half
            calc["mult"] = half
            calc["score"] = half * half
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
        # 拓碑:击败 boss 盲注时获得一个双倍标签(back.lua trigger_effect)
        if (self.deck_key == "b_anaglyph" and self.won_blind
                and self.current_blind and self.current_blind.is_boss):
            self.add_tag("tag_double")
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
        bonus_hand = self.money_per_hand * self.hands_played      # 绿牌:每手 +2
        bonus_discard = self.money_per_discard * self.discards_used  # 绿牌:每弃牌 +1
        if self.no_interest:
            dollars = 0
        else:
            dollars = min(self.dollars // 5, self.interest_cap // 5) * self.interest_amount
        return {
            "blind_reward": blind_reward,
            "hands_money": hands_money,
            "hand_bonus": bonus_hand,
            "discard_bonus": bonus_discard,
            "interest": dollars,
            "total": blind_reward + hands_money + bonus_hand + bonus_discard + dollars,
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

    # ------------------------------------------------------------- 标签

    def add_tag(self, key: str) -> None:
        """记录一个待用标签(跳盲注/双倍标签等来源)。"""
        if key not in self.tags:
            self.tags.append(key)

    def remove_tag(self, index: int | None = None) -> str | None:
        """取走一个标签;缺省取队首。返回其 key,供触发效果。"""
        if not self.tags:
            return None
        if index is None:
            index = 0
        if 0 <= index < len(self.tags):
            return self.tags.pop(index)
        return None

    def give_skip_tag(self) -> str | None:
        """跳过盲注时奖励一个符合当前底注可获取的随机标签。"""
        tags = load_definitions().get("Tag") or {}
        pool = [k for k, e in tags.items()
                if isinstance(e, dict) and self.ante >= (e.get("min_ante") or 1)]
        if not pool:
            return None
        key = random.choice(pool)
        self.add_tag(key)
        return key

    def add_consumable(self, consumable_type, data):
        self.consumables.setdefault(consumable_type, []).append(data)

    def use_consumable(self, consumable_type, index):
        lst = self.consumables.get(consumable_type, [])
        if index < len(lst):
            return lst.pop(index)
        return None