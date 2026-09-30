# Porting contract — `balatro_source_code` → `balatro_cli`

This file is the frozen interface between the engine core (`scoring.py`,
`game_state.py`) and the effect tables (`jokers.py`, `consumables.py`,
`tags.py`, `vouchers.py`, `backs.py`, `packs.py`, `blind.py`).

Everything here mirrors the decompiled Lua in `balatro_source_code/`. When in
doubt **the Lua wins** — read it, don't guess.

## Ground rules

* Python 3.11+, stdlib only, no new dependencies.
* Every effect table is a plain module of functions; no classes unless the Lua
  has one.
* Effect handlers return `hooks.Effect | None`. `None` == "no effect" (Lua
  returning nothing).
* Never print. Never touch stdin/stdout. Errors are returned as dicts, not raised
  (except genuine programming errors).
* Keep the existing public names working: `score_play`, `GameState`,
  `Shop`, `consumable.use_consumable`, `config.STARTING_PARAMS`, ….
* Add tests under `balatro_cli/tests/` next to the existing ones and run
  `.venv/Scripts/python.exe -m pytest -q` before reporting done.

## The run object (duck type)

Effect tables must not import `game_state`; they receive the run and use this
API. `GameState` implements exactly this.

### Collections

| attribute | meaning |
|---|---|
| `run.hand` | `list[Card]` — cards currently in hand |
| `run.deck` | `list[Card]` — face-down draw pile |
| `run.played` | `list[Card]` — discard pile (played + discarded cards) |
| `run.jokers` | `list[JokerCard]` — owned jokers, index 0 leftmost |
| `run.consumeables` | `list[JokerCard]` — tarots/planets/spectrals |
| `run.vouchers` | `list[str]` — redeemed voucher keys |
| `run.tags` | `list[str]` — held tag keys |
| `run.playing_cards()` | every `Card` in deck+hand+played (`G.playing_cards`) |

### Numbers / state

| attribute | meaning |
|---|---|
| `run.dollars`, `run.ante`, `run.round_num` | economy / progression |
| `run.hands_left`, `run.discards_left` | current round counters |
| `run.hand_size` | current hand size (`G.hand.config.card_limit`) |
| `run.chips` | chips banked this round (`G.GAME.chips`) |
| `run.the_blind` | `blind.Blind` or `None` |
| `run.params` | starting params dict (`hands`, `discards`, `hand_size`, `joker_slots`, `consumable_slots`, `reroll_cost`) |
| `run.modifiers` | `dict` mirroring `G.GAME.modifiers` (`no_interest`, `money_per_hand`, `money_per_discard`, `no_blind_reward`, `no_extra_hand_money`, …) |
| `run.current_round` | `dict` mirroring `G.GAME.current_round` (`hands_played`, `hands_left`, `discards_used`, `discards_left`, `most_played_poker_hand`, `free_rerolls`, …) |
| `run.hand_levels` | `dict[hand_name] -> {chips, mult, s_chips, s_mult, l_chips, l_mult, level, played, played_this_round, order, visible}` |
| `run.rng` | `engine.rng.RNG` (`roll`, `chance`, `pick`, `shuffle`, `weighted_pick`) |
| `run.used_vouchers` | `set[str]` |
| `run.used_bosses` | `list[str]` |
| `run.banned_keys` | `set[str]` — keys removed from pools (G.GAME.banned_keys) |
| `run.pool_flags` | `dict` — `G.GAME.pool_flags` (e.g. `gros_michel_extinct`) |
| `run.starting_deck_size` | `int` (`G.GAME.starting_deck_size`) |
| `run.joker_flags` | `engine.hand.JokerFlags` (`four_fingers`, `shortcut`, `smeared`, `pareidolia`, `oops_six`) |

### Methods

