"""牌型识别。返回 (hand_key, [计分牌]),供打分时用 state.hand_levels 取基础值。

牌型键与 game.lua P_CENTERS 里的 hand 名一致:
Flush Five / Flush House / Five of a Kind / Straight Flush / Four of a Kind /
Full House / Flush / Straight / Three of a Kind / Two Pair / Pair / High Card
"""

from __future__ import annotations

from collections import Counter

RANK_ORDER = {
    "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9, "10": 10,
    "Jack": 11, "Queen": 12, "King": 13, "Ace": 14,
}


class HandEvaluator:
    def __init__(self, cards):
        self.cards = sorted(cards, key=lambda c: c.nominal, reverse=True)

    def evaluate(self):
        """返回 ('hand_key', scoring_cards) 或 (None, [])(空/无有效)。"""
        if not self.cards:
            return None, []
        cards = self.cards

        # 只取点数(不去重)判断同点数
        rank_counts = Counter(c.rank for c in cards)
        suit_counts = Counter(c.suit for c in cards)

        # 同点数牌(用于 Flush Five / Five of a Kind)
        five_count_rank = None
        for rank, cnt in rank_counts.items():
            if cnt >= 5:
                five_count_rank = rank
        # 同花色牌(>=5)
        flush_suit = None
        for suit, cnt in suit_counts.items():
            if cnt >= 5:
                flush_suit = suit

        is_flush = flush_suit is not None
        is_straight, straight_ranks = self._straight()
        # 头尾判断(2-6)A-5
        if is_flush and is_straight:
            straight_flush_key = self._straight_flush_key(cards, flush_suit)
            if straight_flush_key:
                return straight_flush_key, [c for c in cards if c.suit == flush_suit]

        if flush_suit is not None and five_count_rank is not None:
            # 同花五条:5 张同花色且同点数
            return ("Flush Five",
                    [c for c in cards if c.suit == flush_suit and c.rank == five_count_rank][:5])

        if flush_suit is not None:
            return ("Flush", [c for c in cards if c.suit == flush_suit][:5])

        if is_straight:
            return ("Straight", straight_ranks)

        if five_count_rank is not None:
            return ("Five of a Kind",
                    [c for c in cards if c.rank == five_count_rank][:5])

        counts = sorted(rank_counts.values(), reverse=True)
        if counts[0] == 4 and counts[1] == 1:
            four = [c for c in cards if c.rank == next(k for k, v in rank_counts.items() if v == 4)]
            return ("Four of a Kind", four[:4])
        if counts[0] == 3 and len(counts) > 1 and counts[1] == 2:
            three = [c for c in cards if c.rank == next(k for k, v in rank_counts.items() if v == 3)]
            return ("Full House", three[:3])
        if counts[0] == 3:
            three = [c for c in cards if c.rank == next(k for k, v in rank_counts.items() if v == 3)]
            return ("Three of a Kind", three[:3])
        pairs = [k for k, v in rank_counts.items() if v == 2]
        if len(pairs) == 2:
            pair_cards = [c for c in cards if c.rank in pairs][:4]
            return ("Two Pair", pair_cards)
        if len(pairs) == 1:
            pair_cards = [c for c in cards if c.rank == pairs[0]]
            return ("Pair", pair_cards[:2])
        high = max(cards, key=lambda c: c.nominal)
        return ("High Card", [high])

    def _straight(self):
        """返回 (是否顺子, 顺子的 5 张牌)。处理 A-2-3-4-5。"""
        vals = sorted({RANK_ORDER[c.rank] for c in self.cards}, reverse=True)
        if len(vals) < 5:
            return False, []
        for i in range(len(vals) - 4):
            run = vals[i:i + 5]
            if run[0] - run[4] == 4:
                return True, self._cards_for_ranks(run)
        # A-5 顺子:A=14 再当作 1
        if {14, 5, 4, 3, 2} <= set(vals):
            return True, self._cards_for_ranks([5, 4, 3, 2, 1])
        return False, []

    def _cards_for_ranks(self, ranks):
        """为给定点数序列取对应牌(Ace 用 14 表示)。"""
        out = []
        for r in ranks:
            if r == 1:
                out.append(max([c for c in self.cards if c.rank == "Ace"],
                               key=lambda c: c.nominal))
                continue
            rank_name = {2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7",
                         8: "8", 9: "9", 10: "10", 11: "Jack", 12: "Queen",
                         13: "King", 14: "Ace"}[r]
            out.append([c for c in self.cards if c.rank == rank_name][0])
        return out

    def _straight_flush_key(self, cards, suit):
        """同花 + 顺子 → Straight Flush 或 Royal Flush(用同一键,暂未区分)。"""
        return ("Straight Flush")