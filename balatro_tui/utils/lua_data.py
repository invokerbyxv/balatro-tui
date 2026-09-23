"""解析 balatro_source_code/game.lua 中的资源定义(P_CENTERS/P_TAGS/P_BLINDS 等)。

只提取静态数据:名称、价格、稀有度、config(即描述文本里 #1# #2# 的数值来源)。
"""
from __future__ import annotations

import re
from pathlib import Path

GAME_LUA = (
    Path(__file__).resolve().parent.parent.parent
    / "balatro_source_code"
    / "game.lua"
)

_NUM_RE = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


class LuaParseError(Exception):
    pass


def _skip_ws(s: str, i: int) -> int:
    while i < len(s):
        c = s[i]
        if c.isspace():
            i += 1
        elif s.startswith("--", i):
            j = s.find("\n", i)
            i = len(s) if j < 0 else j + 1
        else:
            break
    return i


def _parse_string(s: str, i: int):
    q = s[i]
    i += 1
    buf = []
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            buf.append({"n": "\n", "t": "\t"}.get(nxt, nxt))
            i += 2
            continue
        if c == q:
            return "".join(buf), i + 1
        buf.append(c)
        i += 1
    raise LuaParseError("未闭合的字符串")


def _parse_number_expr(s: str, i: int):
    m = _NUM_RE.match(s, i)
    if not m:
        raise LuaParseError(f"位置 {i} 不是数字")
    val = float(m.group())
    i = m.end()
    while True:
        j = _skip_ws(s, i)
        if j < len(s) and s[j] in "+-*/":
            m2 = _NUM_RE.match(s, _skip_ws(s, j + 1))
            if not m2:
                break
            n = float(m2.group())
            if s[j] == "+":
                val += n
            elif s[j] == "-":
                val -= n
            elif s[j] == "*":
                val *= n
            else:
                val = val / n if n else val
            i = m2.end()
        else:
            break
    return (int(val) if val == int(val) else val), i


def _skip_function(s: str, i: int) -> int:
    """跳到 function 值结束处(下一个顶层 ',' 或 '}' 前)。"""
    depth = 0
    while i < len(s):
        c = s[i]
        if c in "({[":
            depth += 1
        elif c in ")}]":
            if depth == 0 and c == "}":
                break
            depth -= 1
        elif c in "\"'":
            _, i = _parse_string(s, i)
            continue
        elif c == "," and depth == 0:
            break
        elif s.startswith("end", i) and depth == 0:
            j = _skip_ws(s, i + 3)
            if j >= len(s) or s[j] in ",}":
                return j
        i += 1
    return i


def _parse_call(s: str, i: int):
    m = re.compile(r"[A-Za-z_]\w*").match(s, i)
    name = m.group()
    j = _skip_ws(s, m.end())
    if j >= len(s) or s[j] != "(":
        if j < len(s) and s[j] == ".":  # 形如 a.b.c(...) 的引用,整段丢弃
            return None, _skip_to_entry_end(s, j)
        return None, m.end()
    depth = 0
    k = j
    while k < len(s):
        if s[k] == "(":
            depth += 1
        elif s[k] == ")":
            depth -= 1
            if depth == 0:
                break
        elif s[k] in "\"'":
            _, k = _parse_string(s, k)
            continue
        k += 1
    inner = s[j + 1 : k]
    if name in ("localize", "HEX", "STR_N_DEFS"):
        arg = re.search(r"['\"]([^'\"]*)['\"]", inner)
        return (f"{name}:{arg.group(1)}" if arg else None), k + 1
    return None, k + 1


def _parse_value(s: str, i: int):
    i = _skip_ws(s, i)
    if i >= len(s):
        raise LuaParseError("值缺失")
    c = s[i]
    if c == "{":
        return _parse_table(s, i)
    if c in "\"'":
        return _parse_string(s, i)
    if c.isdigit() or (c in "+-" and i + 1 < len(s) and s[i + 1 : i + 2].isdigit()):
        return _parse_number_expr(s, i)
    m = re.compile(r"[A-Za-z_]\w*").match(s, i)
    if m:
        word = m.group()
        if word in ("true", "false"):
            return word == "true", m.end()
        if word == "nil":
            return None, m.end()
        if word == "function":
            return None, _skip_function(s, m.end())
        return _parse_call(s, i)
    raise LuaParseError(f"位置 {i} 无法解析: {s[i:i+20]!r}")