| call | meaning |
|---|---|
| `run.add_joker(key, edition=None) -> JokerCard` | emplace a joker (respects slot limit; negative edition grants a slot) |
| `run.add_consumable(key) -> JokerCard` | emplace a consumable (respects slot limit) |
| `run.remove_joker(idx)` / `run.remove_consumable(idx)` | remove by index |
| `run.create_card(kind, **kw) -> Card \| JokerCard` | `common_events.lua:create_card`. `kind` ∈ `Joker`, `Tarot`, `Planet`, `Spectral`, `Enhanced`, `Base`, `Standard` |
| `run.level_up_hand(hand_key, amount=1)` | `common_events.lua:level_up_hand` |
| `run.eval_hooks(event, **kwargs) -> list[Effect]` | run every joker hook + voucher hook for `event` |
| `run.joker_at(i)` / `run.joker_to_right(i)` | Blueprint / Brainstorm helpers |
| `run.playing_card_destroyed(card)` | move a destroyed card to the discard pile and fire hooks |
| `run.add_tag(key)` | append a tag; fires `tag_add` tags (Double Tag) with `tag=<key>` |
| `run.random_tag(ante, blind_kind) -> str` | pool-correct random tag (`get_next_tag_key`) |
| `run.free_rerolls` | int, `G.GAME.current_round.free_rerolls` |
| `run.shop` | `Shop` or `None` |
| `run.consume_effects(effects, joker=None, apply_dollars=True) -> dict` | land the non-scoring side of Effect(s): `create` specs, `dollars`, `destroy_joker`/`destroy_self`/`add_tag`, messages. The scoring pass already pays dollars, so it calls this with `apply_dollars=False`. |
| `run.skip_pack(pack_state)` | booster skipped; fires `skipping_booster` (Red Card) |
| `run.boss_reroll_info() / run.reroll_boss()` | Director's Cut / Retcon boss reroll |
| `run._add_playing_card(card)` | a playing card joined the deck (`playing_card_added`, Driver's License/Hologram tallies) |

### Run attributes added in the 2026-10 completion pass

| attribute | meaning |
|---|---|
| `run.skips` | `G.GAME.skips` (reset when an ante advances) |
| `run.hands_played_total` / `run.unused_discards` | run-level `G.GAME.hands_played` / `G.GAME.unused_discards` |
| `run.idol_card` / `run.mail_card` / `run.ancient_card` / `run.castle_card` | per-round random card refs (game.lua:1949) |
| `run.joker_hand_mod` / `run.joker_discard_mod` / `run.joker_hands_mod` | sums of owned jokers' `h_size`/`d_size`/`h_plays` (add_to_deck) |
| `run.bankrupt_at` | Credit Card overdraft allowance (negative) |
| `run.ante_scaling` | blind chip multiplier (Plasma); `run.scaling` only picks the amount table |
| `run.bosses_used` / `run.boss_reroll_limit` / `run.boss_reroll_cost` / `run.boss_reroll_count` | boss selection + Director's Cut |
| `run.used_jokers` | every joker key ever owned (pool dedup, `get_current_pool`) |
| `run.joker_rate` / `run.playing_card_rate` | shop slot weights (20 / 0 by default); `tarot_rate`/`planet_rate` are multipliers over base 4 |

### Additional hook events fired by the engine

| event | fired at |
|---|---|
| `pre_discard` | `discard_cards`, before the cards leave the hand (Burnt Joker) |
| `ending_shop` | `advance_from_shop` (Perkeo) |
| `skipping_booster` | `skip_pack` (Red Card) |
| `buying_card` | every shop purchase (`other_card` = the bought card) |
| tag contexts | `immediate` (skip_blind), `new_blind_choice` (_offer_blinds), `voucher_add` + `shop_final_pass` + `store_joker_create`/`store_joker_modify` (_enter_shop), `round_start_bonus` (_start_round), `tag_add` (add_tag), `reroll_shop` (Shop.reroll) |

## Hook events

`hooks.py` holds the names. The core fires:

| event | cardarea | extra context fields |
|---|---|---|
| `before` | `play` | `full_hand`, `scoring_hand`, `scoring_name`, `poker_hands` |
| `individual` | `play`/`hand` | `other_card` = the card being scored/held |
| `joker_main` | — | `full_hand`, `scoring_hand`, `scoring_name`, `poker_hands` |
| `after` | `play` | as `before` |
| `repetition` | `play`/`hand` | `other_card`, `repetition_only=True` for the seal probe |
| `discard` | — | `other_card` = discarded card |
| `discard_hand` | — | `full_hand` = the discarded cards |
| `end_of_round` | — | `game_over: bool` |
| `setting_blind` | — | `blind` |
| `hand_drawn` / `first_hand_drawn` | — | |
| `open_booster` | — | `pack` |
| `skip_blind` | — | `blind`, `skipped_blind=True` |
| `shop_start` / `shop_final_pass` / `reroll_shop` | — | |
| `buying_card` / `selling_card` / `selling_self` | — | `other_card` |
| `use_consumeable` | — | `consumable` |
| `card_added` / `card_removed` / `playing_card_added` / `remove_playing_cards` / `destroying_card` | — | `other_card` |
| `round_start` / `blind_defeated` | — | |

## Source map

| CLI module | Lua source | entry point |
|---|---|---|
| `engine/jokers.py` | `card.lua` | `Card:calculate_joker` (~2291-4100), `Card:calculate_dollar_bonus` (~1655) |
| `engine/consumables.py` | `card.lua` | `Card:use_consumeable` (~1091-1523), `Card:can_use_consumeable` (~1523) |
| `engine/tags.py` | `tag.lua` | `Tag:apply_to_run` (~115-520), `Tag:yep` |
| `engine/vouchers.py` | `card.lua` | `Card:redeem` (~1813-1880), `Card:add_to_deck` (~564-645), `Card:remove_from_deck` (~645) |
| `engine/backs.py` | `back.lua` | `Back:trigger_effect`, `Back:init` |
| `engine/packs.py` | `common_events.lua` | `create_card` (~2082), `poll_edition` (~2055), `get_current_pool` (~1963), `get_pack` (~1944) |
| `engine/blind.py` | `blind.lua` | `Blind:set_blind`, `Blind:debuff_card`, `Blind:debuff_hand`, `Blind:modify_hand`, `Blind:press_play`, `Blind:stay_flipped` |
| `engine/scoring.py` | `state_events.lua` | `G.FUNCS.evaluate_play` (~571-1135) |
| `engine/game_state.py` | `state_events.lua` | `end_round` (~87), `new_round` (~290), `evaluate_round` (~1135) |
| `engine/shop.py` | `button_callbacks.lua` | shop creation, `buy_from_shop`, `reroll_shop`, `sell` |

## Effect keys

`hooks.Effect` fields map to the Lua return keys:

| Effect field | Lua key | used by |
|---|---|---|
| `chips` | `chip_mod` | flat chips |
| `mult` | `mult_mod` | flat mult |
| `x_mult` | `Xmult_mod` | multiplier |
| `dollars` / `h_dollars` / `p_dollars` | `dollar` / `h_dollars` / `p_dollars` | money |
| `repetitions` | `repetitions` | retriggers |
| `level_up` | `level_up` | `[(hand_key, amount)]` |
| `destroy` | `remove` / `destroy` | destroy the card |
| `create` | implicit `create_card` calls | `[{"kind": "Tarot", "count": 1}]` |
| `message` | `message` | transcript text |
| `saved` | `saved` | Mr. Bones / Luchador |
| `debuff` | `debuff` | Cerulean Bell etc. |
| `disabled_blind` | `disabled_blind` | Chicot |
| `extra` | `extra` | free-form side data |

`JokerCard.ability` is the mutable per-joker state table (Lua `self.ability`).
It is seeded from `centers.json[key]["config"]` and then freely mutated:
`j.ability["mult"] += 1`, `j.ability["x_mult"] = 2`, `j.ability["tally"] = …`.
