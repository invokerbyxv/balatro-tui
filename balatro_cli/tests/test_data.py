"""Data-extraction and constants tests (M0 / M3) against committed assets."""

from balatro_cli import config
from balatro_cli.data import loader
from balatro_cli.engine.blind import get_blind_amount


def test_greedy_joker_data():
    j = loader.centers()["j_greedy_joker"]
    assert j["cost"] == 5
    assert j["set"] == "Joker"
    assert j["rarity"] == 1
    assert j["config"]["extra"]["s_mult"] == 3
    assert j["config"]["extra"]["suit"] == "Diamonds"


def test_joker_count_pins_parse_completeness():
    jokers = [v for v in loader.centers().values()
              if isinstance(v, dict) and v.get("set") == "Joker"]
    assert len(jokers) == 150  # catches truncation in the parser


def test_all_12_hands_present():
    assert set(config.HAND_LEVELS) == {
        "Flush Five", "Flush House", "Five of a Kind", "Straight Flush",
        "Four of a Kind", "Full House", "Flush", "Straight",
        "Three of a Kind", "Two Pair", "Pair", "High Card",
    }


def test_flush_base_level():
    assert config.HAND_LEVELS["Flush"]["mult"] == 4
    assert config.HAND_LEVELS["Flush"]["chips"] == 35


def test_blinds_data():
    b = loader.blinds()
    assert b["bl_small"]["dollars"] == 3
    assert b["bl_wall"]["mult"] == 4
    assert b["bl_wall"]["boss"]["min"] == 2


def test_blind_amount_table():
    assert get_blind_amount(1) == 300
    assert get_blind_amount(2) == 800
    assert get_blind_amount(8) == 50000


def test_blind_amount_endless_stable():
    assert get_blind_amount(9) > 50000
    assert get_blind_amount(12) > get_blind_amount(11)


def test_pools_membership():
    pools = loader.pools()
    assert pools["Joker"][0]["key"] == "j_joker"  # ordered by `order`
    assert "j_greedy_joker" in {j["key"] for j in pools["Joker"]}
    assert {"key"} <= set(pools["Joker"][0])


def test_interest_math():
    from balatro_cli.engine.game_state import GameState
    st = GameState("seed")
    st.params = dict(config.STARTING_PARAMS)  # no_interest off
    st.dollars = 24
    assert st._interest() == min(24 // 5, 5)  # $4
    st.dollars = 100
    assert st._interest() == config.INTEREST_CAP // 5  # capped at $5
    st.params["no_interest"] = True
    st.dollars = 100
    assert st._interest() == 0


def test_localization_binds_key():
    loc = loader.localization("en-us")
    assert loc["descriptions"]["Joker"]["j_greedy_joker"]["name"] == "Greedy Joker"