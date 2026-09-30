"""Blind / boss-mechanic tests for the blind.lua port.

Covers ante scaling, the key/name effect lookup, every boss's data + `describe`,
and each ported method: set_blind prep, debuff_card, modify_hand, debuff_hand,
press_play, stay_flipped, drawn_to_hand, disable and defeat.
"""

from types import SimpleNamespace

from balatro_cli.data import loader
from balatro_cli.engine import blind as blind_mod
from balatro_cli.engine.blind import (
    BOSS_EFFECTS, TAG_DEBUFF_FACE, TAG_DEBUFF_SUIT, TAG_EYE, TAG_WATER,
    TAG_WHEEL, Blind, blind_name, boss_keys, describe, effects_for,
    eligible_boss_keys, get_blind_amount, key_for,
)
from balatro_cli.engine.card import Card, JokerCard
from balatro_cli.engine.hand import HAND_NAMES
from balatro_cli.engine.rng import RNG

ALL_BLINDS = loader.blinds()
BOSS_KEYS = [k for k, v in ALL_BLINDS.items() if v.get("boss")]


# -- fixtures ---------------------------------------------------------------

class FakeRun:
    """Minimal stand-in for the PORTING.md run duck type."""

    def __init__(self, seed: str = "blind-test"):
        self.rng = RNG(seed)
        self.hand: list = []
        self.deck: list = []
        self.played: list = []
        self.jokers: list = []
        self.highlighted: list = []
        self.dollars = 10
        self.hands_left = 4
        self.discards_left = 3
        self.hand_size = 8
        self.params = {"hands": 4, "discards": 3, "hand_size": 8}
        self.current_round = {"hands_played": 0, "discards_used": 0,
                              "most_played_poker_hand": "Pair"}
        self.hand_levels = {name: {"level": 1} for name in HAND_NAMES}

    def playing_cards(self):
        return list(self.deck) + list(self.hand) + list(self.played)

    def level_up_hand(self, key, amount=1):
        self.hand_levels[key]["level"] += amount


class StubRNG:
    """Records the roll and answers with a fixed result."""

    def __init__(self, result: bool):
        self.result = result
        self.calls: list[tuple] = []

    def chance(self, key, denominator, numerator=1.0):
        self.calls.append((key, denominator))
        return self.result


def blind(key, ante=1, scaling=1, ante_scaling=1):
    return Blind.from_key(key, ante, scaling, ante_scaling=ante_scaling)


def joker(name="Joker", key="j_joker"):
    return JokerCard(key, name)


# -- ante scaling -----------------------------------------------------------

def test_blind_amount_scaling_tables():
    assert get_blind_amount(1, 2) == 300
    assert get_blind_amount(8, 2) == 100000
    assert get_blind_amount(1, 3) == 300
    assert get_blind_amount(8, 3) == 200000
    assert get_blind_amount(0) == 100


def test_blind_amount_endless_rounds_down_to_two_significant_figures():
    for ante in range(9, 15):
        amount = get_blind_amount(ante)
        assert amount > 50000
        sig = 10 ** (len(str(amount)) - 2)
        assert amount % sig == 0
        assert get_blind_amount(ante + 1) > amount


def test_set_chips_mult_and_scaling():
    b = Blind("bl_big", ALL_BLINDS["bl_big"], 2, 1)
    assert b.chips == int(800 * 1.5)
    assert b.kind == "big"
    # scaling=2 selects the stake-2 table; ante_scaling multiplies chips
    # separately (blind.lua:107) - Plasma Deck uses the multiplier only
    b2 = blind("bl_ox", 3, 2)
    assert b2.chips == int(get_blind_amount(3, 2) * 2)
    assert b2.is_boss and b2.boss and b2.kind == "boss"
    assert b2.is_defeated(b2.chips) and not b2.is_defeated(b2.chips - 1)
    b3 = blind("bl_ox", 3, 1, ante_scaling=2)
    assert b3.chips == int(get_blind_amount(3, 1) * 2 * 2)


# -- data + key/name driven lookup -----------------------------------------

def test_every_boss_loads_and_has_a_description():
    assert len(BOSS_KEYS) == 28
    for key in BOSS_KEYS:
        data = ALL_BLINDS[key]
        b = blind(key, 1)
        assert b.name == data["name"]
        assert b.canonical_key == key
        assert b.is_boss is True
        assert b.get_type() == "Boss"
        assert b.mult == data["mult"] and b.dollars == data["dollars"]
        assert describe(key) and b.description == describe(key)
        assert BOSS_EFFECTS[key]
        assert all(isinstance(e, str) and e for e in BOSS_EFFECTS[key])
    assert describe("bl_eye").startswith("The Eye:")
    assert blind_name("bl_final_leaf") == "Verdant Leaf"
    assert describe("bl_small")


