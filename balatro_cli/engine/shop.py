"""Shop model + economy, ported from button_callbacks.lua (buy/reroll/sell).

The shop fills a few slots from the centers pools (mirroring create_card +
get_current_pool): Jokers, consumables (Tarot/Planet), a Booster pack, and a
Voucher option. Buying moves items to the run, rerolling replaces the stock at
a rising cost. It is deterministic under the run's seeded RNG.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .. import config
from ..data import loader
from . import consumable

RARITY_P = [("common", 1, 0.70), ("uncommon", 2, 0.25), ("rare", 3, 0.04), ("legendary", 4, 0.01)]


@dataclass
class ShopItem:
    index: int
    kind: str          # 'joker' | 'consumable' | 'booster' | 'voucher'
    key: str
    name: str
    cost: int

    def describe(self) -> str:
        return f"[{self.index}]{self.kind[:1].upper()}:{self.name} ${self.cost}"


class Shop:
    def __init__(self, state):
        self.state = state
        self.items: list[ShopItem] = []
        self.reroll_cost = config.STARTING_PARAMS["reroll_cost"]
        self.active = True

    # -- generation ---------------------------------------------------------
    def refill(self) -> None:
        pools = self.state.pools
        rng = self.state.rng
        self.items = []
        for i in range(3):
            kind, key, name, cost = self._gen_slot(pools, rng)
            self.items.append(ShopItem(index=i, kind=kind, key=key, name=name, cost=cost))
        # booster pack + optional voucher
        booster = rng.pick("shop_booster", pools["Booster"])
        vc = self.state.vouchers and []
        self.items.append(ShopItem(index=3, kind="booster", key=booster.get("key"),
                                   name=booster.get("name", "Booster"), cost=booster.get("cost", 4)))
        # exhibit the seeded reroll increase in `reroll_cost`
        self.reroll_cost = config.STARTING_PARAMS["reroll_cost"]  # base each refill

    def _gen_slot(self, pools, rng):
        roll = rng.rand("shop_slot")
        kind = "joker" if roll < 0.75 else "consumable"
        if kind == "joker":
            c = self._pick_joker(pools, rng)
            return "joker", c["key"], c["name"], c.get("cost", 5)
        c = rng.pick("shop_consumable", pools["Tarot_Planet"])
        return "consumable", c["key"], c["name"], c.get("cost", 3)

    def _pick_joker(self, pools, rng):
        r = rng.rand("joker_rarity")
        rarity = 4
        for _name, idx, p in RARITY_P:  # cumulative
            r -= p
            if r < 0:
                rarity = idx
                break
        pool = pools["JokerRarity"][rarity] if rarity and rarity <= 4 else pools["Joker"]
        pool = pool or pools["Joker"]
        return rng.pick("joker", pool)

    # -- actions ------------------------------------------------------------
    def buy(self, index: int) -> dict:
        if not self.active:
            return {"ok": False, "error": "shop closed"}
        if not 0 <= index < len(self.items):
            return {"ok": False, "error": "bad index"}
        item = self.items[index]
        if self.state.dollars < item.cost:
            return {"ok": False, "error": "not enough money"}

        if item.kind == "joker":
            if len(self.state.jokers) >= self.state.params["joker_slots"]:
                return {"ok": False, "error": "joker slots full"}
            self.state.jokers.append(item.key)
        elif item.kind == "consumable":
            if len(self.state.consumeables) >= self.state.params["consumable_slots"]:
                return {"ok": False, "error": "consumable slots full"}
            self.state.consumeables.append(item.key)
        elif item.kind == "booster":
            self.state.pending_packs = getattr(self.state, "pending_packs", []) + [item.key]
        elif item.kind == "voucher":
            if item.key not in self.state.vouchers:
                self.state.vouchers.append(item.key)

        self.state.dollars -= item.cost
        self.items[index] = None
        return {"ok": True, "item": item, "remaining": self.state.dollars}

    def sell(self, collection: str, index: int) -> dict:
        slots = self.state.jokers if collection == "jokers" else self.state.consumeables
        if not 0 <= index < len(slots):
            return {"ok": False, "error": "bad index"}
        key = slots.pop(index)
        price = max(1, self.state.rng.num("sell", 1, 5))  # v1 fixed-ish sell value
        self.state.dollars += price
        return {"ok": True, "sold": key, "price": price}

    def reroll(self) -> dict:
        if self.state.dollars < self.reroll_cost:
            return {"ok": False, "error": "not enough money"}
        self.state.dollars -= self.reroll_cost
        self.refill()
        self.reroll_cost += config.REROLL_COST_INCREASE
        return {"ok": True, "cost": self.reroll_cost, "remaining": self.state.dollars}