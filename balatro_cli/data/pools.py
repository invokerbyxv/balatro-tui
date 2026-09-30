"""Build generation pools from extracted centers, mirroring game.lua:780-845.

Pools (sets): Booster, Default, Enhanced, Edition, Joker, Tarot, Planet,
Tarot_Planet, Spectral, Consumeables, Voucher, Back, plus P_JOKER_RARITY_POOLS.

Joker rarity: index 1=Common, 2=Uncommon, 3=Rare, 4=Legendary (as in source).
Each pool is sorted by the center's `order` (Backs offset by unlock, which v1
does not track — all backs treated as unlocked).

An entry in a pool is the center dict augmented with its `key`.
"""

from __future__ import annotations

import json
from pathlib import Path

_SET_ORDER = [
    "Booster", "Default", "Enhanced", "Edition", "Joker", "Tarot", "Planet",
    "Tarot_Planet", "Spectral", "Consumeables", "Voucher", "Back",
]


def load_raw(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_pools(centers: dict) -> dict:
    pools: dict[str, list[dict]] = {s: [] for s in _SET_ORDER}
    rarity: list[list[dict]] = [[], [], [], [], []]  # index 1..4 (Lua is 1-based)

    for key, v in centers.items():
        if not isinstance(v, dict) or v.get("wip") or v.get("demo"):
            continue
        item = dict(v)
        item["key"] = key
        s = item.get("set")
        if s == "Joker":
            pools["Joker"].append(item)
        if s and v.get("demo") and v.get("pos"):
            pools["Demo"].append(item)
        if s and s != "Joker" and not v.get("skip_pool") and not v.get("omit"):
            if s in pools:
                pools[s].append(item)
        if s in ("Tarot", "Planet"):
            pools["Tarot_Planet"].append(item)
        if v.get("consumeable"):
            pools["Consumeables"].append(item)
        if v.get("rarity") and s == "Joker" and not v.get("demo"):
            rarity[v["rarity"]].append(item)

    for name in pools:
        pools[name].sort(key=lambda a: (a.get("order") is None, a.get("order", 0)))
    for i in range(1, 5):
        rarity[i].sort(key=lambda a: (a.get("order") is None, a.get("order", 0)))

    pools["JokerRarity"] = rarity
    return pools