"""Tag-system tests: data asset, pool culling, and every ported effect.

The effect tables only use the documented duck-typed run API, so `FakeRun`
implements just what each tag touches (and nothing else).
"""

from __future__ import annotations

from balatro_cli.data import loader
from balatro_cli.engine import tags
from balatro_cli.engine.card import Card, JokerCard
from balatro_cli.engine.hooks import Context
from balatro_cli.engine.rng import RNG

MIN_ANTE_TWO = {
    "tag_negative", "tag_standard", "tag_meteor", "tag_buffoon", "tag_handy",
    "tag_garbage", "tag_ethereal", "tag_top_up", "tag_orbital",
}


class FakeItem:
    def __init__(self, key, cost):
        self.key = key
        self.cost = cost


class FakeShop:
    def __init__(self, items=()):
        self.items = list(items)
        self.reroll_cost = 5


class FakeRun:
    """Only the run API the tag handlers actually use."""

    def __init__(self, seed="tags-seed", dollars=4, ante=1):
        self.rng = RNG(seed)
        self.tags: list[str] = []
        self.dollars = dollars
        self.ante = ante
        self.hand_size = 8
        self.hand_levels = {k: {"level": 1} for k in ("Flush", "Pair", "High Card")}
        self.jokers: list = []
        self.params = {"joker_slots": 5}
        self.current_round: dict = {}
        self.last_blind: dict = {}
        self.pending_packs: list[str] = []
        self.created: list = []
        self.leveled: list[tuple[str, int]] = []

    # -- factories ---------------------------------------------------------
    def create_card(self, kind, rarity=None, edition=None, **kw):
        pool = loader.pools()["JokerRarity"][rarity or 1]
        entry = self.rng.pick("fake_card", pool)
        card = JokerCard(entry["key"], entry.get("name", entry["key"]),
                         dict(entry.get("config") or {}), rarity=rarity or 1,
                         edition=edition)
        self.created.append(card)
        return card

    def add_joker(self, key, edition=None):
        card = JokerCard(key, key, {"rarity": 1}, edition=edition)
        self.jokers.append(card)
        return card

    def add_tag(self, key):
        self.tags.append(key)
        if getattr(self, "tag_double_pending", False) and key != "tag_double":
            self.tags.append(key)
            self.tag_double_pending = False

    def level_up_hand(self, hand, amount=1):
        self.leveled.append((hand, amount))
        entry = self.hand_levels.setdefault(hand, {"level": 1})
        entry["level"] = int(entry.get("level", 1)) + amount


def fire(run, key, event, **kw):
    """Hold `key` then call Tag:apply_to_run once with `event`."""
    run.tags.append(key)
    return tags.apply(run, key, Context(event=event, run=run, extra=dict(kw)))


# ---------------------------------------------------------------------------
# data asset / pool / random selection
# ---------------------------------------------------------------------------

def test_tags_asset_and_pool():
    assert len(loader.tags()) == 24
    pool = loader.pools()["Tag"]
    assert len(pool) == 24
    assert pool[0]["key"] == "tag_uncommon"          # ordered by `order`
    assert pool[-1]["key"] == "tag_economy"
    assert pool[6]["key"] == "tag_investment"
    assert loader.tags()["tag_investment"]["config"]["dollars"] == 25
    assert loader.tags()["tag_economy"]["config"]["max"] == 40


def test_tag_pool_respects_min_ante():
    early = tags.tag_pool(1)
    assert len(early) == 24 - len(MIN_ANTE_TWO)
    assert not (MIN_ANTE_TWO & set(early))
    assert tags.tag_pool(2) == [e["key"] for e in loader.pools()["Tag"]]
    assert len(tags.tag_pool(2)) == 24
    assert tags.tag_pool(None) == early               # no ante -> ante 1


def test_random_tag_deterministic_for_fixed_seed():
    a = FakeRun("fixed-seed")
    b = FakeRun("fixed-seed")
    first = [tags.random_tag(a, 1, "small") for _ in range(5)]
    second = [tags.random_tag(b, 1, "small") for _ in range(5)]
    assert first == second
    assert all(k in tags.tag_pool(1) for k in first)


def test_random_tag_never_returns_gated_tag_early():
    run = FakeRun("gated")
    assert all(tags.random_tag(run, 1, "small") not in MIN_ANTE_TWO for _ in range(40))


# ---------------------------------------------------------------------------
# economy tags
# ---------------------------------------------------------------------------

def test_skip_tag_pays_five_per_skip():
    run = FakeRun()
    run.skips = 1
    res = fire(run, "tag_skip", "immediate")
    assert res["dollars"] == 5
    run2 = FakeRun()
    run2.skips = 3
    assert fire(run2, "tag_skip", "immediate")["dollars"] == 15


