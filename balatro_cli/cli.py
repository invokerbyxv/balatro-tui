"""CLI entrypoint: wires engine <-> input <-> render.

Modes:
  --script auto    scripted auto-player (deterministic, for testing/CI).
  --script manual  (default) single-key interactive loop in raw mode.

All output is line-based scrolling text (never clears, never moves the cursor).
"""

from __future__ import annotations

import argparse
import sys

from . import config
from .engine.game_state import GameState, BlindOffer
from .engine.hand import get_poker_hand_info, evaluate_poker_hand
from .input import keys as keymod
from .render import transcript as T
from .render.writer import Writer

DECK_KEYS = ["b_red", "b_blue", "b_yellow", "b_green", "b_black", "b_abandoned"]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="balatro-cli", description="covert command-line Balatro")
    p.add_argument("--seed", default="1", help="run seed (string, default %(default)s)")
    p.add_argument("--deck", default="b_red", choices=DECK_KEYS, help="starting deck")
    p.add_argument("--script", default="manual", choices=["manual", "auto"],
                   help="input mode")
    p.add_argument("--locale", default="en-us", choices=["en-us", "zh_CN"])
    p.add_argument("--glyphs", action="store_true", help="use Unicode suit glyphs")
    p.add_argument("--ante-cap", type=int, default=8, help="ante at which to stop")
    return p


