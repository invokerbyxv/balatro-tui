# Balatro CLI 移植计划与进度

对照 `balatro_source_code/`（反编译 Lua）完成 `balatro_cli/` 的移植。
本文档是**进度台账**：每完成一项就把 `[ ]` 改成 `[x]`，中断后从第一个未勾选项继续。

- 接口契约见 `engine/PORTING.md`（引擎核心 ↔ 效果表的冻结接口）。
- 规则：**Lua 源码优先**；引擎改动要同步更新 `engine/PORTING.md`。
- 测试：`.venv/Scripts/python.exe -m pytest balatro_cli/tests -q`（基线 230 passed）。
- 审计日期：2026-09-30（五路审计：jokers / consumables / tags+vouchers+backs / 流程 / blind+hand+card+config）。

## 图例

`[ ]` 未做 · `[~]` 部分完成 · `[x]` 完成（含测试）

---

## Phase 0 — 引擎管线（一切效果落地的前提）

核心问题：效果表返回了正确的 Effect，但引擎不消费/不触发，约 30 个 joker、12 个 tag 事实性死亡。

- [x] **0.1 `Effect.create` 落地**：`GameState.consume_effects` 统一消费（create/dollars/extra/destroy_joker/destroy_self/add_tag/level_up），`_create_from_spec` 物化 8 种 create 规格；`play_cards` 消费计分日志中的非计分效果。受益：DNA、8 Ball、Vagabond、Superposition、Seance、Sixth Sense、Certificate、Riff-raff、Cartomancer、Marble Joker、Hallucination、Invisible Joker。
- [x] **0.2 缺失事件常量与触发点**（hooks.py + game_state.py）：`ending_shop`（advance_from_shop）、`pre_discard`（discard_cards）、`skip_blind`（skip_blind）、`skipping_booster` 常量已加（open_pack 的跳过分支待 cli 接线）。
- [x] **0.3 Effect 返回值不再丢弃**：discard_cards 消费 dollars/create/destroy；setting_blind 消费 disabled_blind/hands_add/destroy_joker；sell_joker 消费 selling_self；destroy_self 自毁（Ice Cream/Seltzer/Gros Michel→pool_flags/Cavendish/Turtle Bean）；Matador 的 $8 计入 debuffed 分支。
- [x] **0.4 运行时状态种子**：`_seed_round_cards`（idol/mail/ancient/castle，每轮）；`driver_tally` 经 playing_card_added 累加（jokers.py Driver's License 分支）；`hands_played_at_create` 在 add_joker 写入（Loyalty Card）。
- [x] **0.5 胜负判定修复**：won 判定移入 end_round（ante≥8 打完 boss → phase "won"）；check_run_end 仅转发 round_won。
- [x] **0.6 add_to_deck / remove_from_deck**：`_joker_deck_delta`（h_size/d_size/Turtle Bean +5/Troubadour/Stuntman/Credit Card bankrupt_at/To the Moon interest_amount）；`sell_value` 计入 extra_value；Chicot 购入即 disable boss。
  - [ ] Astronomer 重定价（商店 Planet/Celestial 免费）→ 归入 3.1 商店改造。
- [x] ante 推进移到 end_round（boss 击败时，state_events.lua:248），`_advance_blind_index` 不再重复推进。
- [x] last_blind 语义修正：`_start_blind` 写入（blind.lua:97），skip 不再覆盖。
- [x] end_round 顺序：end_of_round 效果 → Anaglyph eval → 结钱；`unused_discards`/`hands_played_total`/`skips` run 级累计；boss 击败重算 most_played、清 played_this_ante。

## Phase 1 — tags / vouchers / backs 触发链

tags.py 的 25 个 handler 全部就位，问题全在触发侧与结算侧。

- [x] **1.1 tag 事件触发点**（game_state.py）：
  - `immediate`：skip_blind 后（Top-up/Skip/Garbage/Handy/Economy/Orbital）。
  - `new_blind_choice`：`_offer_blinds`（Charm/Meteor/Ethereal/Standard/Buffoon/Boss）。
  - `voucher_add`：`_enter_shop` refill 后 → `voucher_slots` 扩容 + `shop.refill_vouchers()`。
  - `store_joker_create` / `store_joker_modify`：`_enter_shop._apply_store_joker_tags`（免费 joker 占槽、贴版、couponed）。
  - `round_start_bonus`：`_start_round`（Juggle +h_size，用后清零）。
  - `shop_start`（D6）：`shop.refill` 读 `state.shop_d6ed` 使本店重掷从 $0 起。
  - `shop_final_pass`（Coupon）：`_enter_shop` 中在补货后 fire（game.lua:3165 时机）；`_refill_card_slots` 重掷时保持免费。
