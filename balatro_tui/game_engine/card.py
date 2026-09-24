class Card:
    SUITS = {"Spades": "S", "Hearts": "H", "Clubs": "C", "Diamonds": "D"}
    RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "Jack", "Queen", "King", "Ace"]
    
    def __init__(self, suit, rank):
        self.suit = suit
        self.rank = rank
        self.nominal = self._get_nominal()
        self.color = "red" if suit in ["Hearts", "Diamonds"] else "black"
    
    SUIT_ORDER = {"Spades": 0, "Hearts": 1, "Clubs": 2, "Diamonds": 3}

    def _get_nominal(self):
        if self.rank in ["2", "3", "4", "5", "6", "7", "8", "9", "10"]:
            return int(self.rank)
        elif self.rank == "Ace":
            return 14
        else:
            return 10

    def suit_order(self) -> int:
        return self.SUIT_ORDER.get(self.suit, 0)

    def display(self) -> str:
        """简短显示字符串,如 ♠A / ♥10。"""
        from ..utils.helpers import get_card_suit_symbol
        sym = get_card_suit_symbol(self.suit)
        rank = self.rank if self.rank != "10" else "10"
        return f"{sym}{rank[0] if rank != '10' else '10'}"
    
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
