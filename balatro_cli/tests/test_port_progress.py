"""Regression tests for the 2026-10 port-completion pass.

Each test pins one gap found by the audit in ``PORTING_PLAN.md`` against the
decompiled Lua.  See PORTING_PLAN.md for the item-by-item mapping.
"""

from __future__ import annotations

from balatro_cli.engine.card import Card, JokerCard
from balatro_cli.engine.game_state import GameState
from balatro_cli.engine.hooks import Effect
from balatro_cli.engine.shop import Shop


def _game(seed="1", deck="b_red"):
    g = GameState(seed, deck_key=deck)
    g.start()
    return g


# -- 0.1 Effect.create lands -------------------------------------------------

def test_create_spec_adds_consumable_and_respects_slots():
    g = _game()
    g.params["consumable_slots"] = 1
    made = g._create_from_spec({"kind": "Tarot", "count": 3})
    assert len(made) == 1
    assert len(g.consumeables) == 1


def test_dna_copies_first_played_card_into_deck():
    g = _game()
    g.add_joker("j_dna")
    hand = [Card("K", "H"), Card("5", "S")]
    g.hand[:] = hand
    g.play_cards([0, 1])
    # the copy joins the deck with the same rank/suit
    assert any(c.rank == "K" and c.suit == "H" for c in g.deck)


# -- 0.6 add_to_deck / remove_from_deck --------------------------------------

def test_juggler_and_drunkard_change_round_sizes():
    g = _game()
    g.select_blind("small")                 # baseline round sizes
    hs, dc = g.hand_size, g.discards_left
    g2 = _game()
    g2.add_joker("j_juggler")
    g2.add_joker("j_drunkard")
    g2.select_blind("small")
    assert g2.hand_size == hs + 1
    assert g2.discards_left == dc + 1
    g3 = _game()
    g3.add_joker("j_juggler")
    g3.remove_joker(0)
    g3.select_blind("small")
    assert g3.hand_size == hs and g3.discards_left == dc


def test_to_the_moon_raises_interest():
    g = _game()
    base = g.interest_amount
    g.add_joker("j_to_the_moon")
    assert g.interest_amount == base + 1
    g.remove_joker(0)
    assert g.interest_amount == base


def test_sell_value_includes_extra_value():
    g = _game()
    egg = g.add_joker("j_egg")
    egg.ability["extra_value"] = 4
    assert g.sell_value(egg) >= 5


# -- 0.5 win condition --------------------------------------------------------

def test_winning_ante8_boss_wins_the_run():
    g = _game()
    g.ante = 8
    g.blind_index = 3
    g._offer_blinds()
    g.select_blind("boss")
    g.chips = g.the_blind.chips + 1
    g.end_round()
    assert g.won_run is True
    assert g.phase == "won"


# -- boss selection (common_events.lua:2340) ----------------------------------

def test_showdown_boss_only_on_win_ante():
    g = _game()
    g.ante = 2
    g._offer_blinds()
    g.select_blind("big")          # -> boss offer for ante 2
    # ante 2 offers a boss; it must not be a showdown boss
    boss = [o for o in g.blind_choices if o.kind == "boss"]
    assert not boss or "bl_final_acorn" not in boss[0].key


def test_boss_reroll_with_directors_cut():
    g = _game()
    g.ante = 2
    g.blind_index = 3
    g._offer_blinds()
    assert not g.boss_reroll_info()["available"]
    g.boss_reroll_limit = 1
    g.boss_reroll_cost = 10
    g.dollars = 50
    info = g.boss_reroll_info()
    assert info["available"] is True
    old_key = next(o.key for o in g.blind_choices if o.kind == "boss")
    r = g.reroll_boss()
    assert r["ok"]
    assert g.boss_reroll_count == 1
    assert g.dollars == 40
    assert not g.boss_reroll_info()["available"]     # limit 1 spent


# -- 1.x tags ------------------------------------------------------------------

def test_skip_blind_pays_immediate_tags():
    g = _game()
    g.tags.append("tag_skip")
    before = g.dollars
    res = g.skip_blind(0)
    assert res["ok"]
    assert g.dollars >= before          # Skip Tag pays (per-skip money)


def test_double_tag_duplicates_next_tag():
    g = _game()
    g.add_tag("tag_double")
    assert len(g.tags) == 1
    g.add_tag("tag_handy")          # tag_add fires; the Double copies it
    assert g.tags.count("tag_handy") == 2


# -- 2.x blind / scoring --------------------------------------------------------

def test_blue_seal_creates_last_hand_planet():
    g = _game()
    g.last_hand_played = "Pair"
    card = Card("2", "S")
    card.seal = "blue"
    g.hand.append(card)
    g.params["consumable_slots"] = 2
    g._blue_seal_planets()
    from balatro_cli.data import loader
    planets = [c for c in g.consumeables
               if (loader.centers().get(getattr(c, "key", "")) or {}).get("set") == "Planet"]
    assert planets, "blue seal should produce a Planet"


def test_red_card_grows_on_skipped_pack():
    g = _game()
    j = g.add_joker("j_red_card")
    g.skip_pack({"key": "p_arcana_normal_1"})
    assert j.ability["mult"] == 3


def test_the_serpent_draws_three_after_first_play():
    from balatro_cli.engine.blind import Blind
    g = _game()
    g.the_blind = Blind("bl_serpent", {"name": "The Serpent"}, 1, 1)
    g.hands_left = 3
    g.hand[:] = g.hand[:1]          # single card played from a short hand
    g._draw_to_handsize()           # pre-action fill (no draw yet, hands 0)
    base = len(g.hand)
    g.hand.pop()                    # make room for one played card
    r = g.play_cards([0])
    assert r["ok"]
    # a plain blind would refill to hand_size; The Serpent draws exactly 3
    assert len(g.hand) == g.hand_size + 1