def test_effect_tags_resolve_from_key_or_name():
    assert key_for("The Eye") == "bl_eye"
    assert effects_for("The Eye") == effects_for("bl_eye")
    b = blind("bl_eye")
    assert b.has_effect(TAG_EYE) and b.is_key("The Eye") and b.is_key("bl_eye")
    assert not b.has_effect(TAG_WHEEL)
    club = blind("bl_club")
    assert club.has_effect(TAG_DEBUFF_SUIT) and club.debuff == {"suit": "Clubs"}
    assert blind("bl_plant").has_effect(TAG_DEBUFF_FACE)
    assert not blind("bl_small").effects


def test_effect_tag_table_covers_every_implemented_boss():
    bm = blind_mod
    expected = {
        "bl_water": bm.TAG_WATER, "bl_needle": bm.TAG_NEEDLE,
        "bl_manacle": bm.TAG_MANACLE, "bl_hook": bm.TAG_HOOK,
        "bl_tooth": bm.TAG_TOOTH, "bl_fish": bm.TAG_FISH,
        "bl_wheel": bm.TAG_WHEEL, "bl_house": bm.TAG_HOUSE,
        "bl_mark": bm.TAG_MARK, "bl_eye": bm.TAG_EYE, "bl_mouth": bm.TAG_MOUTH,
        "bl_arm": bm.TAG_ARM, "bl_ox": bm.TAG_OX, "bl_flint": bm.TAG_FLINT,
        "bl_pillar": bm.TAG_PILLAR, "bl_final_bell": bm.TAG_CERULEAN_BELL,
        "bl_final_heart": bm.TAG_CRIMSON_HEART,
        "bl_final_leaf": bm.TAG_VERDANT_LEAF,
        "bl_final_acorn": bm.TAG_AMBER_ACORN,
        "bl_final_vessel": bm.TAG_VIOLET_VESSEL, "bl_wall": bm.TAG_WALL,
        "bl_psychic": bm.TAG_DEBUFF_H_SIZE_GE, "bl_serpent": bm.TAG_SERPENT,
    }
    for key, tag in expected.items():
        assert blind(key).has_effect(tag), key


def test_placeholder_key_falls_back_to_the_name():
    """game_state._boss_offer passes "bl_boss" for every boss."""
    data = {"name": "The Club", "mult": 2, "dollars": 5, "boss": True, "debuff": {}}
    b = Blind("bl_boss", data, 1)
    assert b.canonical_key == "bl_club"
    assert b.has_effect(TAG_DEBUFF_SUIT)
    assert b.debuff == {"suit": "Clubs"}        # backfilled from blinds.json


def test_get_type_and_kind():
    assert blind("bl_small").get_type() == "Small"
    assert blind("bl_big").get_type() == "Big"
    assert blind("bl_hook").get_type() == "Boss"
    assert blind("bl_small").kind == "small"
    assert blind("bl_big").kind == "big"
    assert Blind("mystery", {}, 1).get_type() is None


def test_eligible_boss_keys_are_ante_filtered():
    early = eligible_boss_keys(1)
    assert "bl_hook" in early and "bl_ox" not in early
    assert "bl_hook" not in eligible_boss_keys(1, used=["bl_hook"])
    assert "bl_final_leaf" in eligible_boss_keys(10)
    assert boss_keys() and all(k in ALL_BLINDS for k in boss_keys())


# -- set_blind / round start ------------------------------------------------

def test_set_blind_water_zeroes_discards():
    run = FakeRun()
    b = blind("bl_water")
    b.apply_start_effects(run)
    assert run.discards_left == 0
    assert b.discards_sub == 3
    b.disable(run)
    assert run.discards_left == 3


def test_set_blind_needle_leaves_one_hand():
    run = FakeRun()
    b = blind("bl_needle")
    b.apply_start_effects(run)
    assert run.hands_left == 1
    assert b.hands_sub == 3
    b.disable(run)
    assert run.hands_left == 4


def test_set_blind_manacle_shrinks_hand():
    run = FakeRun()
    run.deck = [Card("2", "S")]
    b = blind("bl_manacle")
    b.apply_start_effects(run)
    assert run.hand_size == 7
    b.disable(run)                              # +1 hand size and draw 1
    assert run.hand_size == 8
    assert len(run.hand) == 1


