"""Tests for the ported joker table (`engine/jokers.py`).

Every assertion here is a number taken from ``centers.json`` / the Lua in
``balatro_source_code/card.lua`` -- the point is to pin the *values*, not just
the plumbing.
"""

from __future__ import annotations

from balatro_cli import config
from balatro_cli.data import loader
from balatro_cli.engine import jokers as J
from balatro_cli.engine.card import Card, JokerCard
from balatro_cli.engine.hand import JokerFlags, evaluate_poker_hand
from balatro_cli.engine.hooks import (AREA_HAND, AREA_JOKERS, AREA_PLAY,
                                      HOOK_AFTER, HOOK_BEFORE, HOOK_DISCARD,
                                      HOOK_END_OF_ROUND, HOOK_INDIVIDUAL,
                                      HOOK_JOKER_MAIN, HOOK_OTHER_JOKER,
                                      HOOK_REPETITION, Context, Effect)
from balatro_cli.engine.rng import RNG


# ---------------------------------------------------------------------------
# FakeRun -- only the duck-typed surface PORTING.md guarantees
# ---------------------------------------------------------------------------

class FakeRun:
    def __init__(self, seed: str = "test"):
        self.rng = RNG(seed)
        self.deck: list[Card] = []
        self.hand: list[Card] = []
        self.played: list[Card] = []
        self.jokers: list[JokerCard] = []
        self.consumeables: list[JokerCard] = []
        self.dollars = 10
        self.ante = 1
        self.round_num = 1
        self.hands_left = 4
        self.discards_left = 3
        self.hand_size = 8
        self.chips = 0
        self.the_blind = None
        self.params = dict(config.STARTING_PARAMS)
        self.modifiers: dict = {}
        self.current_round: dict = {"hands_played": 0, "discards_used": 0,
                                    "hands_left": 4, "discards_left": 3}
        self.hand_levels = {k: {**dict(v), "level": 1, "played": 0,
                                "played_this_round": 0}
                            for k, v in config.HAND_LEVELS.items()}
        self.joker_flags = JokerFlags()
        self.vouchers: list[str] = []
        self.used_vouchers: set[str] = set()
        self.playing_cards_added: list[Card] = []

    def playing_cards(self) -> list[Card]:
        return self.deck + self.hand + self.played + self.playing_cards_added


def card(rank: str, suit: str, enhancement: str | None = None,
         seal: str | None = None) -> Card:
    return Card(rank, suit, enhancement, None, seal)


def joker(key: str) -> JokerCard:
    center = loader.centers()[key]
    return JokerCard(key, name=center.get("name", key),
                     cfg=center.get("config") or {},
                     rarity=center.get("rarity", 1))


def main_ctx(run: FakeRun, played: list[Card], held: list[Card] | None = None,
             event: str = HOOK_JOKER_MAIN, **kw) -> Context:
    """A resolved `joker_main` context for `played` (event overridable)."""
    res = evaluate_poker_hand(played, run.joker_flags)
    return Context(event=event, run=run, cardarea=AREA_JOKERS,
                   full_hand=list(played), scoring_hand=list(res["top"] or []),
                   held=list(held or []), scoring_name=res["top_key"],
                   poker_hands=res, **kw)


def eff_for(key: str, run: FakeRun, played: list[Card],
            held: list[Card] | None = None, **kw) -> Effect | None:
    return J.calculate(run, joker(key), main_ctx(run, played, held, **kw))


# ---------------------------------------------------------------------------
# coverage
# ---------------------------------------------------------------------------

def test_every_joker_centre_is_registered():
    keys = J.joker_keys()
    assert len(keys) == 150
    assert keys == J.covered()
    assert J.UNIMPLEMENTED == set()
    assert not (J.covered() - J.joker_keys())


def test_registry_dispatch_is_by_key_not_display_name():
    run = FakeRun()
    played = [card("K", "S"), card("K", "H")]
    # keyed on the centre key even though the display name is "Joker"
    assert J.calculate(run, "j_joker", main_ctx(run, played)).mult == 4
    assert J.calculate(run, joker("j_joker"), main_ctx(run, played)).mult == 4
    assert J.calculate(run, "j_does_not_exist", main_ctx(run, played)) is None


# ---------------------------------------------------------------------------
# pure scoring: flat mult
# ---------------------------------------------------------------------------

def test_joker_plus_four_mult():
    run = FakeRun()
    assert eff_for("j_joker", run, [card("K", "S"), card("K", "H")]).mult == 4


def test_suit_mult_jokers():
    run = FakeRun()
    diamonds = [card("2", "D"), card("3", "D")]
    hearts = [card("2", "H"), card("3", "H")]
    spades = [card("2", "S"), card("3", "S")]
    clubs = [card("2", "C"), card("3", "C")]
    assert eff_for("j_greedy_joker", run, diamonds).mult == 3
    assert eff_for("j_lusty_joker", run, hearts).mult == 3
    assert eff_for("j_wrathful_joker", run, spades).mult == 3
    assert eff_for("j_gluttenous_joker", run, clubs).mult == 3
    assert eff_for("j_greedy_joker", run, hearts) is None