- [x] **1.2 tag 结算修复**：Double Tag 属性名统一（两个名字都识别并清零）；Investment 改由 `_start_blind` 写 last_blind（blind.lua:97-99）；`run.skips` 维护；Handy/Garbage 用 `hands_played_total`/`unused_discards` run 级累计；`pending_packs`/`boss_reroll_pending` 在 `_offer_blinds._consume_pending_tags` 落地。
- [x] **1.3 vouchers 去重**：`redeem_voucher` 删除 legacy `_apply_voucher_stats` 二次应用（vouchers.py 为唯一实现）。legacy `consumable.py` 错误映射清理 → 归入 3.5。
- [ ] **1.4 voucher 死旋钮接线**：`playing_card_rate`/`illusion_editions`（Magic Trick/Illusion 商店牌槽）、`edition_rate`（Hone/Glow Up）、`boss_reroll_limit/cost`（Director's Cut/Retcon）、`free_rerolls` 接入 shop/boss 流程。
- [x] **1.5 backs**：`back_trigger("eval")` 在击败 boss 后调用（Anaglyph → tag_double）；edition/edition_count deck 配置键（前瞻，现行数据无此键，暂缓）。

## Phase 2 — blind / boss / stake / 计分顺序

- [x] **2.1 blind 运行时钩子接线**：`press_play`（The Hook 洗 2 张弃牌、The Tooth 扣钱）接入 play_cards；`stay_flipped` 接入 `_draw_to_handsize`（cli 点选翻面揭示）；`debuff_hand` 传 `run=`（The Arm 降级 / The Ox 生效）；**The Serpent**（动作后只抽 3 张）接入 `_draw_to_handsize(after_action=True)`。
- [x] **2.2 boss 选择对齐**（common_events.lua:2340-2376 `get_new_boss`）：key 从 blinds.json 外层键注入；`bosses_used` 每键使用计数取最少者；ante 条件（非 showdown 在 ante%8==0 且 ante>=2 时排除；showdown 仅此时出现）；过滤 `banned_keys`；选中即计数。
- [x] **2.3 状态维护**：`played_this_ante` 在 play_cards 写入 / boss 击败清空（The Pillar）；`most_played_poker_hand` 击败 boss 时重算；`unused_discards` 累积。
- [x] **2.4 scaling 双变量拆分**：`run.scaling`（选表，stake 3/6 提升）与 `run.ante_scaling`（Plasma 乘数，backs.py 已改写目标）分离；Blind/set_chips/_make_offer 全部跟随。
- [x] **2.5 stake 实现**（game.lua:2048-2057）：stake≥2 Small Blind 无奖励、≥3 scaling=2、≥5 discards-1、≥6 scaling=3。
- [~] **2.6 计分顺序**：joker edition 的 x_mult 移到 joker_main + joker-on-joker 之后乘（state_events.lua:947-955）；joker 自身 debuff 早退；dollar_bonus debuff 早退。
  - [ ] held 牌红印重触发时重新 roll joker individual 效果（现复用一次结果）。
  - [ ] `first_used_hand_level`（before 前一次性升级）未移植。
  - [ ] 毁牌后对 joker fire `remove_playing_cards`（现只有逐卡 card_removed）。
  - [ ] `extra` 的 mult_mod/chip_mod 子字段展开。
  - [ ] `debuff_played_cards` perma_debuff 修饰符。
- [x] **2.7 end_round 顺序与细节**：end_of_round 效果先于 ROUND_EVAL 结钱；**blue seal** 产 Planet（card.lua:1044-1066）；held 金卡 red seal 双倍；ante 推进在 end_round 内；boss 击败清 `played_this_ante`/`boss_reroll_count`/`skips`。
- [x] **2.8 pareidolia 断链**：`JokerFlags.pareidolia` 补上；jokers.py `_is_face` 走 calculate() 注入的 flags；blind `_refresh_debuffs` 传 flags。