def test_set_blind_preps_eye_mouth_fish():
    eye = blind("bl_eye")
    assert set(eye.hands) == set(HAND_NAMES) and not any(eye.hands.values())
    assert blind("bl_mouth").only_hand is False
    assert blind("bl_fish").prepped is None
    assert blind("bl_water").prepped is True
    assert blind("bl_water").disabled is False


def test_set_blind_debuffs_every_playing_card():
    run = FakeRun()
    club, heart = Card("2", "C"), Card("2", "H")
    wild = Card("3", "H", enhancement="m_wild")
    stone = Card("4", "C", enhancement="m_stone")
    run.hand = [club, heart]
    run.deck = [wild, stone]
    b = blind("bl_club")
    b.apply_start_effects(run)
    assert club.debuffed is True
    assert wild.debuffed is True                # Wild cards count for every suit
    assert heart.debuffed is False
    assert stone.debuffed is False              # stone is never a suit
    b.disable(run)
    assert not any(c.debuffed for c in run.playing_cards())


def test_amber_acorn_flips_and_shuffles_jokers():
    run = FakeRun(seed="amber")
    original = [joker("A", "j_a"), joker("B", "j_b"), joker("C", "j_c")]
    run.jokers = list(original)
    b = blind("bl_final_acorn", 10)
    b.apply_start_effects(run)
    assert all(j.ability["facing"] == "back" for j in run.jokers)
    shuffled = [j.key for j in RNG("amber").shuffle("amber_acorn", original)]
    assert [j.key for j in run.jokers] == shuffled
    b.disable(run)
    assert all(j.ability.get("facing") == "front" for j in run.jokers)


# -- modify_hand (The Flint) ------------------------------------------------

def test_flint_halves_mult_and_chips():
    b = blind("bl_flint")
    assert b.modify_hand([], {}, "Flush", 8, 35) == (4, 18, True)
    assert b.triggered is True
    assert b.modify_hand([], {}, "Pair", 1, 1) == (1, 1, True)


def test_modify_hand_identity_and_disabled():
    assert blind("bl_hook").modify_hand([], {}, "Flush", 8, 35) == (8, 35, False)
    flint = blind("bl_flint")
    flint.disabled = True
    assert flint.modify_hand([], {}, "Flush", 8, 35) == (8, 35, False)


# -- debuff_hand ------------------------------------------------------------

def test_the_eye_blocks_repeats():
    b = blind("bl_eye")
    cards = [Card("8", "S"), Card("8", "H")]
    assert b.debuff_hand(cards, {}, "Pair") is False
    assert b.hands["Pair"] is True
    assert b.debuff_hand(cards, {}, "Pair") is True and b.triggered is True
    assert b.debuff_hand(cards, {}, "Flush") is False


def test_the_eye_check_does_not_record():
    b = blind("bl_eye")
    assert b.debuff_hand([], {}, "Pair", check=True) is False
    assert b.hands["Pair"] is False


def test_the_mouth_allows_only_the_first_hand_type():
    b = blind("bl_mouth")
    cards = [Card("8", "S"), Card("8", "H")]
    assert b.debuff_hand(cards, {}, "Pair") is False
    assert b.only_hand == "Pair"
    assert b.debuff_hand(cards, {}, "Pair") is False
    assert b.debuff_hand(cards, {}, "Flush") is True
    b2 = blind("bl_mouth")
    b2.debuff_hand(cards, {}, "Pair", check=True)
    assert b2.only_hand is False


def test_data_driven_debuffs_hand_and_size():
    psychic = blind("bl_psychic")
    assert psychic.debuff_hand([Card("2", "S")] * 4, {}, "Pair") is True   # < 5
    assert psychic.debuff_hand([Card("2", "S")] * 5, {}, "Flush") is False
    b = Blind("bl_x", {"name": "X", "boss": True, "debuff": {"hand": "Flush"}}, 1)
    assert b.debuff_hand([], {"Flush": [Card("2", "S")]}, "Flush") is True
    assert b.debuff_hand([], {"Flush": []}, "Flush") is False
    b2 = Blind("bl_y", {"name": "Y", "boss": True, "debuff": {"h_size_le": 2}}, 1)
    assert b2.debuff_hand([Card("2", "S")] * 3, {}, "Pair") is True


def test_the_arm_levels_down_the_played_hand():
    run = FakeRun()
    run.hand_levels["Flush"]["level"] = 2
    b = blind("bl_arm")
    assert b.debuff_hand([], {}, "Flush", run=run) is False   # not a thrown hand
    assert b.triggered is True
    assert run.hand_levels["Flush"]["level"] == 1
    run.hand_levels["Flush"]["level"] = 2
    assert b.debuff_hand([], {}, "Flush", check=True, run=run) is False
    assert run.hand_levels["Flush"]["level"] == 2             # check is a probe
    assert b.debuff_hand([], {}, "Pair", level=1) is False
    assert b.triggered is False


