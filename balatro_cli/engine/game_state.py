"""Run / round state machine, ported from state_events.lua (new_round/end_round)

Drive the Balatro loop:
  deck_select -> blind_select -> round (play | discard) -> round_end
  (reward + interest) -> shop -> next blind | ante++ -> ...

Chips accumulate across hands within a round until the blind is defeated.

The engine exposes a small API the CLI (render/input) wires to keys, and a
scripted auto-player for deterministic smoke tests (see `play_auto`).
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from .. import config
from .card import Card
from .deck import build_standard_deck
from .blind import Blind
from .hand import JokerFlags, get_poker_hand_info
from .rng import RNG
from .scoring import score_play
from ..data import loader

BLIND_KINDS = ("small", "big", "boss")


@dataclass
class BlindOffer:
    kind: str
    key: str
    name: str
    dollars: int
    chips: int
    mult: float


class GameState:
    def __init__(self, seed: str, deck_key: str = "b_red", scaling: int = 1):
        self.rng = RNG(str(seed))
        self.seed = str(seed)
        self.deck_key = deck_key
        self.scaling = scaling

        self.params = dict(config.STARTING_PARAMS)
        self._apply_deck(deck_key)

        self.hand_levels = {k: {**dict(v), "level": 1} for k, v in config.HAND_LEVELS.items()}
        self.pools = loader.pools()

        no_faces = deck_key == "b_abandoned"
        self.deck: list[Card] = build_standard_deck(no_faces)
        self.rng.shuffle("deck", self.deck)

        self.hand: list[Card] = []
        self.played: list[Card] = []          # discarded/played pile (single draw pile)
        self.jokers: list = []
        self.consumeables: list = []
        self.vouchers: list = []
        self.tags: list = []

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

        self._last_score = None
        self.joker_flags = JokerFlags()

    # -- startup ------------------------------------------------------------
    def _apply_deck(self, deck_key: str) -> None:
        deltas = config.DECK_DELTAS.get(deck_key, {})
        numeric = ("discards", "hands", "dollars", "hand_size", "joker_slots",
                   "consumable_slots", "ante_scaling", "reroll_cost")
        for k, v in deltas.items():
            if k in numeric and isinstance(v, (int, float)):
                self.params[k] = self.params.get(k, 0) + v
            elif k == "no_interest":
                self.params["no_interest"] = v

    def start(self) -> None:
        self.ante = 1
        self.blind_index = 1
        self.phase = "blind_select"
        self._offer_blinds()

    # -- blinds -------------------------------------------------------------
    def _offer_blinds(self) -> list[BlindOffer]:
        bd = loader.blinds()
        offers = []
        if self.blind_index == 3:
            offers.append(_boss_offer(self, bd))
        else:
            small = bd["bl_small"]
            big = bd["bl_big"]
            offers.append(_make_offer(self, "small", "bl_small", small))
            offers.append(_make_offer(self, "big", "bl_big", big))
        self.blind_choices = offers
        self.phase = "blind_select"
        return offers

    def select_blind(self, choice) -> None:
        """choice: BlindOffer.kind ('small'/'big'/'boss') or a key index."""
        offer = next((o for o in self.blind_choices
                      if o.kind == choice or o.key == choice), None)
        if offer is None:
            try:
                offer = self.blind_choices[int(choice)]
            except (ValueError, IndexError):
                offer = self.blind_choices[0]
        self.the_blind = Blind(offer.key, {"name": offer.name, "dollars": offer.dollars,
                                           "mult": offer.mult, "boss": offer.kind == "boss",
                                           "debuff": _debuff_for(offer.key)},
                               self.ante, self.scaling)
        self._start_round()

    def _start_round(self) -> None:
        self.hands_left = self.params["hands"]
        self.discards_left = self.params["discards"]
        self.reroll_cost = self.params["reroll_cost"]
        self.chips = 0
        self._draw_to_handsize()
        self.phase = "round"

    def _draw_to_handsize(self) -> None:
        need = self.hand_size - len(self.hand)
        while need > 0 and self.deck:
            self.hand.append(self.deck.pop())
            need -= 1
        if not self.deck:
            self.deck.extend(self.played)
            self.played.clear()
            self.deck = self.rng.shuffle("redeal", self.deck)

    # -- actions ------------------------------------------------------------
    def reveal_hand(self) -> tuple[str, list[Card]]:
        return get_poker_hand_info(self.hand, self.joker_flags)

    def play_cards(self, indices: list[int]) -> dict:
        idx = [i for i in indices if 0 <= i < len(self.hand)]
        if not 1 <= len(idx) <= 5 or not self.hands_left:
            return {"ok": False, "error": "cannot play"}
        played = [self.hand[i] for i in sorted(idx, reverse=True)]
        for c in played:
            self.hand.remove(c)
        held = list(self.hand)
        level = self._resolved_level(played, held)
        result = score_play(played, held, level, self.the_blind,
                            jokers=self.jokers, flags=self.joker_flags)
        self.chips += result.score
        self.hands_left -= 1
        self.played.extend(played)
        self._last_score = result
        self._draw_to_handsize()

        won = self.the_blind.is_defeated(self.chips)
        self.last_round_won = won
        if won:
            self.phase = "round_won"
        elif self.hands_left == 0:
            self.phase = "round_lost"
        return {"ok": True, "score": result, "won": won, "lost": self.phase == "round_lost"}

    def discard_cards(self, indices: list[int]) -> dict:
        if not self.discards_left:
            return {"ok": False, "error": "no discards"}
        idx = [i for i in indices if 0 <= i < len(self.hand)]
        if not idx:
            return {"ok": False, "error": "select cards"}
        dropped = [self.hand[i] for i in sorted(idx, reverse=True)]
        for c in dropped:
            self.hand.remove(c)
        self.discards_left -= 1
        self.played.extend(dropped)
        self._draw_to_handsize()
        return {"ok": True, "dropped": dropped, "drawn": len(dropped)}

    def _resolved_level(self, played, held) -> dict:
        hand_key, _ = get_poker_hand_info(played, self.joker_flags)
        base = self.hand_levels[hand_key]
        lvl = base.get("level", 1)
        return {
            "chips": base["chips"] + base["s_chips"] * (lvl - 1),
            "mult": base["mult"] + base["s_mult"] * (lvl - 1),
            "level": lvl,
        }

    def hand_money(self, card: Card) -> int:
        return 3 if card.enhancement == "m_gold" else 0

    # -- round end ----------------------------------------------------------
    def end_round(self) -> dict:
        """Called when a blind is won: reward + interest, -> phase 'shop'."""
        reward = 0
        if self.the_blind:
            reward = self.the_blind.dollars
        self.dollars += reward
        interest = self._interest()
        self.dollars += interest
        # hand/discard money from Gold cards
        extra = sum(self.hand_money(c) for c in self.hand)
        self.dollars += extra
        # tag "handy"/"garbage" ignored for now
        self._enter_shop()
        return {"reward": reward, "interest": interest, "extra": extra}

    def _enter_shop(self) -> None:
        self.phase = "shop"
        self.reroll_cost = self.params["reroll_cost"]

    def advance_from_shop(self) -> None:
        """Next blind: boss defeated -> ante++ & new batch; else next in ante."""
        defeated_boss = bool(self.the_blind and self.the_blind.is_boss and self.last_round_won)
        if self.the_blind and self.the_blind.is_boss:
            self.used_bosses.append(self.the_blind.key)
        if defeated_boss:
            self.ante += 1
            self.blind_index = 1
        else:
            self.blind_index += 1
        self.round_num += 1
        self.chips = 0
        self.the_blind = None
        self._offer_blinds()

    def _interest(self) -> int:
        if self.params.get("no_interest"):
            return 0
        held = max(0, int(self.dollars))
        return config.INTEREST_AMOUNT * min(held // 5, config.INTEREST_CAP // 5)

    # -- loss / win ---------------------------------------------------------
    def check_run_end(self, ante_cap: int = 8) -> None:
        if self.phase == "round_lost":
            self.lost_run = True
            self.phase = "game_over"
        elif self.the_blind and self.phase == "round_won" and self.ante >= ante_cap \
                and self.the_blind.is_boss:
            self.won_run = True
            self.phase = "won"


# -- helpers ----------------------------------------------------------------

def _boss_offer(state, bd) -> BlindOffer:
    bosses = [b for b in bd.values()
              if isinstance(b, dict) and b.get("boss") and not b.get("showdown")]
    eligible = [b for b in bosses
                if (b["boss"].get("min") or 1) <= state.ante <= (b["boss"].get("max") or 10)
                and b.get("key") not in state.used_bosses]
    if state.ante >= 8:
        for b in bd.values():
            if isinstance(b, dict) and b.get("boss") and b.get("showdown"):
                eligible.append(b)
    pool = eligible or bosses or list(bd.values())
    b = state.rng.pick("boss" + str(state.ante), pool)
    return _make_offer(state, "boss", b.get("key", "bl_boss"), b)


def _make_offer(state: GameState, kind: str, key: str, b) -> BlindOffer:
    mult = b.get("mult", 2 if kind == "boss" else 1)
    from .blind import get_blind_amount
    chips = int(get_blind_amount(state.ante, state.scaling) * mult * state.scaling)
    return BlindOffer(kind=kind, key=key, name=b.get("name", kind),
                      dollars=b.get("dollars", 3), chips=chips, mult=mult)


def _debuff_for(key: str) -> dict:
    bd = loader.blinds()
    return bd.get(key, {}).get("debuff", {}) or {}