def test_hand_keyed_mult_jokers():
    run = FakeRun()
    pair = [card("K", "S"), card("K", "H")]
    two_pair = [card("K", "S"), card("K", "H"), card("3", "S"), card("3", "H")]
    trips = [card("K", "S"), card("K", "H"), card("K", "D")]
    straight = [card("5", "S"), card("6", "H"), card("7", "D"),
                card("8", "C"), card("9", "S")]
    flush = [card("5", "H"), card("7", "H"), card("9", "H"),
             card("J", "H"), card("K", "H")]
    assert eff_for("j_jolly", run, pair).mult == 8
    assert eff_for("j_zany", run, trips).mult == 12
    assert eff_for("j_mad", run, two_pair).mult == 10
    assert eff_for("j_crazy", run, straight).mult == 12
    assert eff_for("j_droll", run, flush).mult == 10


def test_hand_keyed_chip_jokers():
    run = FakeRun()
    pair = [card("K", "S"), card("K", "H")]
    two_pair = [card("K", "S"), card("K", "H"), card("3", "S"), card("3", "H")]
    trips = [card("K", "S"), card("K", "H"), card("K", "D")]
    straight = [card("5", "S"), card("6", "H"), card("7", "D"),
                card("8", "C"), card("9", "S")]
    flush = [card("5", "H"), card("7", "H"), card("9", "H"),
             card("J", "H"), card("K", "H")]
    assert eff_for("j_sly", run, pair).chips == 50
    assert eff_for("j_wily", run, trips).chips == 100
    assert eff_for("j_clever", run, two_pair).chips == 80
    assert eff_for("j_devious", run, straight).chips == 100
    assert eff_for("j_crafty", run, flush).chips == 80


def test_xmult_by_hand_type_jokers():
    run = FakeRun()
    pair = [card("K", "S"), card("K", "H")]
    trips = [card("K", "S"), card("K", "H"), card("K", "D")]
    straight = [card("5", "S"), card("6", "H"), card("7", "D"),
                card("8", "C"), card("9", "S")]
    flush = [card("5", "H"), card("7", "H"), card("9", "H"),
             card("J", "H"), card("K", "H")]
    assert eff_for("j_duo", run, pair).x_mult == 2
    assert eff_for("j_trio", run, trips).x_mult == 3
    assert eff_for("j_order", run, straight).x_mult == 3
    assert eff_for("j_tribe", run, flush).x_mult == 2


# ---------------------------------------------------------------------------
# conditional / contextual scoring jokers
# ---------------------------------------------------------------------------

def test_half_joker_needs_three_or_fewer_cards():
    run = FakeRun()
    two = [card("5", "S"), card("7", "H")]
    five = [card("5", "S"), card("6", "H"), card("7", "D"),
            card("8", "C"), card("9", "S")]
    assert eff_for("j_half", run, two).mult == 20
    assert eff_for("j_half", run, five) is None


def test_supernova_counts_played_hand():
    run = FakeRun()
    run.hand_levels["Pair"]["played"] = 7
    assert eff_for("j_supernova", run, [card("K", "S"), card("K", "H")]).mult == 7


def test_banner_scales_with_discards_left():
    run = FakeRun()
    run.current_round["discards_left"] = 2
    assert eff_for("j_banner", run, [card("K", "S"), card("K", "H")]).chips == 60
    run.current_round["discards_left"] = 0
    assert eff_for("j_banner", run, [card("K", "S"), card("K", "H")]) is None


def test_abstract_joker_counts_owned_jokers():
    run = FakeRun()
    run.jokers = [joker("j_abstract"), joker("j_joker")]
    pair = [card("K", "S"), card("K", "H")]
    assert eff_for("j_abstract", run, pair).mult == 6


def test_acrobat_and_mystic_summit():
    run = FakeRun()
    pair = [card("K", "S"), card("K", "H")]
    run.current_round["hands_left"] = 0
    assert eff_for("j_acrobat", run, pair).x_mult == 3
    run.current_round["hands_left"] = 1
    assert eff_for("j_acrobat", run, pair) is None
    run.current_round["discards_left"] = 0
    assert eff_for("j_mystic_summit", run, pair).mult == 15
    run.current_round["discards_left"] = 3
    assert eff_for("j_mystic_summit", run, pair) is None


def test_misprint_rolls_within_configured_range():
    run = FakeRun()
    pair = [card("K", "S"), card("K", "H")]
    value = eff_for("j_misprint", run, pair).mult
    assert 0 <= value <= 23


def test_blackboard_all_black_suits():
    run = FakeRun()
    black = [card("2", "C"), card("3", "S")]
    mixed = [card("2", "C"), card("3", "H")]
    run.hand = black
    assert eff_for("j_blackboard", run, [card("K", "S"), card("K", "H")]).x_mult == 3
    run.hand = mixed
    assert eff_for("j_blackboard", run, [card("K", "S"), card("K", "H")]) is None


def test_stuntman_chips_from_config():
    run = FakeRun()
    assert eff_for("j_stuntman", run, [card("K", "S"), card("K", "H")]).chips == 250


def test_flower_pot_needs_all_four_suits():
    run = FakeRun()
    four = [card("2", "H"), card("3", "D"), card("4", "S"), card("5", "C")]
    three = [card("2", "H"), card("3", "D"), card("4", "S")]
    assert eff_for("j_flower_pot", run, four).x_mult == 3
    assert eff_for("j_flower_pot", run, three) is None


