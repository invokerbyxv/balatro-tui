"""M5: shop economy + joker scoring + consumable application."""

import pytest

from balatro_cli.engine.game_state import GameState
from balatro_cli.engine.shop import Shop


def _game(seed="s"):
    g = GameState(seed)
    g.start()
    return g


def test_shop_refills_four_slots():
    g = _game()
    s = Shop(g)
    s.refill()
    assert len(s.items) == 4
    kinds = [it.kind for it in s.items if it]
    assert "booster" in kinds
    assert ("joker" in kinds) or ("consumable" in kinds)


def test_buy_joker_adds_to_state():
    g = _game()
    g.dollars = 500
    s = Shop(g)
    s.refill()
    joker = next((it for it in s.items if it and it.kind == "joker"), None)
    if not joker:
        pytest.skip("no joker in this shop pool")
    before = len(g.jokers)
    r = s.buy(joker.index)
    assert r["ok"]
    assert len(g.jokers) == before + 1
    assert g.jokers[-1] == joker.key


def test_buy_without_money_fails():
    g = _game()
    g.dollars = 0
    s = Shop(g)
    s.refill()
    joker = next((it for it in s.items if it and it.kind == "joker"), None)
    if not joker:
        pytest.skip("no joker in this shop pool")
    r = s.buy(joker.index)
    assert not r["ok"]
    assert r["error"] == "not enough money"


def test_reroll_escalates_cost():
    g = _game()
    g.dollars = 500
    s = Shop(g)
    s.refill()
    before = s.reroll_cost
    r = s.reroll()
    assert r["ok"]
    assert s.reroll_cost == before + 1


def test_sell_refunds():
    g = _game()
    g.dollars = 0
    g.jokers = ["j_joker"]
    s = Shop(g)
    r = s.sell("jokers", 0)
    assert r["ok"]
    assert g.dollars > 0


def test_joker_scoring_integration():
    """A bought j_joker (+4 mult) raises the final score."""
    from balatro_cli.engine.card import Card
    from balatro_cli.engine.scoring import score_play
    from balatro_cli.engine.blind import Blind

    g = _game()
    g.the_blind = Blind("bl_small", {}, 1, 1)
    level = g.hand_levels["Pair"]
    c1, c2 = Card("8", "S"), Card("8", "H")

    base = score_play([c1, c2], [], level, g.the_blind, jokers=[], flags=g.joker_flags)
    boosted = score_play([c1, c2], [], level, g.the_blind, jokers=["j_joker"], flags=g.joker_flags)
    assert boosted.total_mult == base.total_mult + 4
    assert boosted.score > base.score


def test_planet_levels_up_hand():
    from balatro_cli.engine import consumable
    g = _game()
    before = g.hand_levels["Pair"]["level"]
    r = consumable.use_consumable(g, "c_mercury")  # Mercury = Pair planet
    assert r["ok"] and r["kind"] == "planet"
    assert g.hand_levels["Pair"]["level"] == before + 1


def test_tarot_enhances_card():
    from balatro_cli.engine import consumable
    from balatro_cli.engine.card import Card
    g = _game()
    card = Card("A", "S")
    r = consumable.use_consumable(g, "c_magician", target_cards=[card])
    assert r["ok"]
    assert card.enhancement == "m_lucky"