# Balatro CLI

 covert command-line Balatro —— 一个纯命令行的《小丑牌》。所有输出都是逐行滚动的
普通文本（不清屏、不移动光标），看起来就像 IDE 终端里的一段日志。游戏规则逐条对照
反编译的 Lua 源码（`../balatro_source_code/`）移植，joker / 消耗品 / 标签 / 优惠券 /
牌组 / boss 盲注等机制与原版对齐，移植进度见 [PORTING_PLAN.md](PORTING_PLAN.md)。

## 启动

需要仓库根目录的 `.venv`（Python 3.10+），从仓库根目录运行：

```bash
# 手动模式（默认）：单键交互，按键即生效，无需回车
.venv/bin/python -m balatro_cli.cli

# 常用参数
.venv/bin/python -m balatro_cli.cli --seed abc --deck b_checkered --glyphs --locale zh_CN
```

| 参数 | 说明 |
|---|---|
| `--seed 字符串` | 运行种子。同一种子 + 同样操作 = 完全一致的流程，方便复现 |
| `--deck <key>` | 起始牌组，可选 `b_red` / `b_blue` / `b_yellow` / `b_green` / `b_black` / `b_magic` / `b_nebula` / `b_ghost` / `b_abandoned` / `b_checkered` / `b_zodiac` / `b_painted` / `b_anaglyph` / `b_plasma` / `b_erratic` |
| `--script manual\|auto` | 手动（默认）或自动演示模式 |
| `--locale en-us\|zh_CN` | 界面语言 |
| `--glyphs` | 用 ♠♥♣♦ 显示花色（默认字母 S/H/C/D） |
| `--ante-cap N` | 打到第 N 个 ante 即停（默认 8） |
| `--auto-skip` / `--auto-buy` | 仅 auto 模式：自动跳盲注攒 tag / 自动购物 |

快速看一遍流程可以跑自动模式：

```bash
.venv/bin/python -m balatro_cli.cli --script auto --auto-skip --auto-buy --ante-cap 2
```

## 操作说明

任意时刻 `?` 看当前阶段的按键提示，`q` 退出。手动模式是 raw 单键读取，**按一下即生效**。

### 1. 选盲注（blind select）

每轮开头三选一：Small / Big / Boss，数字键选择：

| 按键 | 作用 |
|---|---|
| `1` / `2` / `3` | 打对应的盲注（Boss 盲有特殊规则，击败后进入下一 ante） |
| `k` | 跳过当前盲注，获得一个 tag（立即型 tag 会当场结算并在 transcript 显示 `tag redeemed: …`） |
| `b` | 重摇 Boss 盲（需要优惠券 Director's Cut，Retcon 可重复，每次 $10） |

> 注意：Boss 盲不可跳过；筹码要求 Small < Big < Boss。

### 2. 出牌回合（round）

| 按键 | 作用 |
|---|---|
| `1`-`8` | 选中/取消选手牌中的第 N 张（最多选 5 张；某些盲注下点选盖牌先翻面） |
| `p` / 空格 / 回车 | 出牌：结算筹码，打够盲注即获胜 |
| `d` | 弃掉选中的牌（消耗一次弃牌机会并补牌） |
| `c` 然后 `N` | 使用第 N 个消耗品（塔罗/星球/幽灵；选中中的手牌会作为目标） |
| `i` | 查看盲注、牌型等级、joker、消耗品、tag、优惠券详情 |

每次出牌显示一行结算：`牌型 [牌] 基础 chips*mult 等级 -> 总分 盲注要求 (+/-差值)`。
打不过且手数用完则游戏结束（Mr. Bones / Luchador 之类的救场 joker 会在此触发）。

### 3. 商店（shop）

击败盲注后结算奖金与利息，进入商店：