def test_seeing_double_needs_a_club_plus_another_suit():
    run = FakeRun()
    ok = [card("2", "C"), card("3", "H")]
    no = [card("2", "C"), card("3", "C")]
    assert eff_for("j_seeing_double", run, ok).x_mult == 2
    assert eff_for("j_seeing_double", run, no) is None


def test_blue_joker_reads_deck_size():
    run = FakeRun()
    run.deck = [card("2", "C")] * 40
    assert eff_for("j_blue_joker", run, [card("K", "S"), card("K", "H")]).chips == 80


def test_bull_scales_with_dollars():
    run = FakeRun()
    run.dollars = 13
    assert eff_for("j_bull", run, [card("K", "S"), card("K", "H")]).chips == 26


def test_bootstraps_every_five_dollars():
    run = FakeRun()
    run.dollars = 17
    assert eff_for("j_bootstraps", run, [card("K", "S"), card("K", "H")]).mult == 6


def test_erosion_counts_missing_deck_cards():
    run = FakeRun()
    run.playing_cards_added = []
    run.hand = [card("2", "C")] * 50
    assert eff_for("j_erosion", run, [card("K", "S"), card("K", "H")]).mult == 8


def test_satoshi_below_thirty_two_has_no_effect():
    run = FakeRun()
    # Driver's License needs a tally of 16 enhanced cards
    assert eff_for("j_drivers_license", run, [card("K", "S"), card("K", "H")]) is None
    joker("j_drivers_license").ability["driver_tally"] = 16
    dl = joker("j_drivers_license")
    dl.ability["driver_tally"] = 16
    assert J.calculate(run, dl, main_ctx(run, [card("K", "S"), card("K", "H")])).x_mult == 3


def test_stone_and_steel_joker_tallies():
    run = FakeRun()
    run.playing_cards_added = [card("2", "C", "m_stone")] * 3
    assert J.calculate(run, joker("j_stone"),
                       main_ctx(run, [card("K", "S")])).chips == 75
    run2 = FakeRun()
    run2.playing_cards_added = [card("2", "C", "m_steel")] * 2
    assert J.calculate(run2, joker("j_steel_joker"),
                       main_ctx(run2, [card("K", "S")])).x_mult == 1.4


# ---------------------------------------------------------------------------
# per-card (individual) jokers
# ---------------------------------------------------------------------------

def individual(key: str, run: FakeRun, played: list[Card], other: Card,
               area: str = AREA_PLAY, held: list[Card] | None = None):
    res = evaluate_poker_hand(played, run.joker_flags)
    ctx = Context(event=HOOK_INDIVIDUAL, run=run, cardarea=area,
                  other_card=other, full_hand=list(played),
                  scoring_hand=list(res["top"] or []), held=list(held or []),
                  scoring_name=res["top_key"], poker_hands=res)
    return J.calculate(run, joker(key), ctx)


def test_per_face_and_per_rank_individual_jokers():
    run = FakeRun()
    king = card("K", "S")
    king_h = card("K", "H")
    ace = card("A", "S")
    two = card("2", "S")
    assert individual("j_scary_face", run, [king, king_h], king).chips == 30
    assert individual("j_smiley", run, [king, king_h], king).mult == 5
    assert individual("j_scholar", run, [ace, two], ace).mult == 4
    assert individual("j_scholar", run, [ace, two], ace).chips == 20
    assert individual("j_fibonacci", run, [ace, two], two).mult == 8
    assert individual("j_even_steven", run, [ace, two], two).mult == 4
    assert individual("j_odd_todd", run, [ace, two], two) is None


def test_walkie_talkie_hits_tens_and_fours():
    run = FakeRun()
    ten = card("T", "S")
    four = card("4", "S")
    five = card("5", "S")
    assert individual("j_walkie_talkie", run, [ten, five], ten).chips == 10
    assert individual("j_walkie_talkie", run, [ten, five], ten).mult == 4
    assert individual("j_walkie_talkie", run, [four, five], four).mult == 4
    assert individual("j_walkie_talkie", run, [five, ten], five) is None


def test_suit_individual_jokers():
    run = FakeRun()
    diam = card("2", "D")
    club = card("3", "C")
    spade = card("4", "S")
    heart = card("5", "H")
    hand = [diam, club, spade, heart]
    assert individual("j_rough_gem", run, hand, diam).dollars == 1
    assert individual("j_onyx_agate", run, hand, club).mult == 7
    assert individual("j_arrowhead", run, hand, spade).chips == 50
    assert individual("j_triboulet", run, [card("Q", "S"), heart], card("Q", "S")).x_mult == 2


def test_photograph_only_first_face():
    run = FakeRun()
    king, queen = card("K", "S"), card("Q", "H")
    hand = [king, queen]
    assert individual("j_photograph", run, hand, king).x_mult == 2
    assert individual("j_photograph", run, hand, queen) is None


