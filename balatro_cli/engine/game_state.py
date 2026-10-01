"""Run / round state machine.

Ported from:
* ``state_events.lua:new_round`` (~290) and ``end_round`` (~87)
* ``state_events.lua:G.FUNCS.evaluate_round`` (~1135) - the round-end money rows
* ``functions/button_callbacks.lua`` - blind select/skip, shop entry, selling
* ``functions/common_events.lua:create_card`` / ``level_up_hand`` / ``add_joker``

The loop::

    deck_select -> blind_select -> round (play | discard) -> round_won
      -> round_end (blind reward + leftover hands + interest) -> shop
      -> next blind | ante++ | game over | won

Chips accumulate across hands within a round until the blind is defeated.

The engine exposes a small API that the CLI (render/input) wires to keys, and a
scripted auto-player for deterministic smoke tests.  Everything an effect table
needs is documented in ``engine/PORTING.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math

from .. import config
from .card import Card, JokerCard, ability_from_config, normalize_seal
from .deck import build_standard_deck
from .blind import Blind, get_blind_amount
from .hand import JokerFlags, get_poker_hand_info, evaluate_poker_hand
from .hooks import (AREA_CONSUMEABLES, AREA_HAND, AREA_JOKERS, AREA_PLAY,
                    HOOK_BLIND_DEFEATED, HOOK_BUYING_CARD, HOOK_CARD_ADDED,
                    HOOK_CARD_REMOVED, HOOK_DISCARD, HOOK_DISCARD_HAND,
                    HOOK_END_OF_ROUND, HOOK_ENDING_SHOP, HOOK_EVAL,
                    HOOK_FIRST_HAND_DRAWN,
                    HOOK_HAND_DRAWN, HOOK_OPEN_BOOSTER, HOOK_POST_DISCARD,
                    HOOK_PRE_DISCARD, HOOK_REMOVE_PLAYING_CARDS,
                    HOOK_PLAYING_CARD_ADDED, HOOK_REROLL_SHOP, HOOK_ROUND_START, HOOK_SELLING_CARD,
                    HOOK_SELLING_SELF, HOOK_SETTING_BLIND, HOOK_SHOP_FINAL_PASS,
                    HOOK_SHOP_START, HOOK_SKIP_BLIND, HOOK_SKIPPING_BOOSTER,
                    HOOK_USE_CONSUMABLE,
                    Context, Effect, merge)
from .rng import RNG
from .scoring import score_play
from ..data import loader

BLIND_KINDS = ("small", "big", "boss")

# G.GAME.round_resets defaults (game.lua ~1979)
ROUND_BONUS_DEFAULT = {"h_size": 0, "d_size": 0, "next_hands": 0, "discards": 0}


@dataclass
class BlindOffer:
    kind: str
    key: str
    name: str
    dollars: int
    chips: int
    mult: float
    skipped: bool = False


@dataclass
class RoundMoney:
    """One row of `evaluate_round`'s money table."""

    reward: int = 0
    hands: int = 0
    discards: int = 0
    jokers: int = 0
    tags: int = 0
    interest: int = 0
    gold: int = 0
    rows: list = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.reward + self.hands + self.discards + self.jokers + self.tags + self.interest + self.gold


