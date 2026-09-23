from collections import Counter

class HandEvaluator:
    def __init__(self, cards):
        self.cards = sorted(cards, key=lambda c: c.nominal, reverse=True)
    
    def evaluate(self):
        if not self.cards:
            return None
        
        counts = Counter(c.rank for c in self.cards)
        suits = Counter(c.suit for c in self.cards)
        
        is_flush = any(count >= 5 for count in suits.values())
        
        ranks = [c.rank for c in self.cards]
        values = [c.nominal for c in self.cards]
        
        is_straight = self._check_straight(values)
        is_five_of_a_kind = 5 in counts.values()
        
        if is_five_of_a_kind:
            return ("five_of_a_kind", self._get_hand_stats("five_of_a_kind"))
        elif is_flush and is_straight:
            return ("straight_flush", self._get_hand_stats("straight_flush"))
        elif is_flush:
            return ("flush", self._get_hand_stats("flush"))
        elif is_straight:
            return ("straight", self._get_hand_stats("straight"))
        
        four_of_a_kind = any(count == 4 for count in counts.values())
        three_of_a_kind = any(count == 3 for count in counts.values())
        pairs = sum(1 for count in counts.values() if count == 2)
        
        if four_of_a_kind:
            return ("four_of_a_kind", self._get_hand_stats("four_of_a_kind"))
        elif three_of_a_kind and pairs >= 1:
            return ("full_house", self._get_hand_stats("full_house"))
        elif three_of_a_kind:
            return ("three_of_a_kind", self._get_hand_stats("three_of_a_kind"))
        elif pairs >= 2:
            return ("two_pair", self._get_hand_stats("two_pair"))
        elif pairs == 1:
            return ("pair", self._get_hand_stats("pair"))
        
        high_card = max(self.cards, key=lambda c: c.nominal)
        return ("high_card", {
            "name": "高牌",
            "chips": 5,
            "mult": 1,
            "rank": 1,
            "cards": [high_card]
        })
    
    def _check_straight(self, values):
        unique_values = sorted(set(values), reverse=True)
        if len(unique_values) < 5:
            return False
        
        for i in range(len(unique_values) - 4):
            if unique_values[i] - unique_values[i + 4] == 4:
                return True
        
        if [14, 5, 4, 3, 2] in [unique_values[i:i+5] for i in range(len(unique_values)-4)]:
            return True
        
        return False
    
    def _get_hand_stats(self, hand_type):
        from ..data.hand_types import HAND_TYPES
        for hand in HAND_TYPES:
            if hand["id"] == hand_type:
                return dict(hand)
        return {"name": hand_type, "chips": 0, "mult": 0, "rank": 0}
