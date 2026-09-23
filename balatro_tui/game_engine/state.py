class GameState:
    def __init__(self):
        self.deck = []
        self.hand = []
        self.jokers = []
        self.vouchers = []
        self.consumables = {"tarots": [], "planets": []}
        
        self.chips = 0
        self.mult = 1
        self.dollars = 4
        self.play_chances = 4
        self.discard_chances = 3
        
        self.current_blind = None
        self.ante = 1
        self.round = 1
        
        self.hands_played = 0
        self.rounds_won = 0
    
    def add_consumable(self, consumable_type, consumable_data):
        if consumable_type in self.consumables:
            self.consumables[consumable_type].append(consumable_data)
    
    def use_consumable(self, consumable_type, index):
        if consumable_type in self.consumables and index < len(self.consumables[consumable_type]):
            return self.consumables[consumable_type].pop(index)
        return None
    
    def create_deck(self, deck_type="standard"):
        from .card import Card
        suits = ["Spades", "Hearts", "Clubs", "Diamonds"]
        ranks = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "Jack", "Queen", "King", "Ace"]
        
        self.deck = [Card(suit, rank) for suit in suits for rank in ranks]
        
        if deck_type == "checkered":
            self.deck = [c for c in self.deck if c.suit in ["Spades", "Hearts"]]
    
    def draw_hand(self, size=8):
        import random
        if len(self.deck) < size:
            return
        
        drawn = random.sample(self.deck, size)
        self.hand.extend(drawn)
        self.deck = [c for c in self.deck if c not in drawn]
        
        self.hand.sort(key=lambda c: c.nominal, reverse=True)
    
    def play_hand(self, cards_to_play):
        from .hand import HandEvaluator
        from .score import ScoreCalculator
        
        hand_evaluator = HandEvaluator(cards_to_play)
        hand_result = hand_evaluator.evaluate()
        
        if not hand_result:
            return None
        
        hand_type, hand_stats = hand_result
        
        calculator = ScoreCalculator(hand_stats, self.jokers)
        score_data = calculator.calculate()
        
        self.hands_played += 1
        
        return {
            "hand_type": hand_type,
            "stats": hand_stats,
            "score": score_data
        }
    
    def discard_cards(self, cards_to_discard):
        for card in cards_to_discard:
            if card in self.hand:
                self.hand.remove(card)
    
    def add_joker(self, joker):
        self.jokers.append(joker)
    
    def reset_round(self):
        self.play_chances = 4
        self.discard_chances = 3
        self.hand.clear()