def test_held_card_jokers():
    run = FakeRun()
    queen = card("Q", "S")
    king = card("K", "S")
    run.hand = [queen, king]
    assert individual("j_shoot_the_moon", run, [card("5", "C")], queen,
                      area=AREA_HAND, held=run.hand).mult == 13
    assert individual("j_baron", run, [card("5", "C")], king,
                      area=AREA_HAND, held=run.hand).x_mult == 1.5


def test_raised_fist_doubles_lowest_card_nominal():
    run = FakeRun()
    low = card("3", "S")
    high = card("K", "H")
    run.hand = [high, low]
    eff = individual("j_raised_fist", run, [card("5", "C")], low,
                     area=AREA_HAND, held=run.hand)
    assert eff.mult == 6
    assert individual("j_raised_fist", run, [card("5", "C")], high,
                      area=AREA_HAND, held=run.hand) is None


def test_bloodstone_and_ancient_and_idol_use_round_state():
    run = FakeRun()
    run.current_round["ancient_card"] = {"suit": "Hearts"}
    heart = card("2", "H")
    club = card("2", "C")
    assert individual("j_ancient", run, [heart, club], heart).x_mult == 1.5
    assert individual("j_ancient", run, [heart, club], club) is None
    run.current_round["idol_card"] = {"rank": "Ace", "suit": "Spades", "id": 14}
    ace = card("A", "S")
    assert individual("j_idol", run, [ace, club], ace).x_mult == 2


def test_eight_ball_and_business_card_roll_dollars():
    run = FakeRun()
    eight = card("8", "S")
    # both roll on a deterministic RNG; assert the *possible* outcomes only
    for _ in range(20):
        eff = individual("j_8_ball", run, [eight], eight)
        assert eff is None or eff.create == [{"kind": "Tarot", "count": 1}]
    face = card("K", "S")
    for _ in range(20):
        eff = individual("j_business", run, [face], face)
        assert eff is None or eff.dollars == 2


def test_hiker_and_wee_joker_and_lucky_cat_mutate_state():
    run = FakeRun()
    two = card("2", "S")
    hiker = joker("j_hiker")
    individual("j_hiker", run, [two], two)
    assert two.ability["perma_bonus"] == 5
    wee = joker("j_wee")
    individual("j_wee", run, [two], two)
    assert wee.ability["extra"]["chips"] == 8
    assert J.calculate(run, wee, main_ctx(run, [two])).chips == 8
    lucky = joker("j_lucky_cat")
    two.ability["lucky_trigger"] = True
    res = evaluate_poker_hand([two], run.joker_flags)
    ctx = Context(event=HOOK_INDIVIDUAL, run=run, cardarea=AREA_PLAY,
                  other_card=two, full_hand=[two],
                  scoring_hand=[two], scoring_name=res["top_key"],
                  poker_hands=res)
    J.calculate(run, lucky, ctx)
    assert lucky.ability["x_mult"] == 1.25


# ---------------------------------------------------------------------------
# retriggers
# ---------------------------------------------------------------------------

def repetition(key: str, run: FakeRun, other: Card, area: str = AREA_PLAY,
               scoring: list[Card] | None = None) -> Effect | None:
    ctx = Context(event=HOOK_REPETITION, run=run, cardarea=area,
                  other_card=other, full_hand=[other],
                  scoring_hand=list(scoring if scoring is not None else [other]))
    return J.calculate(run, joker(key), ctx)


def test_sock_and_buskin_retriggers_faces():
    run = FakeRun()
    assert repetition("j_sock_and_buskin", run, card("K", "S")).repetitions == 1
    assert repetition("j_sock_and_buskin", run, card("2", "S")) is None


def test_hack_retriggers_low_ranks():
    run = FakeRun()
    assert repetition("j_hack", run, card("2", "S")).repetitions == 1
    assert repetition("j_hack", run, card("5", "S")).repetitions == 1
    assert repetition("j_hack", run, card("6", "S")) is None


def test_hanging_chad_only_first_scoring_card():
    run = FakeRun()
    first, second = card("2", "S"), card("3", "H")
    assert repetition("j_hanging_chad", run, first,
                      scoring=[first, second]).repetitions == 2
    assert repetition("j_hanging_chad", run, second,
                      scoring=[first, second]) is None


def test_dusk_retriggers_on_last_hand():
    run = FakeRun()
    run.current_round["hands_left"] = 0
    assert repetition("j_dusk", run, card("2", "S")).repetitions == 1
    run.current_round["hands_left"] = 2
    assert repetition("j_dusk", run, card("2", "S")) is None


def test_seltzer_always_retriggers_then_decrements():
    run = FakeRun()
    seltzer = joker("j_selzer")
    assert repetition("j_selzer", run, card("2", "S")).repetitions == 1
    assert seltzer.ability["extra"] == 10
    assert J.calculate(run, seltzer, Context(event=HOOK_AFTER, run=run,
                                             cardarea=AREA_JOKERS)) is None
    assert seltzer.ability["extra"] == 9
    assert J.calculate(run, joker("j_selzer"), repetition_ctx(run)) is not None


def repetition_ctx(run: FakeRun) -> Context:
    return Context(event=HOOK_REPETITION, run=run, cardarea=AREA_PLAY,
                   other_card=card("2", "S"), scoring_hand=[card("2", "S")])


