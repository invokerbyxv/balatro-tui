# balatro_tui 重构与补全台账

目标:对照 `balatro_source_code/`(反编译 Lua)把 `balatro_tui/`(Textual 前端)补全为
一个机制完整的 Balatro TUI。本文档是**进度台账**:每完成一项就把 `[ ]` 改成 `[x]`,
中断后从第一个未勾选项继续。

- 日期:2026-10-01 立项并完成主体重构。三路并行审计(2 成功 1 超时,Lua 逐条对照由
  `balatro_cli/PORTING_PLAN.md` 的既有五路审计结论补足)。
- 测试:`.venv/bin/pytest balatro_cli/tests -q`(253 passed)、
  `.venv/bin/pytest tests -q`(17 passed,2026-10-01 重写后)。
- 规则:**Lua 源码优先**;引擎语义一律复用 `balatro_cli.engine`,不在本包重复实现。

## 图例

`[ ]` 未做 · `[~]` 部分完成 · `[x]` 完成(含测试)

---

## 0. 审计结论(2026-10-01)

### 策略决定

`balatro_tui` 自带的玩具引擎(game_engine/{state,score,blind,card,hand}.py ≈ 900 行)
存在结构性缺陷,不修补、直接替换:

- `Card` 类没有 `enhancement/edition/seal` 字段 → score.py 里的增强计分是**死代码**。
- `use_consumable` 只 `pop` 且**从未被任何界面调用** → 塔罗/星球/幻灵全部无效。
- 小丑只有 5 种效果分支(其中 2 个是 `pass` 桩),150 个小丑 ≈ 全部失效。
- BOSS 盲注只有目标分,无任何 debuff;标签纯装饰(永不触发);优惠券仅 Overstock;
  赌注(stake)写进 state 但无人读取;ante 8 无胜利结算(`run_over` 无人读)。
- 流程 bug:跳过盲注双跳(preparation.py 手动推进 + shop 再次推进)、跳过还发钱、
  预览列的跳过按钮作用于当前盲注、屏幕栈只 push 不回收。

同仓库 `balatro_cli.engine`(9.8k 行,253 测试)是按 Lua 逐条移植的完整纯逻辑引擎:
150 小丑、消耗品/卡包、25 标签、32 优惠券、15 卡背、BOSS debuff、计分管线
(逐小丑 delta + effects_log 事件流)、stake、ante 8 胜利、种子 RNG。审计确认其
`engine/*` 与 `data/*` 零 import CLI 的 render/input,可直接作为库使用。

**因此:balatro_tui 改为 balatro_cli.engine 的前端。** 本包只保留:
界面(screens/css)、中文文本工具(utils/,基于 zh_CN.json + game.lua 解析,与引擎
key 空间一致)、以及一层薄适配器(game_engine/run.py)把引擎 API 映射给界面。

### 缺口清单(界面可见的功能)——全部由下述 Phase A/B 解决

| # | 领域 | 重构前现状 |
|---|---|---|
| 1 | 消耗品使用 | 无任何使用流程;use_consumable 只 pop 且无效果、无调用 |
| 2 | 卡牌增强/版本/封印 | Card 无字段,永不生效 |
| 3 | 小丑效果 | 5 个分支,其中 2 个 pass;无卖、无排序、无槽位上限 |
| 4 | BOSS 盲注效果 | 仅目标分(如 The Hook 不洗牌、无 debuff 牌) |
| 5 | 标签 | 永不触发,remove_tag 无调用 |
| 6 | 优惠券 | 仅 Overstock;其他 30 张惰性字符串 |
| 7 | 卡包 | 全池均匀抽样、只能选 1 张(choose>1 不支持) |
| 8 | 赌注 stake | UI 可选但无效果 |
| 9 | 胜利/无尽 | ante 8 无胜利结算;run_over 无人读 |
| 10 | 商店经济 | 无折扣/重掷涨价/playing_card 槽/券位扩展 |
| 11 | 计分展示 | 无逐小丑触发流,只打一行总分 |
| 12 | 流程 bug | 跳盲双跳、跳白发钱、预览列 skip 串位、结算屏构造即发钱 |

## Phase A — 后端适配层

- [x] **A.1 `game_engine/run.py` — `RunState` 适配器**(2026-10-01):包装
  `balatro_cli.engine` `GameState` + `Shop`(开局创建一次,引擎进入商店自动补货);
  start_run / blind_choices / select_blind / skip_blind / boss_reroll / preview_hand /
  play_cards(对象→索引) / discard_cards / end_round / continue_endless /
  shop(buy,reroll,sell) / advance_from_shop / open_pack / take_from_pack /
  skip_pack / use_consumable(带目标) / consumable_target_range / sort_hand。
- [x] **A.2 显示映射**(2026-10-01):card_label(花色符号+增强/封印尾缀+红黑配色)、
  carrier_label(中文名+版本前缀+描述)、blind_display(中文盲注名+BOSS 效果描述)、
  score_lines(ScoreResult → 基础→逐牌→逐小丑→汇总的转写行)。tag/voucher 文案
  继续走 utils/collection_data(与引擎同一 key 空间)。