class Cli:
    def __init__(self, args):
        self.args = args
        self.w = Writer()
        self.glyphs = args.glyphs
        self.selected: list[int] = []
        self.shop = None

    # -- output -----------------------------------------------------------
    def out(self, line: str = ""):
        self.w.out(line)

    # -- run loop ---------------------------------------------------------
    def run(self) -> int:
        self.out(T.run_header(1, self.args.deck, self.args.locale))
        state = GameState(self.args.seed, deck_key=self.args.deck, scaling=1)
        state.start()

        if self.args.script == "auto":
            return self._run_auto(state)
        return self._run_manual(state)

    # -- shared plumbing ---------------------------------------------------
    def _score_resolved_level(self, state):
        """Mirror of game_state._resolved_level for empty-hand display."""
        return state.hand_levels["High Card"]

    # =====================================================================
    #  AUTO MODE
    # =====================================================================
    def _auto_choose(self, state):
        results = evaluate_poker_hand(state.hand, state.joker_flags)
        scoring = results["top"] or [state.hand[0]]
        idx = [state.hand.index(c) for c in scoring if c in state.hand]
        return idx[:5] or [0]

    def _run_auto(self, state) -> int:
        guard = 0
        while state.phase not in ("game_over", "won") and guard < 500:
            guard += 1
            if state.phase == "blind_select":
                for o in state.blind_choices:
                    self.out(f"  blind: {T.blind_offer(state.ante, o)}")
                state.select_blind(state.blind_choices[0].kind)
            elif state.phase == "round":
                self._print_hand(state)
                if state.hands_left:
                    r = state.play_cards(self._auto_choose(state))
                    self.out(f"  {T.play_line(r['score'], won=r.get('won'), glyphs=self.glyphs)}")
                    if r.get("lost"):
                        continue
                else:
                    state.lost_run = True
                    state.phase = "game_over"
            elif state.phase == "round_won":
                self._print_round_end(state)
            elif state.phase == "round_lost":
                state.lost_run = True
                state.phase = "game_over"
            elif state.phase == "shop":
                state.check_run_end(self.args.ante_cap)
                if state.phase in ("game_over", "won"):
                    continue
                state.advance_from_shop()
            else:
                self.out(f"  ? phase {state.phase}")
                break
        state.check_run_end(self.args.ante_cap)
        self._print_end(state)
        return 0 if state.won_run else 1

    def _print_hand(self, state):
        self.out(f"  {T.status(state)}")
        self.out(f"  {T.hand_line(state, self.glyphs)}")

    def _print_round_end(self, state):
        res = state.end_round()
        self.out(f"  {T.round_end(state, res['reward'], res['interest'], res['extra'])}")

    def _print_end(self, state):
        if state.won_run:
            self.out(T.win_message(state))
        else:
            self.out(T.game_over(state))

    # =====================================================================
    #  MANUAL MODE
    # =====================================================================
    def _run_manual(self, state) -> int:
        from .engine.shop import Shop
        self._state = state
        self.shop = Shop(state)
        self._show_blind_prompt(state) if state.phase == "blind_select" else None
        while state.phase not in ("game_over", "won"):
            try:
                ch = keymod.read_key()
            except (EOFError, KeyboardInterrupt):
                raise _Quit()
            self._dispatch(ch)
            if state.phase == "round_lost" or state.phase == "game_over":
                state.check_run_end(self.args.ante_cap)
        self._print_end(state)
        return 0 if state.won_run else 1

    def _dispatch(self, ch: str):
        state = self._state
        if ch == "q":
            raise _Quit()
        if ch in ("\r", "\n", "n"):
            ch = "enter"
        if state.phase == "blind_select":
            self._on_blind_select(ch)
        elif state.phase == "round":
            self._on_round(ch)
        elif state.phase == "round_won":
            self._on_round_won(ch)
        elif state.phase == "shop":
            self._on_shop(ch)

    def _on_blind_select(self, ch: str):
        state = self._state
        choices = state.blind_choices
        if ch == "enter":
            state.select_blind(choices[0].kind)   # enter -> first (small)
            self._print_hand(state)
            return
        idx = {"1": 0, "2": 1}.get(ch)
        if idx is None or idx >= len(choices):
            self._show_blind_prompt(state)
            return
        state.select_blind(choices[idx].kind)
        self._print_hand(state)

    def _on_round(self, ch: str):
        state = self._state
        if ch in ("1", "2", "3", "4", "5", "6", "7", "8"):
            i = int(ch) - 1
            if i < len(state.hand):
                if i in self.selected:
                    self.selected.remove(i)
                else:
                    self.selected.append(i)
            self.out(T.prompt_select(state, self.selected))
        elif ch in ("p", " ", "enter"):
            if not self.selected:
                self.selected = [0]
            r = state.play_cards(self.selected)
            self.selected = []
            if not r["ok"]:
                self.out(f"  {r.get('error', '?')}")
                return
            self.out(T.play_line(r["score"], won=r.get("won"), glyphs=self.glyphs))
            if r.get("won"):
                self._on_round_won(ch)   # transition straight to shop
        elif ch in ("d", "x"):
            if not self.selected:
                self.out("  select cards first (1-8)")
                return
            r = state.discard_cards(self.selected)
            self.selected = []
            if not r["ok"]:
                self.out(f"  {r.get('error', '?')}")
            else:
                self.out(T.discard_line(state, r["dropped"], len(r["drawn"]), self.glyphs))
            self.out(f"{T.status(state)}")
        elif ch == "?":
            self.out("  keys: 1-8 select  p/space play  d/x discard  q quit")

    def _on_round_won(self, ch: str):
        state = self._state
        self._print_round_end(state)
        state.phase = "shop"
        self._enter_shop_ui()

    def _enter_shop_ui(self):
        state = self._state
        self.out(T.shop_line(state, self.shop))

    def _on_shop(self, ch: str):
        state = self._state
        self.shop.active = True
        if ch == "s":
            state.advance_from_shop()
            self._on_blind_select_after(state)
            return
        if ch == "r":
            r = self.shop.reroll()
            if r["ok"]:
                self.out(f"  reroll ${r['cost']} -> ${r['remaining']}")
            else:
                self.out(f"  {r['error']}")
        elif ch in ("1", "2", "3", "4", "5"):
            r = self.shop.buy(int(ch) - 1)
            if r["ok"]:
                self.out(f"  bought {r['item'].name} (-${r['item'].cost}) -> ${r['remaining']}")
            else:
                self.out(f"  {r['error']}")
        elif ch == "?":
            self.out("  shop: 1-5 buy  r reroll  s leave  q quit")
            return
        self._enter_shop_ui()

    def _on_blind_select_after(self, state):
        if state.phase == "blind_select":
            self._show_blind_prompt(state)
        elif state.phase == "game_over":
            self._print_end(state)

    def _show_blind_prompt(self, state):
        for i, o in enumerate(state.blind_choices, 1):
            self.out(f"  {i}:{T.blind_offer(state.ante, o)}")
        self.out("  > pick blind (1/2/3)")

    def _quit(self):
        raise _Quit()


class _Quit(Exception):
    pass


def _boss_kind(state) -> bool:
    return any(o.kind == "boss" for o in getattr(state, "blind_choices", []))


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cli = Cli(args)
        return cli.run()
    except _Quit:
        return 0
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())