def test_handy_tag_pays_per_hand_played():
    run = FakeRun()
    run.current_round = {"hands_played": 7}
    assert fire(run, "tag_handy", "immediate")["dollars"] == 7


def test_garbage_tag_pays_per_discard():
    run = FakeRun()
    run.current_round = {"discards_used": 4}
    assert fire(run, "tag_garbage", "immediate")["dollars"] == 4


def test_economy_tag_doubles_capped_at_40():
    run = FakeRun(dollars=30)
    assert fire(run, "tag_economy", "immediate")["dollars"] == 30
    rich = FakeRun(dollars=100)
    assert fire(rich, "tag_economy", "immediate")["dollars"] == 40
    broke = FakeRun(dollars=0)
    res = fire(broke, "tag_economy", "immediate")
    assert res is not None and res["dollars"] == 0


def test_investment_tag_only_after_boss_blind():
    run = FakeRun()
    run.last_blind = {"boss": True}
    res = fire(run, "tag_investment", "eval")
    assert res["dollars"] == 25
    assert res["extra"]["condition"] == "ph_defeat_the_boss"

    plain = FakeRun()
    plain.last_blind = {"boss": False}
    assert fire(plain, "tag_investment", "eval") is None


def test_juggle_tag_adds_three_hand_size():
    run = FakeRun()
    res = fire(run, "tag_juggle", "round_start_bonus")
    assert run.round_bonus["h_size"] == 3
    assert run.hand_size == 11
    assert res["extra"]["h_size"] == 3


def test_tag_events_do_not_cross_fire():
    run = FakeRun()
    run.skips = 1
    run.tags.append("tag_skip")
    ctx = Context(event="round_start_bonus", run=run)
    assert tags.apply(run, "tag_skip", ctx) is None
    assert run.tags == ["tag_skip"]                  # still held


# ---------------------------------------------------------------------------
# shop / store tags
# ---------------------------------------------------------------------------

def test_voucher_tag_adds_a_voucher():
    run = FakeRun()
    res = fire(run, "tag_voucher", "voucher_add")
    assert run.pending_vouchers == [1]
    assert res["extra"]["vouchers"] == 1


def test_d_six_tag_makes_rerolls_free_once():
    run = FakeRun()
    run.shop = FakeShop()
    run.reroll_cost = 5
    res = fire(run, "tag_d_six", "shop_start")
    assert res["extra"]["reroll_cost"] == 0
    assert run.reroll_cost == 0 and run.shop.reroll_cost == 0
    assert fire(run, "tag_d_six", "shop_start") is None   # once per shop


def test_coupon_tag_frees_the_shop():
    run = FakeRun()
    run.shop = FakeShop([FakeItem("j_joker", 5), FakeItem("p_arcana", 4)])
    res = fire(run, "tag_coupon", "shop_final_pass")
    assert res["extra"]["shop_free"] is True
    assert [i.cost for i in run.shop.items] == [0, 0]
    bare = FakeRun()                                  # no shop yet -> held
    assert fire(bare, "tag_coupon", "shop_final_pass") is None
    assert bare.tags == ["tag_coupon"]


def test_top_up_tag_creates_two_common_jokers():
    run = FakeRun()
    res = fire(run, "tag_top_up", "immediate")
    assert res["extra"]["count"] == 2
    assert len(run.jokers) == 2
    assert all(j.ability["rarity"] == 1 for j in run.jokers)


def test_uncommon_tag_creates_a_free_uncommon_joker():
    run = FakeRun()
    res = fire(run, "tag_uncommon", "store_joker_create")
    assert res["extra"]["rarity"] == 2
    card = res["extra"]["card"]
    assert card.ability["rarity"] == 2
    assert card.ability["couponed"] is True
    assert run.jokers == []                           # shop stock, not owned


def test_rare_tag_creates_a_free_rare_joker():
    run = FakeRun()
    res = fire(run, "tag_rare", "store_joker_create")
    assert res["extra"]["rarity"] == 3
    assert res["extra"]["card"].ability["rarity"] == 3
    assert res["extra"]["card"].ability["couponed"] is True


def test_edition_tags_set_the_edition():
    expected = {"tag_foil": "e_foil", "tag_holo": "e_holo",
                "tag_polychrome": "e_polychrome", "tag_negative": "e_negative"}
    for key, edition in expected.items():
        run = FakeRun()
        card = JokerCard("j_joker", "Joker", {"set": "Joker"}, rarity=1)
        res = fire(run, key, "store_joker_modify", card=card)
        assert card.edition == edition
        assert card.ability["couponed"] is True
        assert res["extra"]["edition"] == edition


