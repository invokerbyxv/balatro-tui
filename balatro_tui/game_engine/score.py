"""出牌计分:基础牌型筹码/倍率 + 计分牌点数 + 增强/版本 + 小丑效果。

参照 card.lua:calculate_joker / calculate_card,函数 common_events 的
add_chips/add_mult/apply_to_run 的口径做成简化但可玩版本。
"""

from __future__ import annotations

RANK_CHIPS = {
    "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8,
    "9": 9, "10": 10, "Jack": 10, "Queen": 10, "King": 10, "Ace": 11,
}


def card_base_chips(card) -> int:
    """单张计分牌的筹码基数(点数)。"""
    return RANK_CHIPS.get(card.rank, 0)


def card_enhancement(card):
    """返回卡片增强/版本给 (add_chips, add_mult, x_mult, money, kept)。"""
    add_chips = 0
    add_mult = 0
    x_mult = 1
    money = 0
    enhancement = getattr(card, "enhancement", None) or {}
    if enhancement:
        etype = enhancement.get("name", "")  # m_bonus, m_mult, ...
        cfg = enhancement.get("config") or {}
        if etype in ("", None):
            pass
        elif etype == "m_bonus":
            add_chips += cfg.get("bonus", 30)
        elif etype == "m_mult":
            add_mult += cfg.get("mult", 8)
        elif etype == "m_glass":
            x_mult *= cfg.get("Xmult", 2)
        elif etype == "m_steel":
            x_mult *= cfg.get("h_x_mult", 1.5)
        elif etype == "m_lucky":
            add_mult += cfg.get("mult", 20)
            import random
            if random.random() < cfg.get("p_dollars", 0.15) / 1:
                money += cfg.get("dollars", 20)
        elif etype == "m_gold":
            money += cfg.get("h_dollars", 3)
        elif etype == "m_stone":
            if cfg.get("bonus"):
                add_chips += cfg.get("bonus", 50)
    return add_chips, add_mult, x_mult, money


class ScoreCalculator:
    """根据牌型、计分牌、手牌等级与小丑算这一手的总分。"""

    def __init__(self, hand_key, scoring_cards, level, jokers=None):
        self.hand_key = hand_key
        self.scoring_cards = scoring_cards or []
        self.level = level or {}          # {mult, chips}
        self.jokers = jokers or []

    def calculate(self):
        chips = self.level.get("chips", 0)
        mult = self.level.get("mult", 1)

        # 计分牌基数 + 增强
        for card in self.scoring_cards:
            chips += card_base_chips(card)
            ac, am, xm, _ = card_enhancement(card)
            chips += ac
            mult += am
            mult *= xm

        # 小丑效果(沿用旧 score.py 的分支,按效果叠加)
        for joker in self.jokers:
            chips, mult = self._apply_joker(joker, chips, mult)

        score = chips * mult
        return {
            "hand_key": self.hand_key,
            "chips": chips,
            "mult": mult,
            "score": score,
            "base_chips": self.level.get("chips", 0),
            "base_mult": self.level.get("mult", 1),
        }

    def _apply_joker(self, joker, chips, mult):
        effect = joker.get("effect", "")
        config = joker.get("config") or {}
        extra = config.get("extra")
        if effect == "Mult" and isinstance(extra, (int, float)):
            mult += extra
        elif effect == "Suit Mult" and isinstance(config.get("extra"), dict):
            e = config["extra"]
            if e.get("s_mult"):
                mult += e["s_mult"] if config.get("suit") in _suits_played(self.scoring_cards) else 0
        elif effect == "Type Mult" and config.get("t_mult") and config.get("type"):
            if self.hand_key == config["type"]:
                mult += config["t_mult"]
        elif effect == "Type Chips" and config.get("t_chips") and config.get("type"):
            if self.hand_key == config["type"]:
                chips += config["t_chips"]
        elif effect == "Hand Size Mult" and isinstance(extra, dict):
            if len(self.scoring_cards) >= (extra.get("size") or 4):
                mult *= extra.get("mult") or 1
        elif effect == "Card Chips" and isinstance(extra, dict):
            # 每张特定牌 +chips
            pass
        elif effect == "X_Mult" and isinstance(config.get("Xmult"), (int, float)):
            mult *= config["Xmult"]
        elif effect == "No Discard Mult" and isinstance(extra, dict):
            pass
        return chips, mult


def _suits_played(cards):
    return {c.suit for c in cards}