| 按键 | 作用 |
|---|---|
| `1`-`9` | 购买第 N 件商品（joker / 消耗品 / 补充包 / 优惠券 / 玩法牌） |
| `r` | 重摇卡槽（$5 起，每轮内每次 +$1；被 Coupon/D6 免费时显示 `reroll (free)`；只刷卡槽，包和优惠券保留） |
| `c` 然后 `N` | 使用消耗品 |
| `x` 然后 `N` | 卖掉第 N 个 joker（卖价 = 基础价一半 + 增值，最低 $1） |
| `s` | 离开商店，进入下一轮选盲注 |
| `i` / `?` | 信息 / 帮助 |

买补充包后立即开包：

| 按键 | 作用 |
|---|---|
| `1`-`n` | 选/取消选包里的牌 |
| 回车 | 确认拿取（包上标注可选几张） |
| `s` | 跳过整个包（Red Card 之类的 joker 会因此触发） |

### 4. 界面行解读

```
$61 | jokers 2/5 | consumables 1/2 | tags 2 vouchers 1 | hands 3/4 disc 2/3
^^^^                                                                              -
金钱           joker 数/槽位          消耗品 数/槽位          tag/优惠券数   剩余手数/弃牌数
```

tag 被兑现（跳盲注、进商店、开盲等时机）时会打印 `tag redeemed: <名> (+$/效果)`，
说明它实际做了什么。

## 游玩说明（规则速览）

目标：**依次通过 ante 1 到 ante 8 的所有盲注，打赢 ante 8 的 Boss 盲即通关**。

- **盲注结构**：每个 ante 有 Small → Big → Boss 三连战。盲注就是筹码门槛，
  Small/Boss 之间逐级抬升（ante 越深涨得越狠）。Boss 盲各有特殊 debuff
  （如 The Hook 出牌后随机弃 2 张、The Arm 降牌型等级、The Serpent 限制补牌等），
  Chicot 之类的 joker 可以禁用它们。
- **算分**：出的 5 张牌判定一个牌型（高牌 → 同花五条），得分 =
  (基础筹码 + 筹码增量) × (基础倍数 + 倍数增量)。牌型可通过星球牌升级，
  joker 提供各种筹码/倍数/X 倍数/重触发/经济效果。
- **手牌与弃牌**：每轮 4 次出牌、3 次弃牌、8 张手牌（可被 joker/牌组改变）。
  出牌或弃牌后自动补满。
- **金钱**：打赢盲注得奖金（Small $3 / Big $4 / Boss $5），回合结束按持有现金
  每 $5 生息 $1（上限 $25 生息 $5）。stake≥2 时 Small 盲无奖金。
- **商店**：每轮胜利后开放 2 个卡槽 + 2 个补充包 + 1 个优惠券。卡槽按权重刷
  joker / 塔罗 / 星球 / 幽灵 / 玩法牌；重摇只补卡槽。
- **消耗品**：塔罗牌改牌（升级牌型、复制、强化……），星球牌升牌型等级，
  幽灵牌效果强但代价大。默认 2 个槽位。
- **tag**：跳过盲注获得，按类型在特定时机兑现（立即生效 / 进商店生效 /
  下轮生效……），Double Tag 会复制下一个 tag。
- **优惠券（vouchers）**：永久增益，按依赖链逐级出现（如 Overstock → Overstock Plus）。
- **牌组差异**：15 种牌组各有开局优势（黑牌组无花牌、方格牌组双倍红黑、
  等离子牌组合并左右筹码分、幻牌组每局随机牌面……），并可叠加不同 stake 难度
  （引擎支持，CLI 参数暂未开放）。

机制细节与原版 Lua 的逐条对应关系（含刻意偏差）见
[PORTING_PLAN.md](PORTING_PLAN.md) 与 [engine/PORTING.md](engine/PORTING.md)。

## 测试

```bash
.venv/bin/pytest balatro_cli/tests -q     # 基线 253 passed
```

回归用例集中在 `tests/test_port_progress.py`，每条对应移植计划里的一个修复项。
