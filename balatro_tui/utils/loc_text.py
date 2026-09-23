"""本地化文本渲染:还原游戏内 localize() 对 #n# 占位符与 {C:xx} 控制符的处理。

游戏源码对应:
- loc_parse_string()  解析 "#n#" 与 "{...}" 控制段(misc_functions.lua:1634)
- localize()          用 vars[n] 填充占位符(misc_functions.lua:1759)
预览场景下颜色/字体控制符直接剥离,只保留纯文本。
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

_CONTROL_RE = re.compile(r"\{[^{}]*\}")
_VAR_RE = re.compile(r"#(\d+)#")


@lru_cache(maxsize=4)
def load_descriptions(locale: str = "zh_CN") -> dict:
    with open(DATA_DIR / f"{locale}.json", encoding="utf-8") as f:
        return json.load(f)["descriptions"]


def fmt_value(v) -> str:
    if isinstance(v, bool):
        return ""
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v)


def render_line(line: str, vars_: list | None = None) -> str:
    """渲染单行:剥离 {..} 控制符,把 #n# 替换为 vars_[n-1]。"""
    vars_ = vars_ or []
    # 控制符内不含 #n#,先去掉控制符再替换占位符
    text = _CONTROL_RE.sub("", line)

    def sub(m):
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(vars_) and vars_[idx] is not None:
            return fmt_value(vars_[idx])
        return m.group(0)

    return _VAR_RE.sub(sub, text)


def render_text(lines: list[str], vars_: list | None = None) -> str:
    """把多行描述渲染为一行文本(中文行间直接相连)。"""
    parts = [render_line(l, vars_) for l in lines if l and l.strip()]
    return "".join(parts)


def describe(set_name: str, key: str, vars_: list | None = None, locale: str = "zh_CN") -> str:
    entry = load_descriptions(locale).get(set_name, {}).get(key)
    if not entry:
        return ""
    return render_text(entry.get("text") or [], vars_)


def loc_name(set_name: str, key: str, locale: str = "zh_CN") -> str:
    """取某资源在当前语言下的名称(用于 #n# 填名称的场景)。"""
    entry = load_descriptions(locale).get(set_name, {}).get(key)
    return (entry or {}).get("name", key or "")