def test_mime_retriggers_held_effects():
    run = FakeRun()
    steel = card("2", "S", "m_steel")
    assert repetition("j_mime", run, steel, area=AREA_HAND).repetitions == 1


def test_red_seal_interaction_via_repetition_count():
    run = FakeRun()
    run.jokers = [joker("j_sock_and_buskin")]
    # scoring.py counts seal + joker retriggers; here just pin the joker half
    face = card("K", "S", None, seal="s_red")
    assert repetition("j_sock_and_buskin", run, face).repetitions == 1


# ---------------------------------------------------------------------------
# stateful jokers
# ---------------------------------------------------------------------------

def test_green_joker_ramps_and_drops():
    run = FakeRun()
    green = joker("j_green_joker")
    pair = [card("K", "S"), card("K", "H")]
    before = Context(event=HOOK_BEFORE, run=run, cardarea=AREA_JOKERS,
                     full_hand=pair, scoring_name="Pair", poker_hands={})
    J.calculate(run, green, before)
    assert green.ability["mult"] == 1
    J.calculate(run, green, before)
    assert green.ability["mult"] == 2
    assert J.calculate(run, green, main_ctx(run, pair)).mult == 2
    # a discard removes one
    discard = Context(event=HOOK_DISCARD, run=run, other_card=pair[-1],
                      full_hand=pair)
    J.calculate(run, green, discard)
    assert green.ability["mult"] == 1


def test_ride_the_bus_resets_on_face_cards():
    run = FakeRun()
    bus = joker("j_ride_the_bus")
    run.hand_levels["High Card"]["played"] = 0
    before = Context(event=HOOK_BEFORE, run=run, cardarea=AREA_JOKERS,
                     full_hand=[card("2", "S")], scoring_hand=[card("2", "S")],
                     scoring_name="High Card", poker_hands={})
    J.calculate(run, bus, before)
    assert bus.ability["mult"] == 1
    J.calculate(run, bus, before)
    assert bus.ability["mult"] == 2
    face_before = Context(event=HOOK_BEFORE, run=run, cardarea=AREA_JOKERS,
                          full_hand=[card("K", "S")], scoring_hand=[card("K", "S")],
                          scoring_name="High Card", poker_hands={})
    assert J.calculate(run, bus, face_before) is None
    assert bus.ability["mult"] == 0


def test_runner_and_square_joker_ramp_chips():
    run = FakeRun()
    runner = joker("j_runner")
    straight = [card("5", "S"), card("6", "H"), card("7", "D"),
                card("8", "C"), card("9", "S")]
    ctx = main_ctx(run, straight, event=HOOK_BEFORE)
    J.calculate(run, runner, ctx)
    assert runner.ability["extra"]["chips"] == 15
    assert J.calculate(run, runner, main_ctx(run, straight)).chips == 15
    square = joker("j_square")
    four = [card("5", "S"), card("6", "H"), card("7", "D"), card("8", "C")]
    J.calculate(run, square, main_ctx(run, four, event=HOOK_BEFORE))
    assert square.ability["extra"]["chips"] == 4
    assert J.calculate(run, square, main_ctx(run, four)).chips == 4


def test_ice_cream_loses_chips_and_melts():
    run = FakeRun()
    ice = joker("j_ice_cream")
    assert J.calculate(run, ice, main_ctx(run, [card("K", "S")])).chips == 100
    after = Context(event=HOOK_AFTER, run=run, cardarea=AREA_JOKERS)
    J.calculate(run, ice, after)
    assert ice.ability["extra"]["chips"] == 95
    ice.ability["extra"]["chips"] = 5
    eff = J.calculate(run, ice, after)
    assert eff.extra["destroy_self"] is True


def test_popcorn_shrinks_at_round_end():
    run = FakeRun()
    pop = joker("j_popcorn")
    assert J.calculate(run, pop, main_ctx(run, [card("K", "S")])).mult == 20
    eor = Context(event=HOOK_END_OF_ROUND, run=run)
    J.calculate(run, pop, eor)
    assert pop.ability["mult"] == 16
    pop.ability["mult"] = 4
    eff = J.calculate(run, pop, eor)
    assert eff.extra["destroy_self"] is True


def test_ramen_loses_xmult_on_discard():
    run = FakeRun()
    ramen = joker("j_ramen")
    assert J.calculate(run, ramen, main_ctx(run, [card("K", "S")])).x_mult == 2
    discard = Context(event=HOOK_DISCARD, run=run, other_card=card("2", "S"))
    J.calculate(run, ramen, discard)
    assert round(ramen.ability["x_mult"], 4) == 1.99
    ramen.ability["x_mult"] = 1.005
    eff = J.calculate(run, ramen, discard)
    assert eff.extra["destroy_self"] is True


def test_campfire_grows_on_sell_and_resets_on_boss():
    run = FakeRun()
    fire = joker("j_campfire")
    J.calculate(run, fire, Context(event="selling_card", run=run))
    assert fire.ability["x_mult"] == 1.25
    J.calculate(run, fire, Context(event="selling_card", run=run))
    assert fire.ability["x_mult"] == 1.5
    assert J.calculate(run, fire, main_ctx(run, [card("K", "S")])).x_mult == 1.5

    class Boss:
        is_boss = True
        chips = 300
    run.the_blind = Boss()
    J.calculate(run, fire, Context(event=HOOK_END_OF_ROUND, run=run))
    assert fire.ability["x_mult"] == 1