def test_edition_tag_skips_non_jokers_and_edited_cards():
    run = FakeRun()
    assert fire(run, "tag_foil", "store_joker_modify", card=Card("A", "S")) is None
    run2 = FakeRun()
    edited = JokerCard("j_joker", "Joker", {"set": "Joker"}, edition="e_foil")
    assert fire(run2, "tag_holo", "store_joker_modify", card=edited) is None


def test_pack_tags_queue_the_matching_mega_pack():
    expected = {
        "tag_charm": "p_arcana_mega_",
        "tag_meteor": "p_celestial_mega_",
        "tag_ethereal": "p_spectral_normal_1",
        "tag_standard": "p_standard_mega_1",
        "tag_buffoon": "p_buffoon_mega_1",
    }
    for key, pack in expected.items():
        run = FakeRun()
        res = fire(run, key, "new_blind_choice")
        assert len(run.pending_packs) == 1
        queued = run.pending_packs[0]
        if pack.endswith("_"):                       # mega pack 1 or 2
            assert queued.startswith(pack) and queued[-1] in "12"
        else:
            assert queued == pack
        assert res["extra"]["pack"] == queued


def test_boss_tag_rerolls_the_boss_blind():
    run = FakeRun()
    res = fire(run, "tag_boss", "new_blind_choice")
    assert run.boss_reroll_pending is True
    assert res["extra"]["reroll_boss"] is True
    assert run.pending_packs == []


def test_orbital_tag_levels_a_hand_three_times():
    run = FakeRun()
    hand = tags._record_orbital_choice(run, run.ante, "small")
    res = fire(run, "tag_orbital", "immediate")
    assert res["extra"] == {"hand": hand, "levels": 3}
    assert run.leveled == [(hand, 3)]
    assert run.hand_levels[hand]["level"] == 4


# ---------------------------------------------------------------------------
# Double Tag + consumption
# ---------------------------------------------------------------------------

def test_double_tag_copies_the_next_tag_gained():
    run = FakeRun()
    run.tags = ["tag_double"]
    run.add_tag("tag_investment")
    fired = tags.apply_tags(run, "tag_add", tag="tag_investment")
    assert [f["key"] for f in fired] == ["tag_double"]
    assert fired[0]["extra"]["copied"] == "tag_investment"
    assert run.tags == ["tag_investment", "tag_investment"]


def test_double_tag_never_copies_another_double_tag():
    run = FakeRun()
    run.tags = ["tag_double"]
    run.add_tag("tag_double")
    assert tags.apply_tags(run, "tag_add", tag="tag_double") == []
    assert run.tags == ["tag_double", "tag_double"]   # still held, no copy


def test_double_tag_pending_for_the_next_tag():
    run = FakeRun()
    run.tags = ["tag_double"]
    assert tags.apply_tags(run, "tag_add") == []      # nothing to copy yet
    assert run.tag_double_pending is True
    run.add_tag("tag_skip")
    assert run.tags == ["tag_double", "tag_skip", "tag_skip"]


def test_fired_tag_is_consumed():
    run = FakeRun()
    run.skips = 1
    run.tags = ["tag_skip"]
    fired = tags.apply_tags(run, "immediate")
    assert len(fired) == 1 and fired[0]["key"] == "tag_skip"
    assert run.tags == []


def test_unmatched_tag_stays_held_and_apply_is_idempotent():
    run = FakeRun()
    run.skips = 1
    run.tags = ["tag_skip"]
    assert tags.apply_tags(run, "eval") == []
    assert run.tags == ["tag_skip"]
    ctx = Context(event="immediate", run=run)
    assert tags.apply(run, "tag_skip", ctx)["dollars"] == 5
    assert tags.apply(run, "tag_skip", ctx) is None   # already triggered
    assert run.tags == ["tag_skip"]


def test_two_copies_both_fire():
    run = FakeRun()
    run.current_round = {"hands_played": 3}
    run.tags = ["tag_handy", "tag_handy"]
    fired = tags.apply_tags(run, "immediate")
    assert [f["dollars"] for f in fired] == [3, 3]
    assert run.tags == []


def test_apply_tags_first_only_mirrors_lua_break():
    run = FakeRun()
    run.tags = ["tag_charm", "tag_meteor"]
    fired = tags.apply_tags(run, "new_blind_choice", first_only=True)
    assert len(fired) == 1
    assert run.tags == ["tag_meteor"]


def test_every_tag_has_a_handler_and_a_name():
    for key, entry in loader.tags().items():
        assert key in tags.TAG_HANDLERS
        assert entry["config"]["type"] in tags.EVENTS
        assert tags.name_of(key).endswith("Tag")
        assert tags.describe(key)
    assert tags.name_of("tag_skip") == "Skip Tag"
    assert tags.apply(FakeRun(), "tag_nope", Context(event="immediate")) is None
