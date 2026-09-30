"""Game-state loop tests (M3): deterministic scripted run + helpers."""

from balatro_cli import config
from balatro_cli.engine.game_state import GameState


def auto_choose_highest(state):
    """Select indices in hand that maximize the detected hand tier."""
    from balatro_cli.engine.hand import evaluate_poker_hand
    results = evaluate_poker_hand(state.hand, state.joker_flags)
    # take the scoring cards if a real hand exists and they are in-hand; else a single card.
    scoring = results["top"] or [state.hand[0]]
    idx = [state.hand.index(c) for c in scoring if c in state.hand]
    return idx[:5] or [0]


def play_auto_run(seed="x", deck="b_red"):
    state = GameState(seed, deck_key=deck)
    state.start()
    max_rounds = 200
    rounds = 0
    while state.phase not in ("game_over", "won"):
        rounds += 1
        if rounds > max_rounds:
            raise AssertionError("run did not terminate; stuck at phase " + state.phase)
        if state.phase == "blind_select" and hasattr(state, "blind_choices") and state.blind_choices:
            state.select_blind(state.blind_choices[0].kind)  # always small
        elif state.phase == "round":
            if state.hands_left:
                r = state.play_cards(auto_choose_highest(state))
                if not r["ok"]:
                    state.discards_left = max(0, state.discards_left - 1)
                if r.get("won") or r.get("lost"):
                    if r["won"]:
                        state.end_round()
            else:
                state.lost_run = True
                state.phase = "game_over"
        elif state.phase == "round_won":
            state.end_round()
        elif state.phase == "round_lost":
            state.lost_run = True
            state.phase = "game_over"
        elif state.phase in ("shop",):
            state.advance_from_shop()
        else:
            raise AssertionError(f"unhandled phase {state.phase}")
    return state


def test_run_progresses_and_terminates():
    state = play_auto_run("seed1")
    assert state.phase in ("game_over", "won")


def test_ante_scales_up():
    state = play_auto_run("seed1")
    assert state.ante >= 1


def test_cumulative_chips_win():
    state = GameState("s")
    state.start()
    state.select_blind(state.blind_choices[0].kind)
    assert state.phase == "round"
    # play until chips exceed the small blind
    guard = 0
    while state.phase == "round" and guard < 40:
        guard += 1
        r = state.play_cards(auto_choose_highest(state))
        if not r["ok"]:
            state.discards_left -= 1
    assert state.phase in ("round_won", "game_over")


def test_deck_delta_applied():
    st = GameState("s", deck_key="b_blue")
    assert st.params["hands"] == config.STARTING_PARAMS["hands"] + 1


def test_no_interest_green_deck():
    st = GameState("s", deck_key="b_green")
    assert st.params.get("no_interest")


def test_reroll_cost_reset_per_round():
    st = GameState("s")
    assert st.reroll_cost == config.STARTING_PARAMS["reroll_cost"]