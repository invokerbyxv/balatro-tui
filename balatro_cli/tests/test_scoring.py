"""Scoring pipeline tests (M2) — arithmetic table-driven."""

from types import SimpleNamespace

from balatro_cli import config
from balatro_cli.engine.card import Card
from balatro_cli.engine.scoring import score_play


def lvl(hand_key, level=1):
    base = config.HAND_LEVELS[hand_key]
    return {
        "chips": base["chips"] + base["s_chips"] * (level - 1),
        "mult": base["mult"] + base["s_mult"] * (level - 1),
        "level": level,
    }


def blind(chips):
    return SimpleNamespace(chips=chips, modify_hand=lambda *a: (a[3], a[4], False),
                           is_defeated=lambda c: c >= chips)


def test_pair_base_10x2():
    res = score_play([Card("8", "S"), Card("8", "H")], [], lvl("Pair"), blind(100))
    assert res.hand_key == "Pair"
    # Pair = 10 chips base, +8+8 card chips => 26 chips, 2 mult => 52
    assert res.total_chips == 26
    assert res.total_mult == 2
    assert res.score == 52


def test_straight_level2_scaling():
    played = [Card("7", "S"), Card("8", "H"), Card("9", "C"), Card("T", "D"), Card("J", "S")]
    res = score_play(played, [], lvl("Straight", 2), blind(1000))
    assert res.hand_key == "Straight"
    # Straight base 30/4, s_chips/s_mult 30/4 => level 2 = 60 chips, 8 mult
    # + card chips 7+8+9+10+10 = 44 => 104 chips, 8 mult => 832
    assert res.total_chips == 104
    assert res.total_mult == 8
    assert res.score == 832


def test_steel_held_xmult():
    held = [Card("A", "S", enhancement="m_steel")]
    res = score_play([Card("8", "S"), Card("8", "H")], held, lvl("Pair"), blind(100))
    assert res.score == 78  # (10+8+8) * 2 * 1.5 = 26*3


def test_glass_xmult():
    played = [Card("8", "S", enhancement="m_glass"), Card("8", "H")]
    res = score_play(played, [], lvl("Pair"), blind(100))
    assert res.score == 104  # 26 chips, mult 2 then X2 => 4 => 26*4


def test_bonus_chips_enhancement():
    played = [Card("8", "S", enhancement="m_bonus"), Card("8", "H")]
    res = score_play(played, [], lvl("Pair"), blind(100))
    assert res.score == 112  # (10 + 8+30 + 8) * 2


def test_polychrome_xmult():
    played = [Card("8", "S", edition="e_polychrome"), Card("8", "H")]
    res = score_play(played, [], lvl("Pair"), blind(100))
    assert res.score == 78  # 26 chips, mult 2 * 1.5 = 3


def test_holo_mult():
    played = [Card("8", "S", edition="e_holo"), Card("8", "H")]
    res = score_play(played, [], lvl("Pair"), blind(100))
    assert res.total_mult == 12  # 2 + 10


def test_foil_chips():
    played = [Card("8", "S", edition="e_foil"), Card("8", "H")]
    res = score_play(played, [], lvl("Pair"), blind(100))
    assert res.total_chips == 76  # 10 + (8+50) + 8


def test_blind_threshold_via_score():
    res = score_play([Card("8", "S"), Card("8", "H")], [], lvl("Pair"), blind(20))
    assert res.score == 52