def test_hologram_grows_when_playing_cards_are_added():
    run = FakeRun()
    holo = joker("j_hologram")
    added = [card("2", "S"), card("3", "H")]
    ctx = Context(event="playing_card_added", run=run, extra={"cards": added})
    J.calculate(run, holo, ctx)
    assert holo.ability["x_mult"] == 1.5
    assert J.calculate(run, holo, main_ctx(run, [card("K", "S")])).x_mult == 1.5


def test_obelisk_grows_when_it_is_the_most_played_hand():
    run = FakeRun()
    ob = joker("j_obelisk")
    run.hand_levels["Pair"]["played"] = 3
    run.hand_levels["Flush"]["played"] = 1
    ctx = main_ctx(run, [card("K", "S"), card("K", "H")], event=HOOK_BEFORE)
    J.calculate(run, ob, ctx)
    assert round(ob.ability["x_mult"], 4) == 1.2
    # now another hand is played more often -> reset
    run.hand_levels["Flush"]["played"] = 9
    J.calculate(run, ob, ctx)
    assert ob.ability["x_mult"] == 1


def test_spare_trousers_grows_on_two_pair():
    run = FakeRun()
    trousers = joker("j_trousers")
    two_pair = [card("K", "S"), card("K", "H"), card("3", "S"), card("3", "H")]
    J.calculate(run, trousers, main_ctx(run, two_pair, event=HOOK_BEFORE))
    assert trousers.ability["mult"] == 2
    J.calculate(run, trousers, main_ctx(run, two_pair, event=HOOK_BEFORE))
    assert J.calculate(run, trousers, main_ctx(run, two_pair)).mult == 4
    # a plain pair does not advance it
    J.calculate(run, trousers, main_ctx(run, [card("K", "S"), card("K", "H")],
                                        event=HOOK_BEFORE))
    assert trousers.ability["mult"] == 4


def test_ceremonial_dagger_slices_right_neighbour():
    run = FakeRun()
    dagger = joker("j_ceremonial")
    victim = joker("j_joker")
    run.jokers = [dagger, victim]
    ctx = Context(event="setting_blind", run=run)
    eff = J.calculate(run, dagger, ctx)
    assert eff.destroy is True
    assert eff.extra["destroy_joker"] is victim
    assert dagger.ability["mult"] == 2 * max(1, victim.sell_cost)
    assert J.calculate(run, dagger, main_ctx(run, [card("K", "S")])).mult == 2


def test_constellation_grows_on_planet_use():
    run = FakeRun()
    star = joker("j_constellation")
    planet = JokerCard("c_mercury", name="Mercury", cfg={}, set_="Planet")
    ctx = Context(event="using_consumeable", run=run, consumable=planet)
    J.calculate(run, star, ctx)
    assert round(star.ability["x_mult"], 4) == 1.1
    tarot = JokerCard("c_fool", name="The Fool", cfg={}, set_="Tarot")
    J.calculate(run, star, Context(event="using_consumeable", run=run,
                                   consumable=tarot))
    assert round(star.ability["x_mult"], 4) == 1.1
    assert J.calculate(run, star, main_ctx(run, [card("K", "S")])).x_mult == 1.1


def test_fortune_teller_reads_tarot_usage():
    run = FakeRun()
    teller = joker("j_fortune_teller")
    run.consumeable_usage_total = {"tarot": 6}
    assert J.calculate(run, teller, main_ctx(run, [card("K", "S")])).mult == 6


def test_loyalty_card_fires_every_fifth_hand():
    run = FakeRun()
    loyal = joker("j_loyalty_card")
    loyal.ability["hands_played_at_create"] = 0
    pair = [card("K", "S"), card("K", "H")]
    hits = []
    for total in range(0, 6):
        loyal.ability["total_hands_played"] = total
        eff = J.calculate(run, loyal, main_ctx(run, pair))
        hits.append(bool(eff and eff.x_mult == 4))
    assert loyal.ability["loyalty_remaining"] == (5 - 1 - 5) % 6
    assert hits.count(True) == 1


def test_flash_card_grows_on_reroll():
    run = FakeRun()
    flash = joker("j_flash")
    J.calculate(run, flash, Context(event="reroll_shop", run=run))
    J.calculate(run, flash, Context(event="reroll_shop", run=run))
    assert flash.ability["mult"] == 4
    assert J.calculate(run, flash, main_ctx(run, [card("K", "S")])).mult == 4


def test_yorick_discards_then_gains_xmult():
    run = FakeRun()
    yorick = joker("j_yorick")
    run.current_round["discards_used"] = 2
    discard = Context(event=HOOK_DISCARD, run=run, other_card=card("2", "S"))
    J.calculate(run, yorick, discard)
    assert yorick.ability["yorick_discards"] == 22
    yorick.ability["yorick_discards"] = 1
    J.calculate(run, yorick, discard)
    assert yorick.ability["x_mult"] == 2
    assert yorick.ability["yorick_discards"] == 23
    assert J.calculate(run, yorick, main_ctx(run, [card("K", "S")])).x_mult == 2


