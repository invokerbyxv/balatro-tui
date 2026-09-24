"""盲注(Blind)系统:目标分缩放与 boss 选择。

参照 balatro_source_code/functions/misc_functions.lua -> get_blind_amount,
以及 game.lua -> P_BLINDS(小盲/大盲及 boss 表)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..utils.lua_data import load_definitions


def get_blind_defs() -> dict:
    return load_definitions().get("Blind") or {}

# 无 scaling(默认)与 stake 升高后的缩放表
_AMOUNTS = {
    1: [300, 800, 2000, 5000, 11000, 20000, 35000, 50000],
    2: [300, 900, 2600, 8000, 20000, 36000, 60000, 100000],
    3: [300, 1000, 3200, 9000, 25000, 60000, 110000, 200000],
}

# 小盲 / 大盲 的倍率与奖励
SMALL_MULT = 1
BIG_MULT = 1.5
SMALL_DOLLARS = 3
BIG_DOLLARS = 4


def get_blind_amount(ante: int, scaling: int = 1) -> int:
    """返回指定底注下的盲注目标分(base,未乘 mult)。"""
    amounts = _AMOUNTS.get(scaling, _AMOUNTS[1])
    if ante < 1:
        return 100
    if ante <= 8:
        return amounts[ante - 1]
    k = 0.75
    a, b, c, d = amounts[7], 1.6, ante - 8, 1 + 0.2 * (ante - 8)
    amount = int(a * (b + (k * c) ** d) ** c)
    amount = amount - amount % (10 ** (len(str(amount)) - 2))
    return amount


@dataclass
class Blind:
    """一局对战中要攻克的盲注。"""

    key: str               # bl_small / bl_big / boss key
    name: str              # 中文名
    mult: float            # 目标分倍率
    dollars: int           # 击败后奖励
    base_chips: int        # 未经 mult 的基值
    scaling: int = 1
    boss: Optional[dict] = None
    target: int = 0

    def __post_init__(self):
        self.target = int(self.base_chips * self.mult)

    @property
    def is_boss(self) -> bool:
        return self.boss is not None


def small_blind(ante: int, scaling: int = 1, dollars_delta: int = 0) -> Blind:
    base = get_blind_amount(ante, scaling)
    return Blind("bl_small", "小盲注", SMALL_MULT, SMALL_DOLLARS + dollars_delta, base, scaling)


def big_blind(ante: int, scaling: int = 1, dollars_delta: int = 0) -> Blind:
    base = get_blind_amount(ante, scaling)
    return Blind("bl_big", "大盲注", BIG_MULT, BIG_DOLLARS + dollars_delta, base, scaling)


def pick_boss(ante: int, scaling: int = 1, used: list[str] | None = None,
              cards: dict[str, dict] | None = None) -> Optional[Blind]:
    """从 P_BLINDS 中选一个未用过、且 boss.min<=ante<=max 的 boss。"""
    used = used or []
    defs = cards or get_blind_defs()
    base = get_blind_amount(ante, scaling)
    candidates = []
    for key, d in defs.items():
        if key in ("bl_small", "bl_big"):
            continue
        boss = d.get("boss")
        if not isinstance(boss, dict):
            continue
        mn = boss.get("min") or 1
        mx = boss.get("max") or 10
        if not (mn <= ante <= mx):
            continue
        candidates.append((key, d))
    # 按 order 排序,排除已用
    candidates.sort(key=lambda kv: kv[1].get("order", 999))
    candidates = [kv for kv in candidates if kv[0] not in used]
    if not candidates:
        return None
    key, d = candidates[candidate_index(len(candidates), ante)]
    return Blind(
        key, _boss_name(key, d), d.get("mult") or 2,
        d.get("dollars") or 5, base, scaling, boss=d.get("boss"),
    )


def _boss_name(key: str, d: dict) -> str:
    try:
        from ..utils.collection_data import _desc  # 延迟导入避免环
        return _desc("Blind", key, []) or key
    except Exception:
        return d.get("name") or key


def candidate_index(length: int, ante: int) -> int:
    """稳定选 boss:简单取 (ante-1) 归一后的槽位,避免每次同一个。"""
    return (ante - 1) % length