class GameState:
    def __init__(self, seed: str, deck_key: str = "b_red", scaling: int = 1,
                 stake: int = 1):
        self.rng = RNG(str(seed))
        self.seed = str(seed)
        self.deck_key = deck_key
        # `scaling` selects the blind-amount table (stake 3/6 raise it);
        # `ante_scaling` multiplies blind chips (Plasma Deck) - blind.lua:107
        self.scaling = scaling
        self.ante_scaling = 1
        self.stake = stake

        self.params = dict(config.STARTING_PARAMS)
        # G.deck card area limit (game.lua:2251); Cryptid/DNA/Marble Joker add
        # to it when they put a card in the deck (card.lua:1210/2595/3506)
        self.params.setdefault("deck_limit", 52)
        # -- G.GAME.modifiers / round_resets / current_round ------------------
        self.modifiers: dict = {}
        # stake modifiers (game.lua:2048-2057)
        if stake >= 2:
            self.modifiers.setdefault("no_blind_reward", {})["Small"] = True
        if stake >= 3:
            self.modifiers["scaling"] = 2
        if stake >= 5:
            self.params["discards"] = self.params.get("discards", 3) - 1
        if stake >= 6:
            self.modifiers["scaling"] = 3
        if isinstance(scaling, int) and scaling > 1 and "scaling" not in self.modifiers:
            self.modifiers["scaling"] = scaling
        self.scaling = int(self.modifiers.get("scaling", 1) or 1)
        self.round_bonus = dict(ROUND_BONUS_DEFAULT)
        self.current_round: dict = {
            "hands_played": 0, "discards_used": 0, "hands_left": 0,
            "discards_left": 0, "free_rerolls": 0, "used_packs": [],
            "most_played_poker_hand": "High Card", "voucher": None,
            "reroll_cost_increase": 0,
        }
        self.interest_amount = config.INTEREST_AMOUNT
        self.interest_cap = config.INTEREST_CAP
        self.used_vouchers: set[str] = set()
        self.used_jokers: set[str] = set()
        self.banned_keys: set[str] = set()
        self.pool_flags: dict = {}
        self.last_blind: dict = {}
        self.pending_packs: list[str] = []
        self.skipped_blinds: list[str] = []
        self.tag_double_pending = False
        # run-level tallies (G.GAME.* in the Lua; several jokers/tags read them)
        self.skips = 0                        # G.GAME.skips (reset each ante)
        self.hands_played_total = 0           # G.GAME.hands_played
        self.unused_discards = 0              # G.GAME.unused_discards
        self.driver_tally = 0                 # face cards gained this run
        self.idol_card: dict = {}
        self.mail_card: dict = {}
        self.ancient_card: dict = {}
        self.castle_card: dict = {}
        # sum of owned jokers' ability h_size / d_size (add_to_deck/remove_from_deck)
        self.joker_hand_mod = 0
        self.joker_discard_mod = 0
        self.joker_hands_mod = 0
        self.bankrupt_at = 0
        self.shop = None
        self.shop_size = config.SHOP_SIZE
        self.booster_slots = config.BOOSTER_SLOTS
        self.voucher_slots = 1
        # shop card-slot weights (game.lua:1901-1905); tarot/planet store the
        # merchant-voucher multiplier over a base weight of 4
        self.joker_rate = 20
        self.tarot_rate = 1
        self.planet_rate = 1
        self.playing_card_rate = 0
        self.edition_rate = 1
        self.spectral_rate = 0
        self.reroll_cost_delta = 0
        self.no_blind_reward: dict[str, bool] = {}

        self.hand_levels = {}
        for k, v in config.HAND_LEVELS.items():
            self.hand_levels[k] = {**dict(v), "level": 1, "played": 0,
                                   "played_this_round": 0, "visible": v.get("visible", True)}
        self.pools = loader.pools()

        # collections must exist before the deck back is applied (a back may
        # grant starting vouchers and consumables)
        self.hand: list[Card] = []
        self.played: list[Card] = []          # discard pile (played + discarded)
        self.jokers: list[JokerCard] = []
        self.consumeables: list[JokerCard] = []
        self.vouchers: list[str] = []
        self.tags: list[str] = []
        # transcript lines for redeemed tags (filled by apply_tags, drained
        # by the CLI so each redemption shows what it did)
        self.tag_log: list[str] = []

        no_faces = deck_key == "b_abandoned"
        self.deck: list[Card] = build_standard_deck(no_faces)
        self._apply_deck(deck_key)
        self.starting_deck_size = len(self.deck)
        self.rng.shuffle("deck", self.deck)

        self.dollars = self.params["dollars"]
        self.ante = 1
        self.blind_index = 1                    # 1 small, 2 big, 3 boss
        self.hands_left = 0
        self.discards_left = 0
        self.hand_size = self.params["hand_size"]
        self.reroll_cost = self.params["reroll_cost"]
        self.chips = 0
        self.the_blind: Blind | None = None
        self.last_round_won = False

        self.phase = "deck_select"
        self.round_num = 1
        self.used_bosses: list[str] = []
        self.won_run = False
        self.lost_run = False
        self.message = ""
        self.last_hand_played: str | None = None
        self.blind_choices: list[BlindOffer] = []

        self._last_score = None
        self.joker_flags = JokerFlags()

    # =====================================================================
    #  startup
    # =====================================================================
    def _apply_deck(self, deck_key: str) -> None:
        """Apply a deck back's starting effects (back.lua + game.lua).

        `backs.setup` owns this: it mutates params / modifiers, grants the
        starting vouchers + consumables and installs the back-specific deck
        (Checkered, Abandoned, Erratic, ...).  The `config.DECK_DELTAS` table is
        only the fallback when `engine/backs.py` cannot be imported.
        """
        plan = None
        try:
            from . import backs as backs_mod
            plan = backs_mod.setup(self, deck_key)
        except Exception:
            plan = None
        if plan is not None:
            self._back_plan = plan
        else:
            self._back_plan = None
            self._apply_deltas_fallback(config.DECK_DELTAS.get(deck_key, {}))
        # legacy accessors some callers/tests still read off `params`
        if self.modifiers.get("no_interest"):
            self.params["no_interest"] = True
        for mod_key, param_key in (("money_per_hand", "extra_hand_bonus"),
                                   ("money_per_discard", "extra_discard_bonus")):
            if mod_key in self.modifiers:
                self.params[param_key] = self.modifiers[mod_key]

    def _apply_deltas_fallback(self, deltas: dict) -> None:
        """`config.DECK_DELTAS` application when `backs.py` is unavailable."""
        numeric = ("discards", "hands", "dollars", "hand_size", "joker_slots",
                   "joker_slot", "consumable_slots", "consumable_slot",
                   "ante_scaling", "reroll_cost")
        for k, v in deltas.items():
            if k in numeric and isinstance(v, (int, float)) and not isinstance(v, bool):
                target = {"joker_slot": "joker_slots",
                          "consumable_slot": "consumable_slots"}.get(k, k)
                self.params[target] = self.params.get(target, 0) + v
            elif k == "no_interest":
                self.modifiers["no_interest"] = bool(v)
                self.params["no_interest"] = bool(v)
            elif k == "extra_hand_bonus":
                self.modifiers["money_per_hand"] = v
                self.params["extra_hand_bonus"] = v
            elif k == "extra_discard_bonus":
                self.modifiers["money_per_discard"] = v
                self.params["extra_discard_bonus"] = v
            elif k in ("randomize_rank_suit", "remove_faces", "voucher",
                       "vouchers", "consumables", "spectral_rate"):
                continue
            else:
                self.modifiers[k] = v

    def start(self) -> None:
        self.ante = 1
        self.blind_index = 1
        self.phase = "blind_select"
        self._offer_blinds()

    # =====================================================================
    #  blinds
    # =====================================================================
    def _offer_blinds(self) -> list[BlindOffer]:
        bd = loader.blinds()
        offers: list[BlindOffer] = []
        if self.blind_index == 3:
            offers.append(self._ante_boss_offer(bd))
        elif self.blind_index == 2:
            offers.append(_make_offer(self, "big", "bl_big", bd["bl_big"]))
            offers.append(self._ante_boss_offer(bd))
        else:
            offers.append(_make_offer(self, "small", "bl_small", bd["bl_small"]))
            offers.append(_make_offer(self, "big", "bl_big", bd["bl_big"]))
            offers.append(self._ante_boss_offer(bd))
        # a Boss Tag / Standard Tag may add extra choices
        for extra in getattr(self, "_extra_blind_choices", []) or []:
            offers.append(extra)
        self._extra_blind_choices = []
        self.blind_choices = offers
        self.phase = "blind_select"
        # Charm/Meteor/Ethereal/Standard/Buffoon/Boss tags open their free pack
        # or reroll the boss on the new blind choice (tag.lua:206-301)
        self.apply_tags("new_blind_choice")
        self._consume_pending_tags()
        return offers

    def _ante_boss_offer(self, bd) -> BlindOffer:
        """This ante's boss offer, drawn once per ante and cached.

        The boss is previewed from the first blind select (game.lua shows all
        three); the cache keeps the previewed key stable across skips and
        prevents extra RNG draws / bosses_used counts.
        """
        cached = getattr(self, "_boss_offer_cache", None)
        if cached is not None and cached[0] == self.ante:
            return cached[1]
        offer = _boss_offer(self, bd)
        self._boss_offer_cache = (self.ante, offer)
        return offer

    def _consume_pending_tags(self) -> None:
        """Land what the pack/boss tags queued (free packs, boss reroll)."""
        packs = getattr(self, "pending_packs", None) or []
        for pack_key in packs:
            try:
                self.open_pack(pack_key)
            except Exception:
                pass
        if packs:
            del getattr(self, "pending_packs")[:]
        if getattr(self, "boss_reroll_pending", False):
            self.boss_reroll_pending = False
            if self.blind_choices and self.blind_choices[-1].kind == "boss":
                self.blind_choices.pop()
            bd = loader.blinds()
            offer = _boss_offer(self, bd)
            self.blind_choices.append(offer)
            self._boss_offer_cache = (self.ante, offer)

    def select_blind(self, choice) -> None:
        """choice: BlindOffer.kind ('small'/'big'/'boss'), a key, or an index."""
        offer = next((o for o in self.blind_choices
                      if o.kind == choice or o.key == choice), None)
        if offer is None:
            try:
                offer = self.blind_choices[int(choice)]
            except (ValueError, IndexError, TypeError):
                offer = self.blind_choices[0]
        if offer.kind == "boss" and self.blind_index != 3:
            offer = self.blind_choices[0]   # boss is preview-only until its turn
        self._start_blind(offer)

    def skip_blind(self, index: int = 0) -> dict:
        """Skip the current blind to gain a tag (no round, no shop)."""
        if self.phase != "blind_select" or not self.blind_choices:
            return {"ok": False, "error": "no blind to skip"}
        if not 0 <= index < len(self.blind_choices):
            return {"ok": False, "error": "bad index"}
        offer = self.blind_choices[index]
        if offer.kind == "boss" and self.modifiers.get("no_skip_boss"):
            return {"ok": False, "error": "cannot skip the boss blind"}
        self.skips += 1
        tag = self.random_tag(self.ante, offer.kind)
        self.add_tag(tag)
        self.skipped_blinds.append(offer.key)
        # immediate tags pay out on the spot (tag.lua:131-205)
        gained = self.apply_tags("immediate")
        # Throwback grows on skips (card.lua:2429-2440)
        self.consume_effects(self.eval_hooks(HOOK_SKIP_BLIND, skipped_blind=True,
                                             blind=offer))
        self._advance_blind_index(offer)
        self._offer_blinds()
        return {"ok": True, "tag": tag, "tag_name": self.tag_name(tag),
                "blind": offer.name, "display": self.tag_text(tag),
                "dollars": gained}

    def tag_text(self, key: str) -> str:
        try:
            from . import tags as tags_mod
            return tags_mod.describe(key)
        except Exception:
            return ""

    def peek_skip_tag(self, blind_kind: str = "small") -> str:
        """Tag key the next skip of `blind_kind` would grant (UI preview)."""
        try:
            from . import tags as tags_mod
            return tags_mod.peek_tag(self, self.ante, blind_kind)
        except Exception:
            return ""

    # -- boss blind reroll (Director's Cut / Retcon, button_callbacks.lua:2786)
    def boss_reroll_info(self) -> dict:
        limit = int(getattr(self, "boss_reroll_limit", 0) or 0)
        if not limit:
            return {"available": False}
        rerolled = int(getattr(self, "boss_reroll_count", 0) or 0)
        if limit > 0 and rerolled >= limit:
            return {"available": False}
        cost = int(getattr(self, "boss_reroll_cost", 10) or 10)
        has_boss = any(o.kind == "boss" for o in self.blind_choices)
        return {"available": self.phase == "blind_select" and has_boss
                and self.dollars >= cost,
                "cost": cost, "left": None if limit < 0 else limit - rerolled}

    def reroll_boss(self) -> dict:
        info = self.boss_reroll_info()
        if not info.get("available"):
            return {"ok": False, "error": "cannot reroll the boss"}
        if self.dollars < info["cost"]:
            return {"ok": False, "error": "not enough money"}
        self.dollars -= info["cost"]
        self.boss_reroll_count = int(getattr(self, "boss_reroll_count", 0) or 0) + 1
        self.blind_choices = [o for o in self.blind_choices if o.kind != "boss"]
        offer = _boss_offer(self, loader.blinds())
        self.blind_choices.append(offer)
        self._boss_offer_cache = (self.ante, offer)
        return {"ok": True, "cost": info["cost"], "remaining": self.dollars}

    def _advance_blind_index(self, offer: BlindOffer) -> None:
        if offer.kind == "boss":
            if not getattr(self, "_ante_advanced", False):
                self.ante += 1
            self._ante_advanced = False
            self.blind_index = 1
        elif offer.kind == "big":
            self.blind_index = 3
        else:
            self.blind_index = 2
        self.round_num += 1
        self.chips = 0
        self.the_blind = None

    def _start_blind(self, offer: BlindOffer) -> None:
        # `Blind:set_blind` (blind.lua:97-99): the selected blind becomes
        # last_blind - what Investment/Anaglyph read at the next eval
        self.last_blind = {"boss": offer.kind == "boss", "name": offer.name}
        self.the_blind = Blind(offer.key, {"name": offer.name, "dollars": offer.dollars,
                                           "mult": offer.mult, "boss": offer.kind == "boss",
                                           "debuff": _debuff_for(offer.key)},
                               self.ante, self.scaling,
                               ante_scaling=self.ante_scaling)
        self._start_round()

    def _start_round(self) -> None:
        """`new_round` (state_events.lua:290)."""
        self.current_round["hands_played"] = 0
        self.current_round["discards_used"] = 0
        self.current_round["reroll_cost_increase"] = 0
        self.current_round["used_packs"] = []
        for v in self.hand_levels.values():
            v["played_this_round"] = 0
        free = self._find_joker_count("Chaos the Clown")
        self.current_round["free_rerolls"] = free
        self._seed_round_cards()
        self.hands_left = max(1, self.params["hands"] + self.round_bonus.get("next_hands", 0)
                              + self.joker_hands_mod)
        self.discards_left = max(0, self.params["discards"] + self.round_bonus.get("discards", 0)
                                 + self.joker_discard_mod)
        self.hand_size = self.params["hand_size"] + self.round_bonus.get("h_size", 0) \
            + self.joker_hand_mod
        self.reroll_cost = max(0, self.params["reroll_cost"] + self.reroll_cost_delta)
        self.round_bonus["next_hands"] = 0
        self.round_bonus["discards"] = 0
        self.round_bonus["h_size"] = 0
        self.round_bonus["d_size"] = 0
        self.chips = 0
        self.skipped_this_round = False
        # Juggle Tag hands its +h_size to this round only (tag.lua:334-343);
        # the handler bumps hand_size directly, so re-zero the bonus it wrote
        self.apply_tags("round_start_bonus")
        self.round_bonus["h_size"] = 0
        self.round_bonus["d_size"] = 0

        # 10. `Blind:set_blind` side effects (hand size, discards, hands-)
        if self.the_blind is not None:
            setter = getattr(self.the_blind, "set_blind_effects", None)
            if setter is not None:
                setter(self)
            else:
                self._default_blind_setup()
            self._refresh_debuffs()

        self.current_round["hands_left"] = self.hands_left
        self.current_round["discards_left"] = self.discards_left

        # setting_blind joker effects (card.lua:2491-2604): Chicot disables the
        # boss blind, Burglar trades discards for hands, ...
        for j in list(self.jokers):
            eff = self.eval_hook(j, HOOK_SETTING_BLIND, blind=self.the_blind)
            if eff is None:
                continue
            if getattr(eff, "disabled_blind", False) and self.the_blind is not None:
                self.the_blind.disabled = True
            hands_add = (getattr(eff, "extra", None) or {}).get("hands_add")
            if hands_add:
                self.hands_left += int(hands_add)
            if (getattr(eff, "extra", None) or {}).get("discards_left") == 0:
                self.discards_left = 0
            self.consume_effects(eff, joker=j)
        self._refresh_joker_flags()

        self._draw_to_handsize()
        self.phase = "round"
        for j in list(self.jokers):
            self.eval_hook(j, HOOK_HAND_DRAWN)
            self.eval_hook(j, HOOK_FIRST_HAND_DRAWN)
        self._refresh_debuffs()

    def _seed_round_cards(self) -> None:
        """The random card references jokers key off (game.lua:1949-1952).

        The Idol / Mail-In Rebate re-roll per ante; the Ancient Joker suit
        cycles through the suit list; the Castle suit is picked per ante.
        """
        suits = ("Spades", "Hearts", "Clubs", "Diamonds")
        ranks = ("2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A")
        self.idol_card = {"rank": self.rng.pick("idol", ranks),
                          "suit": self.rng.pick("idol", list(suits))}
        self.mail_card = {"rank": self.rng.pick("mail", ranks)}
        self.ancient_card = {"suit": suits[(self.ante - 1) % 4]}
        self.castle_card = {"suit": self.rng.pick("castle", list(suits))}

    def _default_blind_setup(self) -> None:
        """Minimal boss side effects when blind.py has no set_blind_effects()."""
        name = getattr(self.the_blind, "name", "")
        if name == "The Water":
            self.discards_left = 0
        elif name == "The Needle":
            self.hands_left = 1
        elif name == "The Manacle":
            self.hand_size = max(0, self.hand_size - 1)

    def _refresh_debuffs(self) -> None:
        """`Blind:debuff_card` for every playing card and joker."""
        if self.the_blind is None:
            return
        fn = getattr(self.the_blind, "debuff_card", None)
        if fn is None:
            return
        flags = self.joker_flags
        for c in self.playing_cards():
            fn(c, run=self, flags=flags)
        for j in self.jokers:
            if not getattr(j, "debuffed", False):
                fn(j, True, run=self, flags=flags)

    def _draw_to_handsize(self, after_action: bool = False) -> None:
        blind = self.the_blind
        if after_action and blind is not None and not blind.disabled \
                and (self.current_round["hands_played"] > 0
                     or self.current_round["discards_used"] > 0) \
                and getattr(blind, "name", "") == "The Serpent":
            # state_events.lua:363 - The Serpent draws exactly 3
            need = min(3, len(self.deck))
        else:
            need = self.hand_size - len(self.hand)
        while need > 0:
            if not self.deck:
                if not self.played:
                    break
                self.deck = self.rng.shuffle("redeal", self.played)
                self.played = []
            card = self.deck.pop()
            self.hand.append(card)
            # cardarea.lua:600 - the blind may keep the drawn card face down
            if blind is not None:
                blind.stay_flipped(AREA_HAND, card, run=self,
                                   hands_played=self.current_round["hands_played"],
                                   discards_used=self.current_round["discards_used"])
            need -= 1

    # =====================================================================
    #  actions
    # =====================================================================
    def reveal_hand(self) -> tuple[str, list[Card]]:
        return get_poker_hand_info(self.hand, self.joker_flags)

    def play_cards(self, indices: list[int]) -> dict:
        idx = sorted({i for i in indices if 0 <= i < len(self.hand)})
        if not 1 <= len(idx) <= 5 or not self.hands_left:
            return {"ok": False, "error": "cannot play"}
        played = [self.hand[i] for i in idx]
        for c in played:
            self.hand.remove(c)
        held = list(self.hand)

        # Blind:press_play (blind.lua:464) - The Hook discards 2 more, The
        # Tooth charges per card, Crimson Heart/The Fish arm themselves
        pp = None
        if self.the_blind is not None:
            pp = self.the_blind.press_play(run=self, cards=played)
            if pp.get("dollars_lost"):
                self.dollars -= int(pp["dollars_lost"])

        results = evaluate_poker_hand(played, self.joker_flags)
        hand_key = results["top_key"] or "High Card"
        self.hand_levels[hand_key]["played"] += 1
        self.hand_levels[hand_key]["played_this_round"] += 1
        self.hand_levels[hand_key]["visible"] = True
        self.last_hand_played = hand_key
        for c in played:                    # The Pillar debuffs these next ante
            c.ability["played_this_ante"] = True

        level = self._resolved_level(played, held)
        result = score_play(played, held, level, self.the_blind,
                            jokers=self.jokers, flags=self.joker_flags,
                            run=self, rng=self.rng)
        self.chips += result.score
        self.hands_left -= 1
        self.current_round["hands_played"] += 1
        self.current_round["hands_left"] = self.hands_left
        self.hands_played_total += 1
        self.dollars += result.dollars
        self._last_score = result
        # land non-scoring side effects gathered during scoring (create specs,
        # joker self-destructs); the dollars were already paid via result
        for _tag, eff in result.effects_log:
            self.consume_effects(eff, apply_dollars=False)

        # destroyed cards leave the game entirely
        for c in result.destroyed:
            self._destroy_card(c)
        self.played.extend(c for c in played if c not in result.destroyed)
        # one batched hook with the whole list (state_events.lua:974-976)
        if result.destroyed:
            self.eval_hooks(HOOK_REMOVE_PLAYING_CARDS,
                            other_card=result.destroyed[-1],
                            extra={"removed": list(result.destroyed)})

        self._draw_to_handsize(after_action=True)
        self._refresh_debuffs()

        won = self.the_blind.is_defeated(self.chips)
        self.last_round_won = won
        if won:
            self.phase = "round_won"
        elif self.hands_left == 0:
            # Mr. Bones / Luchador may still save the run
            if not self._check_save():
                self.phase = "round_lost"
        return {"ok": True, "score": result, "won": won,
                "lost": self.phase == "round_lost",
                "dollars": result.dollars, "destroyed": result.destroyed,
                "debuffed": result.debuffed}

    def _check_save(self) -> bool:
        """`end_of_round` jokers with `saved` (Mr. Bones) can rescue a loss."""
        effects = self.eval_hooks(HOOK_END_OF_ROUND, game_over=True)
        if any(getattr(e, "saved", False) for e in effects):
            self.phase = "round_won"
            self.last_round_won = True
            return True
        return False

    def _destroy_card(self, card: Card) -> None:
        for area in (self.deck, self.hand, self.played):
            if card in area:
                area.remove(card)
        for j in list(self.jokers):
            self.eval_hook(j, HOOK_CARD_REMOVED, other_card=card)

    def discard_cards(self, indices: list[int]) -> dict:
        if not self.discards_left:
            return {"ok": False, "error": "no discards"}
        idx = sorted({i for i in indices if 0 <= i < len(self.hand)})
        if not idx:
            return {"ok": False, "error": "select cards"}
        dropped = [self.hand[i] for i in idx]
        for c in dropped:
            self.hand.remove(c)
        self.discards_left -= 1
        self.current_round["discards_used"] += 1
        self.current_round["discards_left"] = self.discards_left

        # Burnt Joker levels a hand when discarding a played-hand-sized pile
        self.eval_hooks(HOOK_PRE_DISCARD, full_hand=list(dropped),
                        scoring_hand=list(dropped))
        # discard joker effects: Trading Card / Mail-In Rebate / Faceless money,
        # Castle's suit tally
        for c in dropped:
            for eff in self.eval_hooks(HOOK_DISCARD, other_card=c,
                                       full_hand=list(dropped)):
                self.dollars += int(getattr(eff, "dollars", 0) or 0)
                self.consume_effects(eff)
            # Purple seal -> create a Tarot (Card:calculate_seal, context.discard)
            if c.seal == "purple" and not c.debuffed:
                self._create_consumable_of("Tarot")
        for c in dropped:
            c.ability["discarded"] = True
        self.played.extend(dropped)
        self.eval_hooks(HOOK_DISCARD_HAND, full_hand=list(dropped))
        self.eval_hooks(HOOK_POST_DISCARD, full_hand=list(dropped))

        self._draw_to_handsize(after_action=True)
        self._refresh_debuffs()
        return {"ok": True, "dropped": dropped, "drawn": len(dropped)}

    # -- hand levels ---------------------------------------------------------
    def _resolved_level(self, played, held) -> dict:
        hand_key, _ = get_poker_hand_info(played, self.joker_flags)
        base = self.hand_levels[hand_key]
        lvl = base.get("level", 1)
        return {
            "chips": base["chips"] + base["s_chips"] * (lvl - 1),
            "mult": base["mult"] + base["s_mult"] * (lvl - 1),
            "level": lvl,
        }

    def level_up_hand(self, hand_key: str, amount: int = 1) -> None:
        """`common_events.lua:level_up_hand`."""
        entry = self.hand_levels.get(hand_key)
        if entry is None:
            return
        entry["level"] = max(1, entry.get("level", 1) + int(amount))

    def hand_money(self, card: Card) -> int:
        if card.debuffed:
            return 0
        return int(card.ability.get("h_dollars", 0) or 0)

    # =====================================================================
    #  collections (jokers / consumables)
    # =====================================================================
    def add_joker(self, key, edition: str | None = None, **kw) -> JokerCard:
        card = self._make_center_card(key, edition=edition, **kw)
        if card.negative:
            self.params["joker_slots"] = self.params.get("joker_slots", 0) + 1
        self.jokers.append(card)
        # Card:add_to_deck (card.lua:564-651) - size mods & economy
        self._joker_deck_delta(card, +1)
        ab = getattr(card, "ability", None) or {}
        if ab.get("name") == "Loyalty Card":
            ab["hands_played_at_create"] = self.hands_played_total
        if ab.get("name") == "Chicot" and self.the_blind is not None and self.the_blind.is_boss:
            self.the_blind.disabled = True
        self.used_jokers.add(key)
        self._refresh_joker_flags()
        self.eval_hooks(HOOK_CARD_ADDED, other_card=card)
        return card

    def _joker_deck_delta(self, card, sign: int) -> None:
        """The add_to_deck/remove_from_deck size & economy adjustments."""
        ab = getattr(card, "ability", None) or {}
        if not ab:
            return
        extra = ab.get("extra") if isinstance(ab.get("extra"), dict) else {}
        self.joker_hand_mod += sign * int(ab.get("h_size", 0) or 0)
        self.joker_discard_mod += sign * int(ab.get("d_size", 0) or 0)
        name = ab.get("name")
        if name == "Turtle Bean":
            self.joker_hand_mod += sign * int(extra.get("h_size", 5) or 5)
            ab.setdefault("h_mod", extra.get("h_mod", 1) or 1)
        elif name == "Troubadour":
            self.joker_hand_mod += sign * int(extra.get("h_size", 2) or 2)
            self.joker_hands_mod += sign * int(extra.get("h_plays", -1) or -1)
        elif name == "Stuntman":
            self.joker_hand_mod -= sign * int(extra.get("h_size", 2) or 2)
        elif name == "Credit Card":
            self.bankrupt_at -= sign * int(ab.get("extra", 20) or 20)
        elif name == "To the Moon":
            self.interest_amount += sign * int(ab.get("extra", 1) or 1)

    def add_consumable(self, key, edition: str | None = None) -> JokerCard:
        card = self._make_center_card(key, edition=edition)
        if card.negative:
            self.params["consumable_slots"] = self.params.get("consumable_slots", 0) + 1
        self.consumeables.append(card)
        return card

    def _make_center_card(self, key: str, edition: str | None = None, **kw) -> JokerCard:
        center = loader.centers().get(key) or {}
        return JokerCard(key, name=center.get("name", key),
                         cfg=center.get("config") or {},
                         edition=edition,
                         rarity=center.get("rarity", 1),
                         cost=center.get("cost", 0),
                         set_=center.get("set", "Joker"))

    def remove_joker(self, idx: int):
        if 0 <= idx < len(self.jokers):
            card = self.jokers.pop(idx)
            if getattr(card, "negative", False):
                self.params["joker_slots"] = max(0, self.params.get("joker_slots", 1) - 1)
            self._joker_deck_delta(card, -1)     # Card:remove_from_deck (card.lua:645)
            self._refresh_joker_flags()
            return card
        return None

    def remove_consumable(self, idx: int):
        if 0 <= idx < len(self.consumeables):
            return self.consumeables.pop(idx)
        return None

    def sell_joker(self, idx: int) -> dict:
        card = self.jokers[idx] if 0 <= idx < len(self.jokers) else None
        if card is None:
            return {"ok": False, "error": "bad index"}
        self.consume_effects(self.eval_hook(card, HOOK_SELLING_SELF))
        self.eval_hooks(HOOK_SELLING_CARD, other_card=card)
        self.eval_hooks(HOOK_CARD_REMOVED, other_card=card)
        price = self.sell_value(card)
        self.remove_joker(idx)
        self.dollars += price
        return {"ok": True, "sold": card, "price": price, "remaining": self.dollars}

    def sell_consumable(self, idx: int) -> dict:
        card = self.consumeables[idx] if 0 <= idx < len(self.consumeables) else None
        if card is None:
            return {"ok": False, "error": "bad index"}
        price = self.sell_value(card)
        self.remove_consumable(idx)
        self.dollars += price
        return {"ok": True, "sold": card, "price": price, "remaining": self.dollars}

    def sell_value(self, card) -> int:
        """`Card:set_cost` (card.lua:369-382): base cost + edition extra_cost;
        sell = max(1, floor(cost/2)) + ability.extra_value."""
        cost = int(getattr(card, "ability", {}).get("cost", 0) or 0)
        if not cost:
            center = loader.centers().get(getattr(card, "key", "")) or {}
            cost = int(center.get("cost", 0) or 0)
        edition = getattr(card, "edition", None)
        if edition == "e_foil":
            cost += 2
        elif edition == "e_holo":
            cost += 3
        elif edition in ("e_polychrome", "e_negative"):
            cost += 5
        extra = int((getattr(card, "ability", {}) or {}).get("extra_value", 0) or 0)
        return max(1, cost // 2 + extra)

    def joker_at(self, i: int):
        return self.jokers[i] if 0 <= i < len(self.jokers) else None

    def joker_to_right(self, i: int):
        return self.jokers[i + 1] if 0 <= i + 1 < len(self.jokers) else None

    def _find_joker_count(self, name: str) -> int:
        return sum(1 for j in self.jokers if _name_of(j) == name)

    def playing_cards(self) -> list[Card]:
        return [*self.deck, *self.hand, *self.played]

    def _add_playing_card(self, card: Card) -> None:
        """A playing card joined the deck (Stone/Standard packs, DNA, ...)."""
        self.deck.append(card)
        if getattr(card, "is_face", False):
            self.driver_tally += 1
        self.starting_deck_size = max(self.starting_deck_size,
                                      len(self.playing_cards()))
        self.eval_hooks(HOOK_PLAYING_CARD_ADDED, other_card=card)

    def playing_card_destroyed(self, card: Card) -> None:
        self._destroy_card(card)

    # =====================================================================
    #  effect hooks
    # =====================================================================
    def _base_context(self, **kw) -> Context:
        return Context(run=self, **kw)

    def eval_hook(self, joker, event: str, **kw):
        """Run one joker's hook and return its Effect (or None)."""
        from . import jokers as joker_mod
        ctx = self._base_context(event=event, joker=joker, **kw)
        try:
            return joker_mod.calculate(self, joker, ctx)
        except Exception:
            return None

    def eval_hooks(self, event: str, **kw) -> list[Effect]:
        """Run every joker hook for `event`, plus the deck back's trigger."""
        from . import jokers as joker_mod
        out: list[Effect] = []
        for j in list(self.jokers) + list(self.consumeables):
            ctx = self._base_context(event=event, joker=j, **kw)
            try:
                eff = joker_mod.calculate(self, j, ctx)
            except Exception:
                eff = None
            if eff is not None and not getattr(eff, "is_empty", lambda: False)():
                eff.source = j
                out.append(eff)
        return out

    def eval_all_effects(self, event: str, **kw) -> Effect:
        return merge(self.eval_hooks(event, **kw))

    def consume_effects(self, effects, joker=None, apply_dollars: bool = True) -> dict:
        """Land non-scoring side of an Effect (or list of Effects).

        Everything the scoring pass does not apply: ``create`` card specs,
        ``dollars`` (out of scoring), ``extra`` payloads (destroy_joker,
        destroy_self, add_tag, level_up on non-scoring events) and messages.
        ``apply_dollars=False`` when the caller (scoring) already paid them.
        Returns ``{"dollars", "created", "messages", "destroyed_jokers"}``.
        """
        if effects is None:
            return {"dollars": 0, "created": [], "messages": [], "destroyed_jokers": []}
        if not isinstance(effects, (list, tuple)):
            effects = [effects]
        dollars = 0
        created: list = []
        messages: list[str] = []
        destroyed: list = []
        for eff in effects:
            if eff is None:
                continue
            if getattr(eff, "is_empty", lambda: False)():
                continue
            if apply_dollars:
                dollars += int(getattr(eff, "dollars", 0) or 0)
            if getattr(eff, "message", ""):
                messages.append(str(eff.message))
            for hand, amount in _effect_level_ups(eff):
                self.level_up_hand(hand, amount)
            for spec in getattr(eff, "create", None) or []:
                made = self._create_from_spec(spec, joker=joker or getattr(eff, "source", None))
                created.extend(made)
            extra = getattr(eff, "extra", None) or {}
            victim = extra.get("destroy_joker")
            if victim is not None and victim in self.jokers:
                self.jokers.remove(victim)
                destroyed.append(victim)
                self._refresh_joker_flags()
            src = getattr(eff, "source", None) or joker
            if extra.get("destroy_self") and src is not None and src in self.jokers:
                self.jokers.remove(src)
                destroyed.append(src)
                self._refresh_joker_flags()
                if getattr(src, "key", "") == "j_gros_michel":
                    self.pool_flags["gros_michel_extinct"] = True
            tag_key = extra.get("add_tag")
            if tag_key:
                self.add_tag(tag_key)
        self.dollars += dollars
        if messages:
            self.message = messages[-1]
        return {"dollars": dollars, "created": created, "messages": messages,
                "destroyed_jokers": destroyed}

    def _create_from_spec(self, spec: dict, joker=None) -> list:
        """Materialize one ``Effect.create`` spec (the ``create_card`` calls
        scattered through calculate_joker).  Returns the created cards."""
        if not isinstance(spec, dict):
            return []
        kind = spec.get("kind")
        out: list = []
        for _ in range(int(spec.get("count", 1) or 1)):
            if kind in ("Tarot", "Planet", "Spectral"):
                if len(self.consumeables) >= self.params.get("consumable_slots", 0):
                    self.message = "No room!"
                    break
                out.append(self.add_consumable(self._poll_consumable_key(kind)))
            elif kind == "Joker":
                if len(self.jokers) >= self.params.get("joker_slots", 0):
                    self.message = "No room!"
                    break
                out.append(self.add_joker(self._poll_joker_key(int(spec.get("rarity", 1) or 1))))
            elif kind == "copy":
                target = spec.get("card")
                if hasattr(target, "rank"):            # playing card -> deck copy
                    from .card import Card
                    copy = Card(target.rank, target.suit)
                    copy.enhancement = target.enhancement
                    copy.edition = getattr(target, "edition", None)
                    copy.seal = target.seal
                    self._add_playing_card(copy)
                    self.params["deck_limit"] += 1     # card.lua:3506
                    out.append(copy)
                elif target is not None:               # consumable/joker copy
                    key = getattr(target, "key", target)
                    set_ = (loader.centers().get(key) or {}).get("set", "Joker")
                    if set_ == "Joker":
                        if len(self.jokers) >= self.params.get("joker_slots", 0):
                            self.message = "No room!"
                            break
                        out.append(self.add_joker(key))
                    else:
                        if len(self.consumeables) >= self.params.get("consumable_slots", 0):
                            self.message = "No room!"
                            break
                        out.append(self.add_consumable(key))
            elif kind in ("copy_joker", "copy_consumeable"):
                target = spec.get("card")
                key = getattr(target, "key", target)
                if kind == "copy_joker":
                    if len(self.jokers) >= self.params.get("joker_slots", 0):
                        self.message = "No room!"
                        break
                    out.append(self.add_joker(key, edition=getattr(target, "edition", None)))
                else:
                    if len(self.consumeables) >= self.params.get("consumable_slots", 0):
                        self.message = "No room!"
                        break
                    out.append(self.add_consumable(key))
            elif kind == "stone_card":
                from .card import Card
                card = Card(self.rng.pick("marble", ["2", "3", "4", "5", "6", "7", "8", "9", "10"]),
                            self.rng.pick("marble", ["Spades", "Hearts", "Clubs", "Diamonds"]))
                card.enhancement = "m_stone"
                self._add_playing_card(card)
                self.params["deck_limit"] += 1         # card.lua:2595
                out.append(card)
            elif kind == "playing_card":
                card = self.create_card("Base", edition=spec.get("edition"),
                                        seal_random=spec.get("seal_random"),
                                        enhancement=spec.get("enhancement"))
                if card is not None:
                    self._add_playing_card(card)
                    out.append(card)
        return out

    def _poll_consumable_key(self, kind: str) -> str:
        pool = [c for c in (self.pools.get(kind) or [])
                if c.get("key") not in self.banned_keys]
        if not pool:
            pool = self.pools.get(kind) or [{"key": "c_fool"}]
        return self.rng.pick("create_" + kind, pool)["key"]

    def _poll_joker_key(self, rarity: int = 1) -> str:
        try:
            pool = self.pools["JokerRarity"][rarity] or self.pools["Joker"]
        except (KeyError, IndexError):
            pool = self.pools.get("Joker") or []
        pool = [c for c in pool if c.get("key") not in self.banned_keys] or pool
        if not pool:
            return "j_joker"
        return self.rng.pick("create_joker", pool)["key"]


    def _refresh_joker_flags(self) -> None:
        try:
            from . import jokers as joker_mod
            self.joker_flags = joker_mod.joker_flags(self)
        except Exception:
            flags = JokerFlags()
            names = {_name_of(j) for j in self.jokers}
            flags.four_fingers = "Four Fingers" in names
            flags.shortcut = "Shortcut" in names
            flags.smeared = "Smeared Joker" in names
            self.joker_flags = flags
        # Oops! All 6s doubles the luck normal (card.lua:608)
        if self._find_joker_count("Oops! All 6s"):
            self.rng.probabilities_normal = 2
        else:
            self.rng.probabilities_normal = 1

    def back_trigger(self, context: str, **kw):
        """`Back:trigger_effect`."""
        try:
            from . import backs as backs_mod
            return backs_mod.trigger(self, self.deck_key, context, **kw)
        except Exception:
            return None

    # =====================================================================
    #  card creation
    # =====================================================================
    def create_card(self, kind: str = "Base", area: str | None = None, **kw):
        try:
            from . import packs as packs_mod
            card = packs_mod.create_card(self, kind, area=area, **kw)
        except Exception:
            card = self._create_card_fallback(kind, **kw)
        if area == "hand":
            self.hand.append(card)
        elif area == "jokers":
            self.add_joker(getattr(card, "key", card))
        elif area == "consumeables":
            self.add_consumable(getattr(card, "key", card))
        elif area == "deck":
            self.deck.append(card)
        return card

    def _create_card_fallback(self, kind: str, forced_key: str | None = None,
                              rarity: int | None = None, **kw):
        if forced_key:
            return self._make_center_card(forced_key)
        pools = self.pools
        if kind == "Joker":
            pool = pools["JokerRarity"][rarity] if rarity else pools["Joker"]
            pool = [c for c in (pool or pools["Joker"]) if c["key"] not in self.banned_keys]
            if not pool:
                pool = pools["Joker"]
            return self._make_center_card(self.rng.pick("create_joker", pool)["key"])
        if kind in ("Tarot", "Planet", "Spectral"):
            pool = [c for c in pools[kind] if c["key"] not in self.banned_keys] or pools[kind]
            return self._make_center_card(self.rng.pick("create_" + kind, pool)["key"])
        if kind == "Base":
            card = build_standard_deck(False)[self.rng.num("create_base", 0, 51)]
            return card
        if kind == "Enhanced":
            base = self._create_card_fallback("Base")
            pool = pools.get("Enhanced", [])
            if pool:
                base.enhancement = self.rng.pick("create_enhanced", pool)["key"]
                base.ability = ability_from_config(
                    (loader.centers().get(base.enhancement) or {}).get("config"),
                    effect=(loader.centers().get(base.enhancement) or {}).get("effect", ""))
            return base
        return build_standard_deck(False)[0]

    def _create_consumable_of(self, kind: str) -> JokerCard | None:
        if len(self.consumeables) >= self.params.get("consumable_slots", 0):
            return None
        card = self.create_card(kind)
        self.add_consumable(getattr(card, "key", card))
        return card

    # =====================================================================
    #  consumables
    # =====================================================================
    def use_consumable(self, index_or_key, targets=None) -> dict:
        if isinstance(index_or_key, int):
            if not 0 <= index_or_key < len(self.consumeables):
                return {"ok": False, "error": "bad index"}
            card = self.consumeables[index_or_key]
        else:
            card = next((c for c in self.consumeables
                         if getattr(c, "key", c) == index_or_key), None)
            if card is None:
                return {"ok": False, "error": f"no consumable {index_or_key}"}
        key = getattr(card, "key", str(card))
        self.eval_hooks(HOOK_USE_CONSUMABLE, consumable=card)
        try:
            from . import consumables as cons_mod
            if not cons_mod.can_use(self, key, targets):
                return {"ok": False, "error": "cannot use " + key}
            result = cons_mod.use(self, key, targets)
        except ImportError:
            from . import consumable as legacy
            result = legacy.use_consumable(self, key, targets)
        if result.get("ok"):
            self.consumeables.remove(card)
        return result

    # =====================================================================
    #  vouchers / tags / packs
    # =====================================================================
    def redeem_voucher(self, key: str) -> dict:
        if key in self.used_vouchers:
            return {"ok": False, "error": "already redeemed"}
        try:
            from . import vouchers as v_mod
            result = v_mod.redeem(self, key)
        except Exception:
            result = {"ok": True, "key": key, "effects": []}
        if result.get("ok"):
            if key not in self.vouchers:
                self.vouchers.append(key)
            self.used_vouchers.add(key)
        return result

    def _apply_voucher_stats(self, key: str) -> None:
        center = loader.centers().get(key) or {}
        cfg = center.get("config") or {}
        name = center.get("name", key)
        if key == "v_overstock_norm":
            self.shop_size += 1
        elif key == "v_overstock_plus":
            self.shop_size += 1
        elif key == "v_crystal_ball":
            self.params["consumable_slots"] = self.params.get("consumable_slots", 0) + 1
        elif key == "v_antimatter":
            self.params["joker_slots"] = self.params.get("joker_slots", 0) + 1
        elif key == "v_grabber":
            self.params["hands"] = self.params.get("hands", 0) + 1
        elif key == "v_nacho_tong":
            self.params["hands"] = self.params.get("hands", 0) + 1
        elif key == "v_wasteful":
            self.params["discards"] = self.params.get("discards", 0) + 1
        elif key == "v_recyclomancy":
            self.params["discards"] = self.params.get("discards", 0) + 1
        elif key == "v_paint_brush":
            self.params["hand_size"] = self.params.get("hand_size", 0) + 2
        elif key == "v_palette":
            self.params["hand_size"] = self.params.get("hand_size", 0) - 1
        elif key == "v_seed_money":
            self.interest_cap = 50
        elif key == "v_money_tree":
            self.interest_cap = int(cfg.get("extra", 100) or 100)
        elif key == "v_reroll_surplus":
            self.reroll_cost_delta -= 2
        elif key == "v_reroll_glut":
            self.reroll_cost_delta -= 2
        elif key == "v_tarot_merchant":
            self.tarot_rate *= 2
        elif key == "v_tarot_tycoon":
            self.tarot_rate *= 2
        elif key == "v_planet_merchant":
            self.planet_rate *= 2
        elif key == "v_planet_tycoon":
            self.planet_rate *= 2
        elif key == "v_hone":
            self.edition_rate *= 2
        elif key == "v_glow_up":
            self.edition_rate *= 2
        elif key == "v_omen_globe":
            self.spectral_rate = max(1, self.spectral_rate) * 2
        self.message = f"voucher {name}"

    def add_tag(self, key: str) -> None:
        self.tags.append(key)
        # UI_definitions.lua:1252 - the new tag is offered to tag_add tags
        # (Double Tag copies it); guard against reentrancy while the copy's
        # own add_tag fires (the Lua defers via events instead)
        if not getattr(self, "_in_tag_add", False):
            self._in_tag_add = True
            try:
                self.apply_tags("tag_add", tag=key)
            finally:
                self._in_tag_add = False
        doubling = (getattr(self, "tag_double_pending", False)
                    or getattr(self, "_tag_double_pending", False))
        if doubling and key != "tag_double":
            self.tag_double_pending = False
            self._tag_double_pending = False
            self.tags.append(key)
            self.message = "Double Tag!"

    def tag_name(self, key: str) -> str:
        try:
            from . import tags as tags_mod
            return tags_mod.name_of(key)
        except Exception:
            center = (loader.tags() if hasattr(loader, "tags") else {}).get(key) or {}
            return center.get("name", key)

    def random_tag(self, ante: int | None = None, blind_kind: str = "small") -> str:
        try:
            from . import tags as tags_mod
            return tags_mod.random_tag(self, ante if ante is not None else self.ante,
                                       blind_kind)
        except Exception:
            pool = ["tag_investment", "tag_skip", "tag_economy", "tag_handy",
                    "tag_garbage", "tag_voucher", "tag_double", "tag_juggle",
                    "tag_orbital", "tag_top_up", "tag_coupon", "tag_d_six",
                    "tag_boss", "tag_charm", "tag_meteor", "tag_buffoon",
                    "tag_ethereal", "tag_standard"]
            return self.rng.pick("tag" + str(ante), pool)

    def apply_tags(self, event: str, **kw) -> int:
        """Fire held tags whose config.type matches `event`; returns $ gained.

        Every redemption appends a line to ``self.tag_log`` for the transcript.
        """
        try:
            from . import tags as tags_mod
            results = tags_mod.apply_tags(self, event, **kw)
        except Exception:
            return 0
        total = 0
        for res in results or []:
            if isinstance(res, dict):
                total += int(res.get("dollars", 0) or 0)
                line = f"tag redeemed: {self.tag_name(res.get('key', ''))}"
                if res.get("dollars"):
                    line += f" (+${res['dollars']})"
                msg = res.get("message")
                if msg and msg not in line:
                    line += f" - {msg}"
                self.tag_log.append(line)
                if msg:
                    self.message = msg
            elif isinstance(res, Effect):
                total += int(res.dollars or 0)
        self.dollars += total
        return total

    def open_pack(self, pack_key: str) -> dict:
        try:
            from . import packs as packs_mod
            state = packs_mod.open_pack(self, pack_key)
        except Exception:
            return {"ok": False, "error": "packs unavailable"}
        self.current_round.setdefault("used_packs", []).append(pack_key)
        self.eval_hooks(HOOK_OPEN_BOOSTER, pack=state)
        return state

    def take_from_pack(self, pack_state, indices) -> dict:
        try:
            from . import packs as packs_mod
            return packs_mod.take_from_pack(self, pack_state, indices)
        except Exception:
            return {"ok": False, "error": "packs unavailable"}

    def skip_pack(self, pack_state) -> dict:
        """Skip a booster pack (button_callbacks.lua skip_booster)."""
        self.current_round.setdefault("used_packs", []).append(
            getattr(pack_state, "key", None) or
            (pack_state.get("key") if isinstance(pack_state, dict) else None))
        self.eval_hooks(HOOK_SKIPPING_BOOSTER, pack=pack_state)
        return {"ok": True, "skipped": True}

    # =====================================================================
    #  round end
    # =====================================================================
    def end_round(self) -> dict:
        """Called when a blind is won: money rows + interest, -> phase 'shop'."""
        was_boss = bool(self.the_blind is not None and self.the_blind.is_boss)
        # end_of_round jokers first (card.lua end_of_round contexts), then the
        # ROUND_EVAL money rows - the Lua order (state_events.lua:93-247 -> 1135)
        armed = self.eval_hooks(HOOK_END_OF_ROUND, game_over=False)
        self.consume_effects(armed)
        self.unused_discards += max(0, self.discards_left)
        if was_boss:
            self._update_most_played()
        self._blue_seal_planets()
        money = self.calculate_round_money()
        self.dollars += money.total
        # Anaglyph Deck: a Double Tag after every boss blind (back.lua:111-120)
        self.back_trigger("eval")
        if was_boss and self.ante >= 8 and self.blind_index == 3:
            self.won_run = True
            self.phase = "won"
            return {"reward": money.reward, "interest": money.interest,
                    "extra": money.gold, "money": money, "rows": money.rows,
                    "hands": money.hands, "discards": money.discards,
                    "jokers": money.jokers, "tags": money.tags,
                    "total": money.total}
        if was_boss:
            # ante advances right here in the Lua (state_events.lua:248), so the
            # shop pools see the new ante; _advance_blind_index must not re-bump.
            self.ante += 1
            self._ante_advanced = True
            self.boss_reroll_count = 0      # Director's Cut: 1 per ante
            for c in self.playing_cards():
                c.ability["played_this_ante"] = False
            self.skips = 0
        for j in list(self.jokers):
            self._end_of_round_rental(j)
        self._enter_shop()
        return {"reward": money.reward, "interest": money.interest,
                "extra": money.gold, "money": money, "rows": money.rows,
                "hands": money.hands, "discards": money.discards,
                "jokers": money.jokers, "tags": money.tags, "total": money.total}

    def _update_most_played(self) -> None:
        """`G.GAME.current_round.most_played_poker_hand` (state_events.lua:130)."""
        best, best_n = "High Card", -1
        for hand, entry in self.hand_levels.items():
            n = entry.get("played", 0) or 0
            if n > best_n:
                best, best_n = hand, n
        self.current_round["most_played_poker_hand"] = best

    def _blue_seal_planets(self) -> None:
        """`Card:calculate_seal` Blue branch (card.lua:1044-1066): every held
        blue-seal card creates the Planet of the last hand played."""
        hand_key = self.last_hand_played
        if not hand_key:
            return
        for c in list(self.hand):
            if getattr(c, "seal", None) == "blue" and not getattr(c, "debuffed", False):
                if len(self.consumeables) >= self.params.get("consumable_slots", 0):
                    return
                planet = self._planet_for_hand(hand_key)
                if planet:
                    self.add_consumable(planet)
                    self.message = "+1 Planet"

    def _planet_for_hand(self, hand_key: str) -> str | None:
        for c in (self.pools.get("Planet") or []):
            cfg = c.get("config") or {}
            if cfg.get("hand_type") == hand_key:
                return c["key"]
        center = next((cc for cc in (loader.centers() or {}).values()
                       if cc.get("set") == "Planet"
                       and (cc.get("config") or {}).get("hand_type") == hand_key), None)
        return center.get("key") if center else None

    def _end_of_round_rental(self, joker) -> None:
        ability = getattr(joker, "ability", None) or {}
        if ability.get("rental"):
            rate = int(ability.get("rental_rate", 3) or 3)
            self.dollars = max(0, self.dollars - rate)

    def calculate_round_money(self) -> RoundMoney:
        """`G.FUNCS.evaluate_round` (state_events.lua:1135)."""
        m = RoundMoney()
        rows = m.rows
        no_reward = self.modifiers.get("no_blind_reward") or {}
        kind = getattr(self.the_blind, "kind", "") if self.the_blind is not None else ""
        if self.the_blind is not None and self.the_blind.is_defeated(self.chips) \
                and not no_reward.get(kind.capitalize()):
            m.reward = int(self.the_blind.dollars or 0)
            rows.append(("blind", m.reward))
        else:
            rows.append(("blind", 0))

        money_per_hand = int(self.modifiers.get("money_per_hand", 1))
        if self.hands_left > 0 and not self.modifiers.get("no_extra_hand_money"):
            m.hands = self.hands_left * money_per_hand
            if m.hands:
                rows.append(("hands", m.hands))
        money_per_discard = int(self.modifiers.get("money_per_discard", 0) or 0)
        if self.discards_left > 0 and money_per_discard:
            m.discards = self.discards_left * money_per_discard
            rows.append(("discards", m.discards))

        for j in list(self.jokers):
            try:
                from . import jokers as joker_mod
                amount = joker_mod.dollar_bonus(self, j) or 0
            except Exception:
                amount = 0
            if amount:
                m.jokers += amount
                rows.append((f"joker:{getattr(j, 'key', j)}", amount))

        m.tags = self.apply_tags(HOOK_EVAL)
        if m.tags:
            rows.append(("tags", m.tags))

        if self.dollars >= 5 and not self._no_interest():
            m.interest = self.interest_amount * min(self.dollars // 5,
                                                    self.interest_cap // 5)
            rows.append(("interest", m.interest))

        # Gold cards still in hand pay out at the end of the round; a red seal
        # retriggers its own payout (state_events.lua:187-247)
        m.gold = 0
        for c in self.hand:
            pay = self.hand_money(c)
            if not pay:
                continue
            reps = 2 if getattr(c, "seal", None) == "red" else 1
            m.gold += pay * reps
        if m.gold:
            rows.append(("gold", m.gold))
        return m

    def _enter_shop(self) -> None:
        self.phase = "shop"
        self.reroll_cost = max(0, self.params["reroll_cost"] + self.reroll_cost_delta)
        self.eval_hooks(HOOK_SHOP_START)
        self.apply_tags("shop_start")
        if self.shop is not None:
            self.shop.refill()
        # game.lua:3162-3167: voucher_add tags add a shop voucher slot, then
        # shop_final_pass tags (Coupon) zero out the freshly-stocked shop
        self.apply_tags("voucher_add")
        if getattr(self, "pending_vouchers", None):
            self.voucher_slots += len(self.pending_vouchers)
            del self.pending_vouchers[:]
        if self.shop is not None:
            self.shop.refill_vouchers()
        # Rare/Uncommon tags slip a free joker into the card slots, then the
        # Foil/Holo/Polychrome/Negative tags edition the first plain one
        self._apply_store_joker_tags()
        self.apply_tags("shop_final_pass")

    def _apply_store_joker_tags(self) -> None:
        """`store_joker_create` / `store_joker_modify` (tag.lua:344-446)."""
        try:
            from . import tags as tags_mod
        except Exception:
            return
        for item in list(getattr(self.shop, "items", None) or []):
            if item is None or item.kind != "joker":
                continue
            card = getattr(item, "data", None)
            if not hasattr(card, "ability"):
                from .card import JokerCard
                center = loader.centers().get(item.key) or {}
                card = JokerCard(item.key, name=center.get("name", item.key),
                                 cfg=center.get("config") or {},
                                 edition=getattr(card, "edition", None),
                                 rarity=center.get("rarity", 1),
                                 cost=center.get("cost", item.cost),
                                 set_="Joker")
                item.data = card
            item.card = card
            for event in ("store_joker_create", "store_joker_modify"):
                for res in tags_mod.apply_tags(self, event, card=card):
                    made = (res.get("extra") or {}).get("card") if isinstance(res, dict) else None
                    if made is not None and event == "store_joker_create":
                        # the tag's free joker takes this slot
                        item.key = getattr(made, "key", item.key)
                        item.name = getattr(made, "name", item.name)
                        item.cost = 0
                        item.card = made
                        break

    def advance_from_shop(self) -> None:
        """Next blind: boss defeated -> ante++ & new batch; else next in ante."""
        # leaving the shop (button_callbacks.lua:2486): Perkeo & friends
        self.consume_effects(self.eval_hooks(HOOK_ENDING_SHOP))
        blind = self.the_blind
        if blind is not None and blind.is_boss:
            if blind.key not in self.used_bosses:
                self.used_bosses.append(blind.key)
        kind = blind.kind if blind is not None else "small"
        offer = BlindOffer(kind, getattr(blind, "key", "") or "", "", 0, 0, 1)
        self._advance_blind_index(offer)
        self._offer_blinds()

    def _interest(self) -> int:
        if self._no_interest():
            return 0
        held = max(0, int(self.dollars))
        return self.interest_amount * min(held // 5, self.interest_cap // 5)

    def _no_interest(self) -> bool:
        """`G.GAME.modifiers.no_interest` (also mirrored into params for legacy)."""
        return bool(self.modifiers.get("no_interest") or self.params.get("no_interest"))

    # =====================================================================
    #  loss / win
    # =====================================================================
    def check_run_end(self, ante_cap: int = 8) -> None:
        if self.phase == "round_lost":
            self.lost_run = True
            self.phase = "game_over"
        elif self.phase == "round_won" and self.won_run:
            self.phase = "won"

    # =====================================================================
    #  introspection used by the render layer
    # =====================================================================
    @property
    def joker_keys(self) -> list[str]:
        return [getattr(j, "key", str(j)) for j in self.jokers]

    @property
    def consumable_keys(self) -> list[str]:
        return [getattr(c, "key", str(c)) for c in self.consumeables]

    def describe_state(self) -> str:
        return (f"ante {self.ante} blind {self.blind_index} ${self.dollars} "
                f"hand {len(self.hand)}/{self.hand_size} hands {self.hands_left} "
                f"disc {self.discards_left}")


# -- helpers ----------------------------------------------------------------

def _effect_level_ups(eff) -> list[tuple[str, int]]:
    """Normalize an Effect's `level_up` payload to [(hand_key, amount)]."""
    level_up = getattr(eff, "level_up", None)
    if not level_up:
        return []
    if level_up is True:
        return []
    out: list[tuple[str, int]] = []
    for item in level_up:
        if isinstance(item, str):
            out.append((item, 1))
        elif isinstance(item, (tuple, list)) and len(item) == 2:
            out.append((item[0], int(item[1])))
    return out


def _name_of(j) -> str:
    """Center display name for a JokerCard or a bare centers key."""
    if isinstance(j, str):
        return (loader.centers().get(j) or {}).get("name", j)
    return (getattr(j, "ability", None) or {}).get("name", "")


def _boss_offer(state, bd) -> BlindOffer:
    """`get_new_boss` (common_events.lua:2340-2376).

    Non-showdown bosses sit out the win ante (ante % 8 == 0, ante >= 2);
    showdown bosses only appear then; the pick happens among the bosses
    used the *fewest* times; banned keys are excluded.
    """
    win_ante = 8
    used: dict = getattr(state, "bosses_used", None)
    if not isinstance(used, dict):
        used = {}
        state.bosses_used = used
    eligible: list[dict] = []
    for key, raw in bd.items():
        if not isinstance(raw, dict) or not raw.get("boss"):
            continue
        b = dict(raw)
        b.setdefault("key", key)          # blinds.json keys live on the dict
        boss_cfg = b["boss"] or {}
        showdown = bool(boss_cfg.get("showdown"))
        ante = max(1, state.ante)
        if not showdown:
            if not (int(boss_cfg.get("min") or 1) <= ante):
                continue
            if ante % win_ante == 0 and ante >= 2:
                continue
        else:
            if ante % win_ante != 0 or ante < 2:
                continue
        if key in state.banned_keys:
            continue
        eligible.append(b)
    if not eligible:
        eligible = [b for b in bd.values()
                    if isinstance(b, dict) and b.get("boss")] or list(bd.values())
    # restrict to the least-used bosses
    min_use = min(used.get(b.get("key"), 0) for b in eligible) if eligible else 0
    pool = [b for b in eligible if used.get(b.get("key"), 0) <= min_use] or eligible
    b = state.rng.pick("boss" + str(state.ante), pool)
    key = b.get("key") or "bl_boss"
    used[key] = used.get(key, 0) + 1
    if key not in state.used_bosses:
        state.used_bosses.append(key)
    return _make_offer(state, "boss", key, b)


def _make_offer(state: GameState, kind: str, key: str, b) -> BlindOffer:
    mult = b.get("mult", 2 if kind == "boss" else 1)
    chips = int(get_blind_amount(state.ante, state.scaling) * mult
                * getattr(state, "ante_scaling", 1))
    return BlindOffer(kind=kind, key=key, name=b.get("name", kind),
                      dollars=b.get("dollars", 3), chips=chips, mult=mult)


def _debuff_for(key: str) -> dict:
    bd = loader.blinds()
    return bd.get(key, {}).get("debuff", {}) or {}
