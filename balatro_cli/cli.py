"""CLI entrypoint: wires engine <-> input <-> render.

Modes:
  --script auto    scripted auto-player (deterministic, for testing/CI).
  --script manual  (default) single-key interactive loop in raw mode.

All output is line-based scrolling text (never clears, never moves the cursor).

Commands
--------
blind select   ``1``/``2``/``3`` play that blind, ``k`` skip it for a tag
round          ``1``-``8`` toggle cards, ``p``/space play, ``d`` discard,
               ``c<N>`` use consumable N, ``i`` show info, ``?`` help
shop           ``1``-``9`` buy, ``r`` reroll, ``s`` leave, ``c<N>`` use
               consumable N, ``x<N>`` sell joker N, ``i`` info
pack           ``1``-``n`` toggle a card, ``enter`` take the selection
anywhere       ``q`` quit
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

DECK_KEYS = ["b_red", "b_blue", "b_yellow", "b_green", "b_black", "b_magic",
             "b_nebula", "b_ghost", "b_abandoned", "b_checkered", "b_zodiac",
             "b_painted", "b_anaglyph", "b_plasma", "b_erratic"]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="balatro-cli", description="covert command-line Balatro")
    p.add_argument("--seed", default="1", help="run seed (string, default %(default)s)")
    p.add_argument("--deck", default="b_red", choices=DECK_KEYS, help="starting deck")
    p.add_argument("--script", default="manual", choices=["manual", "auto"],
                   help="input mode")
    p.add_argument("--locale", default="en-us", choices=["en-us", "zh_CN"])
    p.add_argument("--glyphs", action="store_true", help="use Unicode suit glyphs")
    p.add_argument("--ante-cap", type=int, default=8, help="ante at which to stop")
    p.add_argument("--auto-skip", action="store_true",
                   help="auto mode: skip blinds for tags instead of playing them")
    p.add_argument("--auto-buy", action="store_true",
                   help="auto mode: buy jokers/consumables in the shop")
    return p


class Cli:
    def __init__(self, args):
        self.args = args
        self.w = Writer()
        self.glyphs = args.glyphs
        self.selected: list[int] = []
        self.shop = None
        self._pending: str | None = None
        self._pack = None
        self._pack_selection: list[int] = []

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
        from .engine.shop import Shop
        guard = 0
        self.shop = Shop(state)
        while state.phase not in ("game_over", "won") and guard < 800:
            guard += 1
            if state.phase == "blind_select":
                for i, o in enumerate(state.blind_choices, 1):
                    self.out(f"  {i}:{T.blind_offer(state.ante, o)}")
                if self.args.auto_skip and len(state.blind_choices) == 2:
                    res = state.skip_blind(0)
                    self.out(f"  {T.skip_line(res)}")
                else:
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
                self._auto_shop(state)
                state.advance_from_shop()
            else:
                self.out(f"  ? phase {state.phase}")
                break
        state.check_run_end(self.args.ante_cap)
        self._print_end(state)
        return 0 if state.won_run else 1

    def _auto_shop(self, state) -> None:
        self.shop.active = True
        if not self.shop.items:
            self.shop.refill()
        self.out(f"  {T.shop_line(state, self.shop)}")
        if not self.args.auto_buy:
            return
        for item in list(self.shop.all_items()):
            if item.kind in ("joker", "consumable") and state.dollars >= item.cost:
                r = self.shop.buy(item.index)
                if r.get("ok"):
                    self.out(f"  bought {item.name} (-${item.cost}) -> ${state.dollars}")

    def _print_hand(self, state):
        self.out(f"  {T.status(state)}")
        self.out(f"  {T.hand_line(state, self.glyphs)}")

    def _print_round_end(self, state):
        res = state.end_round()
        self.out(f"  {T.round_end(state, res['reward'], res['interest'], res['extra'], res.get('money'))}")

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
        if state.phase == "blind_select":
            self._show_blind_prompt(state)
        else:
            self._print_hand(state)
        while state.phase not in ("game_over", "won"):
            try:
                ch = keymod.read_key()
            except (EOFError, KeyboardInterrupt):
                raise _Quit()
            if ch is None:
                continue
            try:
                self._dispatch(ch)
            except _Quit:
                raise
            except Exception as exc:   # keep the transcript alive on bad input
                self.out(f"  ! {type(exc).__name__}: {exc}")
            if state.phase in ("round_lost", "game_over"):
                state.check_run_end(self.args.ante_cap)
        self._print_end(state)
        return 0 if state.won_run else 1

    # -- command plumbing --------------------------------------------------
    def _dispatch(self, raw: str):
        state = self._state
        cmd = (raw or "").strip()
        if cmd in ("\r", "\n"):
            cmd = ""
        # normalize: "enter"/"space" words plus two-key sequences like "c1"
        low = cmd.lower()
        if low in ("enter", ""):
            key, arg = "enter", ""
        elif low == "space":
            key, arg = " ", ""
        elif low.startswith("\\x03") or low == "ctrl-c":
            key, arg = "q", ""
        else:
            key, arg = low[0], low[1:]

        if key == "q":
            raise _Quit()

        # two-key sequences
        if self._pending in ("c", "x"):
            pending, self._pending = self._pending, None
            if pending == "c":
                self._use_consumable(arg or key, state)
            else:
                self._sell(arg or key, state)
            return

        if self._pack is not None:
            self._on_pack(key, arg, state)
            return

        if state.phase == "blind_select":
            self._on_blind_select(key, arg, state)
        elif state.phase == "round":
            self._on_round(key, arg, state)
        elif state.phase == "round_won":
            self._on_round_won(state)
        elif state.phase == "shop":
            self._on_shop(key, arg, state)

    # -- blind select ------------------------------------------------------
    def _on_blind_select(self, key: str, arg: str, state):
        if key == "k":
            res = state.skip_blind(0)
            self.out(f"  {T.skip_line(res)}")
            if state.phase == "blind_select":
                self._show_blind_prompt(state)
            return
        if key == "b":
            info = state.boss_reroll_info()
            if info.get("available"):
                r = state.reroll_boss()
                if r.get("ok"):
                    self.out(f"  boss rerolled (-${r['cost']}) -> ${r['remaining']}")
                else:
                    self.out(f"  {r.get('error')}")
            else:
                self.out("  no boss reroll available (Director's Cut required)")
            self._show_blind_prompt(state)
            return
        if key == "enter":
            state.select_blind(state.blind_choices[0].kind)
            self._print_hand(state)
            return
        if key in ("1", "2", "3"):
            idx = int(key) - 1
            if idx >= len(state.blind_choices):
                self._show_blind_prompt(state)
                return
            state.select_blind(state.blind_choices[idx].kind)
            self._print_hand(state)
            return
        if key == "?":
            self._help("blind")
            return
        self._show_blind_prompt(state)

    # -- round -------------------------------------------------------------
    def _on_round(self, key: str, arg: str, state):
        if key in ("1", "2", "3", "4", "5", "6", "7", "8"):
            i = int(key) - 1
            if i < len(state.hand):
                card = state.hand[i]
                if card.ability.pop("wheel_flipped", None) is not None:
                    # clicking a face-down card reveals it (blind face-down rules)
                    self.out(T.hand_line(state, self.glyphs))
                    return
                if i in self.selected:
                    self.selected.remove(i)
                else:
                    self.selected.append(i)
            self.out(T.prompt_select(state, self.selected))
        elif key in ("p", " ", "enter"):
            if not self.selected:
                self.selected = [0]
            r = state.play_cards(self.selected)
            self.selected = []
            if not r["ok"]:
                self.out(f"  {r.get('error', '?')}")
                return
            self.out(T.play_line(r["score"], won=r.get("won"), glyphs=self.glyphs))
            if r.get("won"):
                self._on_round_won(state)
            elif r.get("lost"):
                self.out("  out of hands")
        elif key in ("d", "x"):
            if not self.selected:
                self.out("  select cards first (1-8)")
                return
            r = state.discard_cards(self.selected)
            self.selected = []
            if not r["ok"]:
                self.out(f"  {r.get('error', '?')}")
            else:
                self.out(T.discard_line(state, r["dropped"], len(r["drawn"]), self.glyphs))
            self.out(f"  {T.status(state)}")
        elif key == "c":
            self._pending = "c"
            self.out(f"  {T.consumables_line(state)}")
            self.out("  > use which consumable? (1-9)")
        elif key == "i":
            self._print_info(state)
        elif key == "?":
            self._help("round")

    def _print_info(self, state):
        self.out(f"  {T.blind_line(state)}")
        self.out(f"  {T.hand_info_line(state, self.glyphs)}")
        self.out(f"  {T.jokers_line(state)}")
        self.out(f"  {T.consumables_line(state)}")
        if state.tags:
            self.out(f"  {T.tags_line(state)}")
        if state.vouchers:
            self.out(f"  {T.vouchers_line(state)}")

    def _use_consumable(self, index_s: str, state):
        try:
            idx = int(index_s) - 1
        except (TypeError, ValueError):
            self.out("  > bad consumable index")
            return
        if not 0 <= idx < len(state.consumeables):
            self.out("  > no such consumable")
            return
        # highlighted hand cards are the targets (Lua G.hand.highlighted)
        targets = [state.hand[i] for i in sorted(self.selected)
                   if 0 <= i < len(state.hand)]
        key = getattr(state.consumeables[idx], "key", "")
        try:
            from .engine import consumables as cons
            if not cons.can_use(state, key, targets):
                self.out(f"  > cannot use {key} now"
                         f" ({len(targets)} card(s) highlighted)")
                return
        except ImportError:
            pass
        r = state.use_consumable(idx, targets=targets)
        self.out(f"  use -> {r}")
        self.out(f"  {T.status(state)}")

    def _sell(self, index_s: str, state):
        try:
            idx = int(index_s) - 1
        except (TypeError, ValueError):
            self.out("  > bad index")
            return
        r = state.sell_joker(idx)
        if r["ok"]:
            self.out(f"  sold {r['sold']} +${r['price']} -> ${r['remaining']}")
        else:
            self.out(f"  {r['error']}")
        self.out(f"  {T.status(state)}")

    def _on_round_won(self, state):
        self._print_round_end(state)
        self._enter_shop_ui()

    def _enter_shop_ui(self):
        state = self._state
        self.shop.active = True
        self.shop.refill()
        self.out(T.shop_line(state, self.shop))
        if getattr(self.shop, "vouchers", None):
            self.out(T.shop_voucher_line(self.shop))
        self.out(T.shop_prompt(self.shop, state))

    # -- shop --------------------------------------------------------------
    def _on_shop(self, key: str, arg: str, state):
        self.shop.active = True
        if key == "s":
            state.advance_from_shop()
            if state.phase == "blind_select":
                self._show_blind_prompt(state)
            elif state.phase == "game_over":
                self._print_end(state)
            return
        if key == "r":
            r = self.shop.reroll()
            if r["ok"]:
                self.out(f"  reroll ${r['cost']} -> ${r['remaining']}")
            else:
                self.out(f"  {r['error']}")
        elif key == "c":
            self._pending = "c"
            self.out(f"  {T.consumables_line(state)}")
            self.out("  > use which consumable? (1-9)")
            return
        elif key == "x":
            self._pending = "x"
            self.out(f"  {T.jokers_line(state)}")
            self.out("  > sell which joker? (1-9)")
            return
        elif key == "i":
            self._print_info(state)
        elif key == "?":
            self._help("shop")
            return
        elif key.isdigit():
            r = self.shop.buy(int(key) - 1)
            if not r["ok"]:
                self.out(f"  {r['error']}")
            else:
                self.out(f"  bought {r['item'].name} (-${r['item'].cost}) -> ${r['remaining']}")
                if r.get("pack"):
                    self._begin_pack(r["pack"])
        else:
            self.out(T.shop_prompt(self.shop, state))
            return
        if self._pack is not None:
            return
        self.out(T.shop_line(state, self.shop))
        if getattr(self.shop, "vouchers", None):
            self.out(T.shop_voucher_line(self.shop))
        self.out(T.shop_prompt(self.shop, state))

    # -- booster packs -----------------------------------------------------
    def _begin_pack(self, pack: dict):
        if not pack or not pack.get("ok"):
            self.out("  pack -> (nothing)")
            return
        self._pack = pack
        self._pack_selection = []
        self.out(f"  {T.pack_line(pack, self.glyphs)}")
        self.out(f"  > pick {pack.get('choose', 1)} (numbers, enter=confirm)")

    def _on_pack(self, key: str, arg: str, state):
        pack = self._pack
        cards = pack.get("cards", [])
        if key == "s":
            r = state.skip_pack(pack)
            self.out(f"  pack skipped ({r.get('skipped')})")
            self._pack = None
            self._pack_selection = []
            self.out(T.shop_line(state, self.shop))
            self.out(T.shop_prompt(self.shop, state))
            return
        if key == "enter":
            if not self._pack_selection:
                self._pack_selection = [0]
            r = state.take_from_pack(pack, self._pack_selection)
            self.out(f"  pack -> {r.get('taken') or r.get('error') or 'taken'}")
            self._pack = None
            self._pack_selection = []
            self.out(T.shop_line(state, self.shop))
            self.out(T.shop_prompt(self.shop, state))
            return
        if key.isdigit():
            i = int(key) - 1
            if 0 <= i < len(cards):
                if i in self._pack_selection:
                    self._pack_selection.remove(i)
                else:
                    self._pack_selection.append(i)
            self.out(f"  {T.pack_line(pack, self.glyphs)}")
            self.out(f"  > selected {[i + 1 for i in self._pack_selection]}")
            return
        self.out(f"  {T.pack_line(pack, self.glyphs)}")

    # -- help --------------------------------------------------------------
    def _help(self, where: str):
        if where == "blind":
            self.out("  keys: 1/2/3 play a blind  k skip (gain a tag)  q quit")
        elif where == "round":
            self.out("  keys: 1-8 select  p/space play  d discard  c# use consumable"
                     "  i info  q quit")
        else:
            self.out("  shop: 1-9 buy  r reroll  c# use consumable  x# sell joker"
                     "  i info  s leave  q quit")

    def _show_blind_prompt(self, state):
        for i, o in enumerate(state.blind_choices, 1):
            self.out(f"  {i}:{T.blind_offer(state.ante, o)}")
        if state.tags:
            self.out(f"  {T.tags_line(state)}")
        self.out("  > pick blind (1/2/3) or k=skip for a tag")


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