def test_the_ox_zeroes_money_on_the_most_played_hand():
    run = FakeRun()
    b = blind("bl_ox")
    assert b.debuff_hand([], {}, "Flush", run=run) is False
    assert run.dollars == 10
    assert b.debuff_hand([], {}, "Pair", run=run) is False
    assert b.triggered is True and run.dollars == 0
    run.dollars = 10
    assert b.debuff_hand([], {}, "Pair", check=True, run=run) is False
    assert run.dollars == 10                                  # check is a probe
    assert b.debuff_hand([], {}, "Pair", most_played="Pair") is False


def test_debuff_hand_disabled():
    b = blind("bl_eye")
    b.disabled = True
    assert b.debuff_hand([], {}, "Pair") is False
    assert b.hands["Pair"] is False


# -- debuff_card ------------------------------------------------------------

def test_debuff_card_suit_and_face():
    club = blind("bl_club")
    assert club.debuff_card(Card("2", "C")) is True
    assert club.debuff_card(Card("2", "H")) is False
    plant = blind("bl_plant")
    face = Card("K", "S")
    assert plant.debuff_card(face) is True and face.debuffed is True
    assert plant.debuff_card(Card("T", "S")) is False
    flags = SimpleNamespace(pareidolia=True)
    assert plant.debuff_card(Card("2", "S"), flags=flags) is True


def test_debuff_card_pillar_value_and_nominal():
    pillar = blind("bl_pillar")
    card = Card("2", "S")
    assert pillar.debuff_card(card) is False
    card.ability["played_this_ante"] = 1
    assert pillar.debuff_card(card) is True
    by_value = Blind("bl_v", {"name": "V", "boss": True, "debuff": {"value": "K"}}, 1)
    assert by_value.debuff_card(Card("K", "S")) is True
    assert by_value.debuff_card(Card("Q", "S")) is False
    ten = Blind("bl_t", {"name": "T", "boss": True, "debuff": {"value": "10"}}, 1)
    assert ten.debuff_card(Card("T", "S")) is True
    by_nominal = Blind("bl_n", {"name": "N", "boss": True, "debuff": {"nominal": 11}}, 1)
    assert by_nominal.debuff_card(Card("A", "S")) is True
    assert by_nominal.debuff_card(Card("K", "S")) is False


def test_debuff_card_verdant_leaf_and_crimson_heart():
    leaf = blind("bl_final_leaf", 10)
    card, j = Card("2", "S"), joker()
    assert leaf.debuff_card(card) is True
    assert leaf.debuff_card(j) is False and j.debuffed is False
    heart = blind("bl_final_heart", 10)
    j2 = joker()
    j2.set_debuff(True)
    assert heart.debuff_card(j2) is True        # jokers keep their state
    assert heart.debuff_card(card) is False     # playing cards are cleared
    assert card.debuffed is False


# -- stay_flipped -----------------------------------------------------------

def test_stay_flipped_wheel_rolls_one_in_seven():
    b = blind("bl_wheel")
    stub = StubRNG(True)
    assert b.stay_flipped("hand", Card("2", "S"), rng=stub) is True
    assert stub.calls == [("wheel", 7)]
    assert b.stay_flipped("hand", Card("2", "S"), rng=StubRNG(False)) is False
    assert b.stay_flipped("deck", Card("2", "S"), rng=StubRNG(True)) is False


def test_stay_flipped_house_marks_and_fish():
    house = blind("bl_house")
    card = Card("2", "S")
    assert house.stay_flipped("hand", card, hands_played=0, discards_used=0) is True
    assert card.ability["wheel_flipped"] is True
    assert house.stay_flipped("hand", card, hands_played=1, discards_used=0) is False
    assert house.stay_flipped("hand", card, hands_played=0, discards_used=1) is False
    mark = blind("bl_mark")
    debuffed_face = Card("K", "S")
    debuffed_face.set_debuff(True)
    assert mark.stay_flipped("hand", debuffed_face) is True   # is_face(true)
    assert mark.stay_flipped("hand", Card("2", "S")) is False
    fish = blind("bl_fish")
    assert fish.stay_flipped("hand", Card("2", "S")) is False
    fish.press_play()
    assert fish.prepped is True
    assert fish.stay_flipped("hand", Card("2", "S")) is True
    disabled = blind("bl_house")
    disabled.disabled = True
    assert disabled.stay_flipped("hand", Card("2", "S"),
                                 hands_played=0, discards_used=0) is False