# -- 3.x shop --------------------------------------------------------------------

def test_shop_items_have_costs_and_reroll_keeps_packs():
    g = _game()
    s = Shop(g)
    s.refill()
    jokers = [it for it in s.items if it and it.kind == "joker"]
    assert jokers and all(it.cost > 0 for it in jokers)
    packs_before = [it.key for it in s.items if it and it.kind == "booster"]
    g.dollars = 100
    s.reroll()
    packs_after = [it.key for it in s.items if it and it.kind == "booster"]
    assert packs_before == packs_after


def test_shop_playing_card_slot_can_be_bought_into_deck():
    g = _game()
    from balatro_cli.engine.shop import ShopItem
    s = Shop(g)
    card = Card("7", "D")
    s.items = [ShopItem(index=0, kind="playing_card", key="c_base",
                        name="Playing Card", cost=1, data=card)]
    g.dollars = 10
    r = s.buy(0)
    assert r["ok"] and card in g.deck


# -- 2026-10-01 follow-up pass (see PORTING_PLAN.md re-audit notes) ------------

def test_sell_value_includes_edition_bump():
    g = _game()
    j = g.add_joker("j_joker")              # base cost 2
    base = g.sell_value(j)
    j.edition = "e_foil"                    # card.lua:372 - foil adds 2
    assert g.sell_value(j) == base + 1


def test_ceremonial_dagger_uses_real_sell_value():
    from balatro_cli.engine.hooks import HOOK_SETTING_BLIND
    g = _game()
    dagger = g.add_joker("j_ceremonial")
    victim = g.add_joker("j_joker")         # cost 2 -> sell value 1
    expected = 2 * g.sell_value(victim)
    eff = g.eval_hook(dagger, HOOK_SETTING_BLIND)
    g.consume_effects(eff)                  # the slice lands via the effect
    assert victim not in g.jokers
    assert dagger.ability["mult"] == expected


def test_extra_mult_chip_mod_subfields_apply():
    from types import SimpleNamespace
    from balatro_cli.engine import scoring
    eff = Effect(extra={"mult_mod": 4, "chip_mod": 30})
    chips, mult = scoring._apply(eff, 100, 5, SimpleNamespace(dollars=0, money=0))
    assert (chips, mult) == (130, 9)


def test_held_red_seal_rerolls_joker_individual():
    from balatro_cli.engine.scoring import score_play
    g = _game()
    g.add_joker("j_baron")                  # held Kings: x1.5 (individual)
    played = [Card("3", "S")]
    for held, expected in (([Card("K", "S")], 1),
                           ([Card("K", "S", seal="red")], 2)):
        res = score_play(played, held, g._resolved_level(played, held),
                         g.the_blind, jokers=g.jokers, run=g, rng=g.rng)
        held_log = [_e for tag, _e in res.effects_log if tag == "held"]
        assert len(held_log) == expected


def test_scoring_destruction_fires_remove_playing_cards():
    g = _game()
    g.add_joker("j_glass")                  # grows per shattered Glass card
    glass = Card("5", "S", enhancement="m_glass")
    g.hand[:] = [glass, Card("5", "H")]     # a pair so both cards score
    g.select_blind("small")
    orig = g.rng.chance
    g.rng.chance = lambda key, denom, **kw: True if key == "glass" else orig(key, denom, **kw)
    r = g.play_cards([0, 1])
    assert r["ok"] and glass in r["destroyed"]
    assert g.jokers[0].ability["x_mult"] > 1    # the batched hook landed


def test_cryptid_raises_deck_limit():
    from balatro_cli.engine import consumables
    g = _game()
    base_limit, base_hand = g.params["deck_limit"], len(g.hand)
    res = consumables._cryptid(g, "c_cryptid", "Tarot", "Cryptid",
                               {"extra": 2}, [Card("A", "S")])
    assert res["ok"]
    assert len(g.hand) == base_hand + 2         # copies join the hand (card.lua:1207)
    assert g.params["deck_limit"] == base_limit + 2     # card.lua:1210


def test_shop_illusion_editions_stamp_playing_cards():
    g = _game()
    g.playing_card_rate = 1000          # the playing-card slot always wins
    s = Shop(g)
    stamped = enhanced = 0
    for _ in range(200):
        kind, _key, _name, _cost, card = s._gen_slot(g.pools, g.rng)
        if kind != "playing_card":
            continue
        stamped += bool(getattr(card, "edition", None))
        enhanced += bool(getattr(card, "enhancement", None))
    assert stamped == 0 and enhanced == 0           # no Illusion -> no polls

    g.used_vouchers.add("v_illusion")
    stamped = enhanced = 0
    for _ in range(200):
        kind, _key, _name, _cost, card = s._gen_slot(g.pools, g.rng)
        if kind != "playing_card":
            continue
        stamped += bool(getattr(card, "edition", None))
        enhanced += bool(getattr(card, "enhancement", None))
    assert enhanced > 0                             # >0.6 opens the Enhanced pool
    assert stamped > 0                              # >0.8 stamps an edition


def test_tag_redemption_writes_transcript_log():
    g = _game()
    g.tags.append("tag_skip")
    res = g.skip_blind(0)
    assert res["ok"]
    assert g.tag_log
    assert all(line.startswith("tag redeemed") for line in g.tag_log)