def _parse_table(s: str, i: int):
    assert s[i] == "{"
    i += 1
    out_dict: dict = {}
    out_list: list = []
    while True:
        i = _skip_ws(s, i)
        if i >= len(s):
            raise LuaParseError("表未闭合")
        if s[i] == "}":
            return (out_dict if out_dict else out_list), i + 1
        # key = value / [key] = value / 裸值
        key = None
        m = re.compile(r"[A-Za-z_]\w*").match(s, i)
        eq = None
        if m:
            j = _skip_ws(s, m.end())
            if j < len(s) and s[j] == "=" and not s.startswith("==", j):
                key, eq = m.group(), j
        elif s[i] == "[":
            j = _skip_ws(s, i + 1)
            k, jj = _parse_value(s, j)
            jj = _skip_ws(s, jj)
            if jj < len(s) and s[jj] == "]":
                j2 = _skip_ws(s, jj + 1)
                if j2 < len(s) and s[j2] == "=":
                    key, eq = str(k), j2
                else:
                    raise LuaParseError(f"[key] 后缺少 =: {s[i:i+30]!r}")
            else:
                raise LuaParseError(f"[key] 未闭合: {s[i:i+30]!r}")
        if eq is not None:
            val, i = _parse_value(s, eq + 1)
            out_dict[key] = val
        else:
            val, i = _parse_value(s, i)
            out_list.append(val)
        i = _skip_ws(s, i)
        if i < len(s) and s[i] in ",;":
            i += 1


def _skip_to_entry_end(s: str, i: int) -> int:
    """从任意表达式中间跳到该条目值的结束处(顶层 ',' 前或 '}' 前)。"""
    depth = 0
    while i < len(s):
        c = s[i]
        if c in "({[":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif c == "}":
            if depth == 0:
                break
            depth -= 1
        elif c in "\"'":
            try:
                _, i = _parse_string(s, i)
            except LuaParseError:
                return len(s)
            continue
        elif c == "," and depth == 0:
            break
        i += 1
    return i


def _looks_like_bareword(m, s) -> bool:
    j = _skip_ws(s, m.end())
    return j < len(s) and s[j] in ",;}"


def _parse_section(text: str, marker: str) -> dict:
    idx = text.find(marker)
    if idx < 0:
        raise LuaParseError(f"找不到 {marker}")
    start = text.index("{", idx)
    # game.lua 里有 9.6/4 这类算式,先就地求值
    chunk = re.sub(
        r"(?<![\w.'\"])(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)(?![\w'\"])",
        lambda mm: repr(float(mm.group(1)) / float(mm.group(2))),
        text[start:],
    )
    val, _ = _parse_table(chunk, 0)
    return val


def _parse_hands(text: str) -> dict:
    """解析 game.lua 中牌型基础数值表(hands = { ["Pair"] = {...} })。"""
    hands = {}
    for m in re.finditer(
        r'\["([^"]+)"\]\s*=\s*\{[^}]*?\bl_mult\s*=\s*(\d+),\s*l_chips\s*=\s*(\d+)',
        text,
    ):
        hands[m.group(1)] = {"l_mult": int(m.group(2)), "l_chips": int(m.group(3))}
    return hands


_CACHE: dict | None = None


def load_definitions() -> dict:
    """返回 {set 名: {key: 定义}} 外加 '_hands'。"""
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    text = GAME_LUA.read_text(encoding="utf-8")
    centers = _parse_section(text, "self.P_CENTERS = {")
    tags = _parse_section(text, "self.P_TAGS = {")
    blinds = _parse_section(text, "self.P_BLINDS = {")
    stakes = _parse_section(text, "self.P_STAKES = {")

    grouped: dict[str, dict] = {}
    for key, entry in centers.items():
        if not isinstance(entry, dict):
            continue
        group = entry.get("set")
        if group:
            grouped.setdefault(group, {})[key] = entry
    grouped["Tag"] = tags
    grouped["Blind"] = blinds
    grouped["Stake"] = {k: v for k, v in stakes.items() if isinstance(v, dict)}
    grouped["_hands"] = _parse_hands(text)
    _CACHE = grouped
    return grouped


def get_config(entry: dict) -> dict:
    cfg = entry.get("config") if entry else None
    return cfg if isinstance(cfg, dict) else {}