def test_caino_and_glass_react_to_destroyed_cards():
    run = FakeRun()
    caino = joker("j_caino")
    face = card("K", "S")
    ctx = Context(event="cards_destroyed", run=run,
                  extra={"glass_shattered": [face, card("2", "S")]})
    J.calculate(run, caino, ctx)
    assert caino.ability["caino_xmult"] == 2
    assert J.calculate(run, caino, main_ctx(run, [card("K", "S")])).x_mult == 2
    glass = joker("j_glass")
    shattered = card("2", "S", "m_glass")
    shattered.shattered = True
    J.calculate(run, glass, Context(event="remove_playing_cards", run=run,
                                    extra={"removed": [shattered, shattered]}))
    assert round(glass.ability["x_mult"], 4) == 2.5


def test_madness_and_burglar_and_riff_raff_on_setting_blind():
    run = FakeRun()
    madness = joker("j_madness")
    other = joker("j_joker")
    run.jokers = [madness, other]
    eff = J.calculate(run, madness, Context(event="setting_blind", run=run))
    assert round(madness.ability["x_mult"], 4) == 1.5
    assert eff.extra["destroy_joker"] is other

    run2 = FakeRun()
    burglar = joker("j_burglar")
    eff2 = J.calculate(run2, burglar, Context(event="setting_blind", run=run2))
    assert eff2.extra["hands_add"] == 3
    assert eff2.extra["discards_left"] == 0

    run3 = FakeRun()
    riff = joker("j_riff_raff")
    eff3 = J.calculate(run3, riff, Context(event="setting_blind", run=run3))
    assert eff3.create == [{"kind": "Joker", "count": 2}]


def test_certificate_and_perkeo_create_cards():
    run = FakeRun()
    cert = joker("j_certificate")
    eff = J.calculate(run, cert, Context(event="first_hand_drawn", run=run))
    assert eff.create[0]["kind"] == "playing_card"
    run.consumeables = [JokerCard("c_fool", name="The Fool", cfg={}, set_="Tarot")]
    perkeo = joker("j_perkeo")
    eff2 = J.calculate(run, perkeo, Context(event="ending_shop", run=run))
    assert eff2.create[0]["kind"] == "copy_consumeable"
    assert eff2.create[0]["negative"] is True


def test_gros_michel_and_cavendish_extinction_rolls():
    run = FakeRun()
    gros = joker("j_gros_michel")
    ctx = Context(event=HOOK_END_OF_ROUND, run=run)
    for _ in range(40):
        eff = J.calculate(run, gros, ctx)
        if eff and eff.extra.get("destroy_self"):
            assert run.pool_flags.get("gros_michel_extinct") is True
            break
    else:
        raise AssertionError("gros michel never rolled extinct")
    cav = joker("j_cavendish")
    assert J.calculate(run, cav, main_ctx(run, [card("K", "S")])).x_mult == 3


def test_mr_bones_saves_at_25_percent():
    run = FakeRun()

    class Boss:
        is_boss = True
        chips = 100
    run.the_blind = Boss()
    run.chips = 30
    bones = joker("j_mr_bones")
    eff = J.calculate(run, bones, Context(event=HOOK_END_OF_ROUND, run=run,
                                          game_over=True))
    assert eff.saved is True
    run.chips = 10
    assert J.calculate(run, bones, Context(event=HOOK_END_OF_ROUND, run=run,
                                           game_over=True)) is None


def test_to_do_list_and_space_joker_before_hooks():
    run = FakeRun()
    todo = joker("j_todo_list")
    todo.ability["to_do_poker_hand"] = "Pair"
    pair = [card("K", "S"), card("K", "H")]
    assert J.calculate(run, todo, main_ctx(run, pair)).dollars == 4
    assert J.calculate(run, todo, main_ctx(run, [card("2", "S")])) is None
    J.calculate(run, todo, Context(event=HOOK_END_OF_ROUND, run=run))
    assert todo.ability["to_do_poker_hand"] in run.hand_levels

    space = joker("j_space")
    hit = False
    for _ in range(60):
        ctx = main_ctx(run, pair, event=HOOK_BEFORE)
        eff = J.calculate(run, space, ctx)
        if eff is not None:
            assert eff.level_up is True
            hit = True
            break
    assert hit


def test_midas_mask_and_vampire_rewrite_scoring_cards():
    run = FakeRun()
    face = card("K", "S")
    midas = joker("j_midas_mask")
    J.calculate(run, midas, main_ctx(run, [face], event=HOOK_BEFORE))
    assert face.enhancement == "m_gold"
    vamp = joker("j_vampire")
    glass = card("2", "S", "m_glass")
    J.calculate(run, vamp, main_ctx(run, [glass], event=HOOK_BEFORE))
    assert glass.enhancement is None
    assert round(vamp.ability["x_mult"], 4) == 1.1


def test_dna_returns_a_card_copy():
    run = FakeRun()
    run.current_round["hands_played"] = 0
    dna = joker("j_dna")
    one = card("K", "S")
    eff = J.calculate(run, dna, main_ctx(run, [one], event=HOOK_BEFORE))
    assert eff.create[0]["kind"] == "copy"
    assert eff.create[0]["card"] is one


