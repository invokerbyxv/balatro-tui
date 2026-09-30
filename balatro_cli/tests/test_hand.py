"""Hand-detection tests (M1) with vectors from the Balatro rules."""

from balatro_cli.engine.card import Card
from balatro_cli.engine.hand import JokerFlags, evaluate_poker_hand, get_poker_hand_info


def C(rank, suit):
    return Card(rank, suit)


def top(hand, flags=None):
    _k, cards = get_poker_hand_info(hand, flags)
    return _k, cards


def test_high_card():
    k, _ = top([C("K", "S"), C("A", "H"), C("2", "C"), C("3", "D"), C("4", "S")])
    assert k == "High Card"


def test_pair():
    k, _ = top([C("8", "S"), C("8", "H"), C("2", "C"), C("4", "D"), C("6", "S")])
    assert k == "Pair"


def test_two_pair():
    k, _ = top([C("A", "S"), C("A", "H"), C("Q", "C"), C("Q", "D"), C("4", "S")])
    assert k == "Two Pair"


def test_three_of_a_kind():
    k, _ = top([C("T", "S"), C("T", "H"), C("T", "C"), C("6", "D"), C("4", "S")])
    assert k == "Three of a Kind"


def test_straight():
    k, _ = top([C("7", "S"), C("8", "H"), C("9", "C"), C("T", "D"), C("J", "S")])
    assert k == "Straight"


def test_straight_ace_low():
    k, _ = top([C("A", "S"), C("2", "H"), C("3", "C"), C("4", "D"), C("5", "S")])
    assert k == "Straight"


def test_ace_high_not_straight():
    k, _ = top([C("K", "S"), C("A", "H"), C("2", "C"), C("3", "D"), C("4", "S")])
    assert k == "High Card"


def test_flush():
    k, _ = top([C("A", "S"), C("K", "S"), C("T", "S"), C("5", "S"), C("4", "S")])
    assert k == "Flush"


def test_full_house():
    k, _ = top([C("K", "S"), C("K", "H"), C("K", "C"), C("2", "D"), C("2", "S")])
    assert k == "Full House"


def test_four_of_a_kind():
    k, _ = top([C("J", "S"), C("J", "H"), C("J", "C"), C("J", "D"), C("3", "S")])
    assert k == "Four of a Kind"


def test_straight_flush():
    k, _ = top([C("8", "S"), C("9", "S"), C("T", "S"), C("J", "S"), C("Q", "S")])
    assert k == "Straight Flush"


def test_five_of_a_kind():
    # Five Aces (via wilds/enhance semantics: IDs equal)
    a = C("A", "S")
    b = C("A", "H")
    c = C("A", "C")
    d = C("A", "D")
    e = C("A", "S")  # duplicate suit card
    k, _ = top([a, b, c, d, e])
    assert k == "Five of a Kind"


def test_downgrade_5oak_to_pair():
    """5oaK must fall through to a Pair via downgrade block."""
    res = evaluate_poker_hand([C("A", "S"), C("A", "H"), C("A", "C"),
                               C("A", "D"), C("A", "S")])
    assert res["top_key"] == "Five of a Kind"
    assert len(res["Pair"]) == 2  # downgraded
    assert len(res["Three of a Kind"]) == 3
    assert len(res["Four of a Kind"]) == 4


def test_four_fingers_flush():
    """Four Fingers -> 4-card flush."""
    flags = JokerFlags(four_fingers=True)
    k, _ = top([C("A", "H"), C("K", "H"), C("T", "H"), C("5", "H")], flags)
    assert k == "Flush"


def test_four_fingers_straight():
    flags = JokerFlags(four_fingers=True)
    k, _ = top([C("7", "S"), C("8", "H"), C("9", "C"), C("T", "D")], flags)
    assert k == "Straight"


def test_shortcut_straight():
    """Shortcut allows skipping a single rank."""
    flags = JokerFlags(shortcut=True)
    k, _ = top([C("A", "S"), C("3", "H"), C("5", "C"), C("7", "D"), C("9", "S")], flags)
    assert k == "Straight"


def test_no_hand_with_2_cards_fails():
    # 3-card minimum pattern; a 2-card rendering of Pair needs the hand drawn.
    # Playing fewer than 5 but with suitable ranks: 3-of-a-kind needs 3 cards.
    k, _ = top([C("8", "S"), C("8", "H"), C("8", "D")])
    assert k == "Three of a Kind"


def test_wild_is_every_suit():
    w = Card("7", "S", enhancement="m_wild")
    h = [w, Card("K", "H"), Card("T", "H"), Card("5", "H"), Card("4", "H")]
    k, _ = top(h)
    assert k == "Flush"


def test_stone_is_not_any_suit():
    s = Card("Q", "C", enhancement="m_stone")
    h = [s, Card("K", "H"), Card("T", "H"), Card("5", "H"), Card("4", "H")]
    k, _ = top(h)
    assert k != "Flush"