## Phase 3 — 商店 / 卡池 / consumable 集成

- [x] **3.1 商店槽位分布**：按 UI_definitions.lua:764-786 的 rate 加权（joker 20 / tarot 4×rate / planet 4×rate / playing_card / spectral）；卡生成统一走 `packs.create_card`（rarity 0.95/0.7 阈值、`used_jokers`/pool_flags/Planet softlock/banned 过滤、edition poll、The Soul/Black Hole 替换全量生效）；`used_jokers` 由 add_joker 维护。
- [x] **3.2 reroll 范围**：`_refill_card_slots` 只重填卡槽，包与 voucher 保留（button_callbacks.lua:2873）；Coupon 期间重掷保持免费。
- [~] **3.3 商店钩子**：每次购买 fire `buying_card`；买 playing card 进牌组（`state._add_playing_card`）。
  - [ ] inflation 修饰符（每购 +1 重定价，button_callbacks.lua:2461-2470）。
- [~] **3.4 packs**：`used_jokers` 维护（add_joker）；`pool_flags` 写入点（Gros Michel 腐烂 → `consume_effects`）。
  - [ ] `_most_played_hand` 排序键用 handlist 顺序（Telescope 目标，hand_levels 需补 `order` 字段）。
- [x] **3.5 consumable 集成**：cli `_use_consumable` 传选中手牌为 targets 并前置 `can_use`；引擎 `use_consumable` 也过 `can_use`；Tanuki/Wheel 概率已走 `probabilities_normal`（rng.chance 内建）。
  - [ ] Cryptid 增加 deck 上限（card.lua:1210）。
  - [ ] The Fool 消耗品空间检查、Wraith 0.99 语义（1% 非稀有）。
- [~] **3.6 杂项行为对齐**（jokers.py）：Brainstorm 最左不复制；Swashbuckler mult=其它 joker 卖价之和；Blackboard 检查手牌 debuff；Madness 排除 eternal；joker 自身 debuff 早退；dollar_bonus 的 debuff 早退；Red Card 跳包 +3 mult。
  - [ ] Ceremonial Dagger 用真实卖价（`_sell_cost` fallback 仍为 1）。
  - [ ] Satellite 用去重物种数（现用 usage total fallback）。
- [x] **voucher 死旋钮接线**：`playing_card_rate`（Magic Trick/Illusion 商店牌槽）；`boss_reroll_limit/cost`（Director's Cut/Retcon → `boss_reroll_info`/`reroll_boss`，cli `b` 键）；Astronomer（Planet/Celestial 免费，card.lua:380）；tarot/planet rate 改为 Lua 真值 `4*extra`（2.4/8）。
  - [ ] `illusion_editions`（Illusion 花牌贴版概率）；`free_rerolls` 来自 voucher（现为 Chaos the Clown 专用）。

## Phase 4 — 收尾

- [x] 4.1 `engine/PORTING.md` 同步新增的 run API / 属性 / 事件表。
- [x] 4.2 全量测试通过（245 passed）+ 新增 `tests/test_port_progress.py` 回归（15 项）。
- [~] 4.3 cli.py 渲染层：翻面牌点选揭示已接；商店免费重摇显示、tag 兑现 transcript 文本未做。
- [x] 4.4 已知刻意偏差记录（不动）：Obelisk 按游戏文本、首店 Buffoon 随机源、resample 64 次上限、To Do List 时机、tarot/planet rate 文档化数值。

## 已确认完成（本次审计基线）

- consumables.py：52 个 consumable handler 全部就位，无数缺漏。
- jokers.py：150 个 joker handler 全部注册（缺口在引擎落地层，见 Phase 0）。
- vouchers.py：32 个 v_* 分支齐、requires 链正确（问题在 game_state 双重应用）。
- tags.py：25 个 tag handler 齐（问题在触发链）。
- backs.py：16 个 deck apply 参数面完整，Plasma final_scoring_step 已接入。
- scoring.py 主流程、enhancement/seal/edition 数值、hand.py 牌型判定、config 起始参数与 HAND_LEVELS、get_blind_amount 三张表：与 Lua 一致。