def test_sixth_sense_only_on_first_hand_single_six():
    run = FakeRun()
    run.current_round["hands_played"] = 0
    sixth = joker("j_sixth_sense")
    six = card("6", "S")
    eff = J.calculate(run, sixth, Context(event="destroying_card", run=run,
                                          full_hand=[six]))
    assert eff.create == [{"kind": "Spectral", "count": 1}]
    run.current_round["hands_played"] = 1
    assert J.calculate(run, sixth, Context(event="destroying_card", run=run,
                                           full_hand=[six])) is None


# ---------------------------------------------------------------------------
# Blueprint / Brainstorm / Baseball Card
# ---------------------------------------------------------------------------

def test_copy_index_blueprint_right_and_brainstorm_leftmost():
    run = FakeRun()
    bp, target = joker("j_blueprint"), joker("j_joker")
    run.jokers = [bp, target]
    assert J.copy_index(run, 0) == 1
    run.jokers = [target, bp]
    assert J.copy_index(run, 1) == -1
    bs = joker("j_brainstorm")
    run.jokers = [target, bs]
    assert J.copy_index(run, 1) == 0
    assert J.copy_index(run, 0) == -1


def test_blueprint_copies_the_joker_to_its_right():
    run = FakeRun()
    bp, target = joker("j_blueprint"), joker("j_joker")
    run.jokers = [bp, target]
    pair = [card("K", "S"), card("K", "H")]
    assert J.calculate(run, bp, main_ctx(run, pair)).mult == 4


def test_blueprint_does_not_recurse_when_already_a_copy():
    run = FakeRun()
    bp1, bp2 = joker("j_blueprint"), joker("j_blueprint")
    run.jokers = [bp1, bp2]
    assert J.calculate(run, bp1, main_ctx(run, [card("K", "S")])) is None


def test_brainstorm_copies_the_leftmost_joker():
    run = FakeRun()
    target, bs = joker("j_joker"), joker("j_brainstorm")
    run.jokers = [target, bs]
    pair = [card("K", "S"), card("K", "H")]
    assert J.calculate(run, bs, main_ctx(run, pair)).mult == 4


def test_baseball_card_only_other_joker_pass():
    run = FakeRun()
    ball = joker("j_baseball")
    common = joker("j_joker")
    rare = JokerCard("j_x", name="Rare", cfg={}, rarity=2)
    ctx = Context(event=HOOK_OTHER_JOKER, run=run, other_joker=rare)
    assert J.calculate(run, ball, ctx).x_mult == 1.5
    assert J.calculate(run, ball, Context(event=HOOK_OTHER_JOKER, run=run,
                                          other_joker=common)) is None
    # never on the ordinary main pass
    assert J.calculate(run, ball, main_ctx(run, [card("K", "S")])) is None


# ---------------------------------------------------------------------------
# dollar bonus / flags / find_joker helpers
# ---------------------------------------------------------------------------

def test_dollar_bonus_jokers():
    run = FakeRun()
    assert J.dollar_bonus(run, joker("j_golden")) == 4
    run.playing_cards_added = [card("9", "S")] * 3
    assert J.dollar_bonus(run, joker("j_cloud_9")) == 3
    assert J.dollar_bonus(run, joker("j_rocket")) == 1
    run.current_round["discards_used"] = 0
    run.current_round["discards_left"] = 3
    assert J.dollar_bonus(run, joker("j_delayed_grat")) == 6
    run.consumeable_usage = {"c_mercury": {"set": "Planet"},
                             "c_venus": {"set": "Planet"},
                             "c_fool": {"set": "Tarot"}}
    assert J.dollar_bonus(run, joker("j_satellite")) == 2


def test_rocket_grows_on_boss_defeat():
    run = FakeRun()

    class Boss:
        is_boss = True
        chips = 100
    run.the_blind = Boss()
    rocket = joker("j_rocket")
    J.calculate(run, rocket, Context(event=HOOK_END_OF_ROUND, run=run))
    assert rocket.ability["extra"]["dollars"] == 3
    assert J.dollar_bonus(run, rocket) == 3


def test_joker_flags_read_four_fingers_shortcut_smeared_oops():
    run = FakeRun()
    run.jokers = [joker("j_four_fingers"), joker("j_shortcut"),
                  joker("j_smeared"), joker("j_pareidolia"), joker("j_oops")]
    flags = J.joker_flags(run)
    assert flags is run.joker_flags
    assert flags.four_fingers is True
    assert flags.shortcut is True
    assert flags.smeared is True
    assert run.rng.probabilities_normal == 2
    assert J.joker_flags(FakeRun()).four_fingers is False


def test_has_and_count_use_centre_names():
    run = FakeRun()
    run.jokers = [joker("j_mime"), joker("j_mime"), joker("j_joker")]
    assert J.has(run, "Mime") is True
    assert J.count(run, "Mime") == 2
    assert J.count(run, "Blueprint") == 0
    assert J.has(run, "Joker") is True


def test_blueprint_has_no_effect_on_its_own_when_alone():
    run = FakeRun()
    run.jokers = [joker("j_blueprint")]
    assert J.calculate(run, run.jokers[0], main_ctx(run, [card("K", "S")])) is None
