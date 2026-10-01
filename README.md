# balatro-tui

Balatro 的终端移植(中文界面),基于 [Textual](https://textual.textualize.io/)。

## 架构

- `balatro_tui/` — Textual 前端:屏幕(`screens/`)、样式(`css/`)、中文文本工具
  (`utils/`,解析 `balatro_source_code/game.lua` + `data/zh_CN.json`)。
  **游戏规则语义不在本包实现**,全部来自 `balatro_cli.engine`。
- `balatro_tui/game_engine/run.py` — `RunState` 适配层,把界面的「卡牌对象」操作
  翻译成引擎接口,并提供显示映射(牌面符号、中文名、逐小丑计分转写)。
- `balatro_cli/engine/` — 按 `balatro_source_code/` 逐条移植的纯逻辑引擎
  (150 小丑、消耗品/卡包、标签、优惠券、卡背、BOSS 盲注、计分管线、stake、
  种子 RNG),进度台账见 `balatro_cli/PORTING_PLAN.md`。
- `balatro_tui/PORTING_PLAN.md` — TUI 侧重构/补全台账(2026-10-01 完成主体)。

## 运行

```bash
textual run --dev main.py        # 开发模式
# 或
.venv/bin/python main.py
```

## 测试

```bash
.venv/bin/pytest balatro_cli/tests -q   # 引擎(基线 253 passed)
.venv/bin/pytest tests -q               # TUI 适配层 + Pilot 冒烟(基线 17 passed)
```

## dev console

```bash
textual console
```