# -- press_play -------------------------------------------------------------

def test_press_play_hook_discards_two_random_cards():
    run = FakeRun(seed="hook")
    run.hand = [Card(r, "S") for r in ("2", "3", "4", "5", "6")]
    b = blind("bl_hook")
    out = b.press_play(run=run)
    assert len(out["hook_discarded"]) == 2 and out["triggered"] is True
    assert b.triggered is True
    assert len(run.hand) == 3 and len(run.played) == 2
    assert run.discards_left == 3               # Hook discards are free
    assert not set(out["hook_discarded"]) & set(run.hand)
    assert len(b.press_play(run=run)["hook_discarded"]) == 2
    assert len(run.hand) == 1 and len(run.played) == 4


def test_press_play_tooth_charges_per_card():
    run = FakeRun()
    b = blind("bl_tooth")
    out = b.press_play(run=run, cards=[Card("2", "S"), Card("3", "S"), Card("4", "S")])
    assert out["dollars_lost"] == 3 and run.dollars == 7
    assert b.triggered is True
    assert b.press_play(run=run, cards=[])["dollars_lost"] == 0


def test_press_play_crimson_heart_preps_with_jokers():
    run = FakeRun()
    b = blind("bl_final_heart", 10)
    assert b.press_play(run=run)["triggered"] is False
    run.jokers = [joker()]
    assert b.press_play(run=run)["triggered"] is True
    assert b.prepped is True


# -- drawn_to_hand ----------------------------------------------------------

def test_cerulean_bell_forces_one_card():
    run = FakeRun(seed="bell")
    run.hand = [Card("2", "S"), Card("3", "S"), Card("4", "S")]
    b = blind("bl_final_bell", 10)
    forced = b.drawn_to_hand(run=run)["forced"]
    assert forced is not None and forced.ability["forced_selection"] is True
    assert run.highlighted == [forced]
    assert b.drawn_to_hand(run=run)["forced"] is None      # already forced
    b.disable(run)
    assert not any(c.ability.get("forced_selection") for c in run.hand)
    assert run.highlighted == []


def test_crimson_heart_debuffs_one_joker_per_hand():
    run = FakeRun(seed="heart")
    run.jokers = [joker("A", "j_a"), joker("B", "j_b"), joker("C", "j_c")]
    b = blind("bl_final_heart", 10)
    assert b.drawn_to_hand(run=run)["debuffed_joker"] is not None
    assert sum(1 for j in run.jokers if j.debuffed) == 1
    assert b.prepped is None                               # cleared after the draw
    assert b.drawn_to_hand(run=run)["debuffed_joker"] is None
    b.press_play(run=run)
    assert b.prepped is True
    assert b.drawn_to_hand(run=run)["debuffed_joker"] is not None
    assert sum(1 for j in run.jokers if j.debuffed) == 1


# -- disable / defeat -------------------------------------------------------

def test_disable_wall_and_violet_vessel_chips():
    wall = blind("bl_wall", 2)
    assert wall.chips == int(get_blind_amount(2) * 4)
    wall.disable(FakeRun())
    assert wall.chips == int(get_blind_amount(2) * 4 / 2)
    vessel = blind("bl_final_vessel", 10)
    assert vessel.chips == int(get_blind_amount(10) * 6)
    vessel.disable(FakeRun())
    assert vessel.chips == int(get_blind_amount(10) * 6 / 3)


def test_disable_clears_debuffs_and_keeps_data():
    run = FakeRun()
    card, j = Card("2", "C"), joker()
    j.set_debuff(True)
    run.hand = [card]
    run.jokers = [j]
    b = blind("bl_club")
    b.apply_start_effects(run)
    assert card.debuffed is True
    b.disable(run)
    assert b.disabled is True and card.debuffed is False
    assert b.debuff == {"suit": "Clubs"}        # data is kept for display


def test_defeat_restores_manacle_and_clears_the_blind():
    run = FakeRun()
    run.deck = [Card("2", "S")]
    card = Card("2", "C")
    run.hand = [card]
    b = blind("bl_club")
    b.apply_start_effects(run)
    assert card.debuffed is True
    b.defeat(run=run)
    assert b.name == "" and b.chips == 0 and b.debuff == {}
    assert b.is_boss is False and b.get_type() is None
    assert card.debuffed is False
    manacle = blind("bl_manacle")
    run2 = FakeRun()
    run2.deck = [Card("2", "S")]
    manacle.apply_start_effects(run2)
    assert run2.hand_size == 7
    manacle.defeat(run=run2)
    assert run2.hand_size == 8
