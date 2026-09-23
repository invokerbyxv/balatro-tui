class Card:
    SUITS = {"Spades": "S", "Hearts": "H", "Clubs": "C", "Diamonds": "D"}
    RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "Jack", "Queen", "King", "Ace"]
    
    def __init__(self, suit, rank):
        self.suit = suit
        self.rank = rank
        self.nominal = self._get_nominal()
        self.color = "red" if suit in ["Hearts", "Diamonds"] else "black"
    
    def _get_nominal(self):
        if self.rank in ["2", "3", "4", "5", "6", "7", "8", "9", "10"]:
            return int(self.rank)
        elif self.rank == "Ace":
            return 14
        else:
            return 10
    
    def __str__(self):
        return f"{self.rank} [{self.SUITS[self.suit]}]"
    
    def __repr__(self):
        return f"Card({self.suit}, {self.rank})"
    
    def __eq__(self, other):
        if isinstance(other, Card):
            return self.suit == other.suit and self.rank == other.rank
        return False
    
    def __hash__(self):
        return hash((self.suit, self.rank))