- [x] **A.3 删除旧引擎**(2026-10-01):state/score/blind/card/hand.py 已删除,
  `game_engine/__init__.py` 只导出 RunState 与显示函数。

## Phase B — 界面接线

- [x] **B.1 选牌组/赌注 + 盲注选择**(2026-10-01):DeckSelect 走 start_run,
  8 个赌注真实生效(引擎 game.lua:2048-2057 口径);Preparation 用 blind_display_choices
  (BOSS 卡带效果描述),跳过走 skip_blind(即时型标签当场结算并显示通知,
  无双跳不发钱),Director's Cut 重掷 BOSS 按钮(有券才显示)。
- [x] **B.2 战斗屏**(2026-10-01):点选按卡牌对象;play 返回结构化结果,
  计分按 score_lines 逐行展示(含 BOSS 封禁该牌型的提示、毁牌列表、
  state.message 转写);弃牌失败有可见错误;弃牌/毁牌后手牌重建;
  BOSS debuff(The Hook 洗牌、The Ox、The Arm 等)由引擎自动生效。
- [x] **B.3 消耗品/小丑栏**(2026-10-01):栏位显示真名与描述;消耗品点击→
  需要手牌目标时进入选牌模式(n 张确认),星球等无目标直接使用(战斗/商店皆可);
  小丑点击弹出出售确认(SellDialog,sell_value 由引擎算);槽位上限引擎强制。
- [x] **B.4 商店/卡包**(2026-10-01):Shop API(卡牌位/卡包位/券位、折扣价、
  重掷涨价、playing_card 槽);卡包 open_pack→take_from_pack(支持 choose>1
  多次取走)→skip_pack;Voucher Tag 扩容券位可见。
- [x] **B.5 结算/胜负/无尽**(2026-10-01):end_round 结算行(盲注奖励/剩余出牌/
  标签/利息/金币牌,红封印重触发由引擎处理);ante 8 boss 胜利 → 通关屏 +
  「继续(无尽模式)」(continue_endless 手动进商店);失败 → 回首页
  (switch_screen 清栈);GameScreen.swap_screen 防屏幕栈无限增长;
  Run 信息屏:真实手牌等级、持有优惠券、战绩统计。
- [x] **B.6 标签条**(2026-10-01):显示真实标签名(悬停看描述);触发由引擎在
  对应时机自动完成。注意:即时型标签(Handy/Garbage/Economy/Top-up/Orbital 等)
  在 skip_blind/end_round 时当场结算并从队列消耗,这是引擎的正确语义而非丢失。

## Phase C — 测试

- [x] **C.1 重写 tests/**(2026-10-01):删除旧 test_engine.py;新增
  test_run_state.py(15 项:生命周期/出弃牌/排序/卡组/stake/跳过/消耗品改牌/
  星球升级/商店买卖/卡包多选/整局冒烟/ante8 无尽/中文映射)。
- [x] **C.2 Textual Pilot 冒烟**(2026-10-01):test_app_smoke.py —— 首页→选牌组
  →跳过→开打→出牌→弃牌 端到端;收藏屏开关。稳定性经验:
  1. 必须设 `TEXTUAL_ANIMATIONS=none` 并 `wait_for_scheduled_animations()`,
     否则屏幕推入动画期间点击会落空;
  2. 每次交互后用 `pilot.pause(0.2)`(带时延),裸 pause 不保证消息链排空;
  3. 引擎「即时型标签当场消耗」语义曾让断言 tags 非空时随机失败(非 bug)。

## Phase D — 收尾

- [x] **D.1** README/包注释说明 balatro_tui 依赖 balatro_cli.engine(2026-10-01)。
- [x] **D.2** 更新 auto-memory(2026-10-01)。

## 审计外的附带修复

- [x] **balatro_cli/engine/backs.py 方格卡组(Checkered Deck)bug**(2026-10-01,
  三路审计中复现):Lua back.lua:239-251 是把梅花→黑桃、方片→红桃(牌组保持
  52 张,26 黑桃 + 26 红桃);引擎原来只建了 26 张(S/H 各半)。已修复为
  每点数 4 张独立对象(S,H,S,H)。`balatro_cli/tests` 253 项仍全绿
  (该行为此前无测试覆盖)。
- [x] 战斗屏布局 bug:#played_area 高度固定 1 行截断多行计分转写;
  ActionBar 按钮溢出屏幕右缘(弃牌按钮 x=79+8>80 列)导致点击失效。
  已改 CSS(height auto + max-height 8 滚动、按钮宽度收敛)。
- [x] preparation 布局 bug:盲注卡高度不随内容自适应,跳过按钮溢出到边框行。
  已改 CSS(OfferRow/Blind height auto)。

## 已知留白(后续可选)

- [ ] 计分逐小丑动画(定时逐行揭示)目前是一次性展示全部转写行。
- [ ] 小丑/消耗品重排序(拖拽或按键);引擎按列表顺序触发,顺序影响计分。
- [ ] 存档/读档(引擎支持种子重放,可做 seed 分享)。
- [ ] 收藏屏可按已解锁/已使用过滤。
