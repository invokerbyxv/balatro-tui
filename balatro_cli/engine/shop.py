"""Shop model + economy, ported from `button_callbacks.lua`.

Shop layout (`game.lua` shop creation)::

    [ card slot ] x shop_size        (jokers / tarots / planets)
    [ booster  ] x booster_slots
    [ voucher  ] x voucher_slots

* `shop_size` starts at 2 and grows with Overstock / Overstock+ (`v_overstock_norm`
  / `v_overstock_plus`), i.e. `state.shop_size`.
* Booster slots hold a weighted-random pack key (`get_pack`).
* The single voucher slot offers the next unredeemed, requirement-satisfied
  voucher (`get_next_voucher_key`, common_events.lua:1901).

Card slots are jokers 75% of the time, otherwise a consumable; the
Tarot/Planet merchant vouchers bias that split (`state.tarot_rate`,
`state.planet_rate`).

Rerolling replaces the card slots and raises the reroll cost for the rest of the
visit (`G.GAME.current_round.reroll_cost_increase`), except for Chaos the Clown
free rerolls.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import config
from ..data import loader
from . import packs
from .card import Card
from . import consumable as _legacy_consumable  # noqa: F401  (compat import)

RARITY_P = [("common", 1, 0.70), ("uncommon", 2, 0.25), ("rare", 3, 0.04), ("legendary", 4, 0.01)]


@dataclass
class ShopItem:
    index: int
    kind: str          # 'joker' | 'consumable' | 'booster' | 'voucher'
    key: str
    name: str
    cost: int
    data: dict | None = None
    card: object | None = None    # live JokerCard when a tag slotted one in

    def describe(self) -> str:
        tag = {"joker": "J", "consumable": "C", "booster": "B", "voucher": "V"}.get(self.kind, "?")
        return f"[{self.index}]{tag}:{self.name} ${self.cost}"

    @property
    def set(self) -> str | None:
        return (self.data or {}).get("set")


class Shop:
    def __init__(self, state):
        self.state = state
        self.items: list[ShopItem | None] = []
        self.vouchers: list[ShopItem | None] = []
        self.reroll_cost = config.STARTING_PARAMS["reroll_cost"]
        self.rerolls_used = 0
        self.active = True
        state.shop = self

    # -- generation ---------------------------------------------------------
    def refill(self, full: bool = True) -> None:
        """Fill the card / booster / voucher slots for this shop visit."""
        state = self.state
        pools = state.pools
        rng = state.rng
        if full:
            # a D6 Tag makes this shop's rerolls start free (tag.lua:382)
            base = 0 if getattr(state, "shop_d6ed", False) else state.params["reroll_cost"]
            self.reroll_cost = max(0, base + state.reroll_cost_delta)
            self.rerolls_used = 0

        self.items = []
        for i in range(max(0, state.shop_size)):
            kind, key, name, cost, data = self._gen_slot(pools, rng)
            self.items.append(ShopItem(index=i, kind=kind, key=key, name=name,
                                       cost=self._price(cost), data=data))

        boosters = pools.get("Booster") or []
        for b in range(max(0, state.booster_slots)):
            if not boosters:
                break
            weights = [float(x.get("weight", 1) or 1) for x in boosters]
            pack = rng.weighted_pick("shop_booster", boosters, weights)
            cost = int(pack.get("cost", 4) or 4)
            if "celestial" in str(pack.get("key", "")) and \
                    "Astronomer" in state.joker_keys:
                cost = 0                    # card.lua:380 - Celestial free
            self.items.append(ShopItem(index=len(self.items), kind="booster",
                                       key=pack.get("key"), name=pack.get("name", "Booster"),
                                       cost=self._price(cost), data=pack))

        self.vouchers = []
        for v in range(max(0, state.voucher_slots)):
            key = self._next_voucher_key()
            if not key:
                break
            center = loader.centers().get(key) or {}
            self.vouchers.append(ShopItem(index=len(self.items), kind="voucher", key=key,
                                          name=center.get("name", key),
                                          cost=self._price(center.get("cost", 10)),
                                          data=center))

    def refill_vouchers(self) -> None:
        """Re-run the voucher slot roll (Voucher Tag added a slot)."""
        state = self.state
        while len(self.vouchers) < max(0, state.voucher_slots):
            key = self._next_voucher_key()
            if not key:
                break
            center = loader.centers().get(key) or {}
            self.vouchers.append(ShopItem(index=len(self.items) + len(self.vouchers),
                                          kind="voucher", key=key,
                                          name=center.get("name", key),
                                          cost=self._price(center.get("cost", 10)),
                                          data=center))

    def _price(self, cost: int) -> int:
        """Clearance Sale / Liquidation discount."""
        discount = 0
        if "v_clearance_sale" in self.state.used_vouchers:
            discount = 0.25
        if "v_liquidation" in self.state.used_vouchers:
            discount = 0.5
        if discount:
            return max(0, int(cost * (1 - discount)))
        return int(cost)

    def _gen_slot(self, pools, rng):
        """The shop card-slot roll (UI_definitions.lua:764-786).

        Weighted over joker/tarot/planet/playing-card/spectral rates; the Lua
        defaults are 20/4/4/0/0 (game.lua:1901-1905) and the merchant vouchers
        store a *multiplier* over the 4-base weights.  Card creation goes
        through ``packs.create_card`` so rarity, pool filtering and editions
        match the rest of the game.
        """
        state = self.state
        illusion = "v_illusion" in state.used_vouchers
        rates = [("Joker", float(getattr(state, "joker_rate", 20) or 0)),
                 ("Tarot", 4.0 * float(getattr(state, "tarot_rate", 1) or 1)),
                 ("Planet", 4.0 * float(getattr(state, "planet_rate", 1) or 1)),
                 ("Base", float(getattr(state, "playing_card_rate", 0) or 0)),
                 ("Spectral", float(getattr(state, "spectral_rate", 0) or 0))]
        total = sum(w for _, w in rates) or 1.0
        roll = rng.rand("cdt" + str(state.ante)) * total
        # UI_definitions.lua:772 - the Illusion poll is evaluated eagerly when
        # the slot table is built, before the pool roll is matched.
        enhanced_pool = illusion and rng.rand("illusion") > 0.6
        acc = 0.0
        type_ = "Joker"
        for name, weight in rates:
            acc += weight
            if acc >= roll > acc - weight:
                type_ = name
                break
        if type_ == "Base" and enhanced_pool:
            type_ = "Enhanced"
        card = packs.create_card(state, type_, key_append="sho")
        # UI_definitions.lua:786-792 - Illusion can stamp an edition on a
        # shop playing card: 20% chance, then poly >0.85 / holo >0.5 / foil.
        if illusion and type_ in ("Base", "Enhanced") and isinstance(card, Card):
            if rng.rand("illusion") > 0.8:
                poll = rng.rand("illusion")
                if poll > 0.85:
                    card.edition = "e_polychrome"
                elif poll > 0.5:
                    card.edition = "e_holo"
                else:
                    card.edition = "e_foil"
        set_ = getattr(card, "set", None) or type_
        if set_ == "Joker":
            kind = "joker"
        elif set_ in ("Tarot", "Planet", "Spectral"):
            kind = "consumable"
        else:                                   # Base / Enhanced playing card
            kind = "playing_card"
        cost = int(((getattr(card, "ability", None) or {}).get("cost", 0)) or 0)
        if kind == "consumable" and set_ == "Planet" and \
                "Astronomer" in self.state.joker_keys:
            cost = 0                        # card.lua:380 - Astronomer
        return kind, card.key, getattr(card, "name", card.key) or card.key, cost, card

    def _next_voucher_key(self) -> str | None:
        """`get_next_voucher_key` (common_events.lua:1901)."""
        state = self.state
        owned = state.used_vouchers
        pool = state.pools.get("Voucher") or []
        candidates = []
        for c in pool:
            key = c["key"]
            if key in owned or key in state.banned_keys:
                continue
            requires = c.get("requires") or []
            if isinstance(requires, str):
                requires = [requires]
            if all(r in owned for r in requires):
                candidates.append(c)
        if not candidates:
            return None
        # the Lua takes the first unowned voucher in order
        return candidates[0]["key"]

    # -- actions ------------------------------------------------------------
    def buy(self, index: int) -> dict:
        if not self.active:
            return {"ok": False, "error": "shop closed"}
        item = self._item(index)
        if item is None:
            return {"ok": False, "error": "bad index"}
        state = self.state
        if state.dollars < item.cost:
            return {"ok": False, "error": "not enough money"}

        if item.kind == "joker":
            if len(state.jokers) >= state.params["joker_slots"]:
                return {"ok": False, "error": "joker slots full"}
            state.add_joker(item.key, edition=getattr(item.data, "edition", None)
                            if not isinstance(item.data, dict) else None)
            state.eval_hooks("buying_card", other_card=item.data)
        elif item.kind == "consumable":
            if len(state.consumeables) >= state.params["consumable_slots"]:
                return {"ok": False, "error": "consumable slots full"}
            state.add_consumable(item.key)
            state.eval_hooks("buying_card", other_card=item.data)
        elif item.kind == "playing_card":
            card = item.data if hasattr(item.data, "rank") else None
            if card is None:
                return {"ok": False, "error": "no card"}
            state._add_playing_card(card)
            state.eval_hooks("buying_card", other_card=card)
        elif item.kind == "booster":
            state.dollars -= item.cost
            self._consume(index)
            pack = state.open_pack(item.key)
            return {"ok": True, "item": item, "remaining": state.dollars, "pack": pack}
        elif item.kind == "voucher":
            result = state.redeem_voucher(item.key)
            if not result.get("ok"):
                return {"ok": False, "error": result.get("error", "cannot redeem")}
            state.dollars -= item.cost
            self._consume(index)
            return {"ok": True, "item": item, "remaining": state.dollars,
                    "redeem": result}

        state.dollars -= item.cost
        self._consume(index)
        return {"ok": True, "item": item, "remaining": state.dollars}

    def _item(self, index: int) -> ShopItem | None:
        for it in list(self.items) + list(self.vouchers):
            if it is not None and it.index == index:
                return it
        if 0 <= index < len(self.items):
            return self.items[index]
        return None

    def _consume(self, index: int) -> None:
        for coll in (self.items, self.vouchers):
            for i, it in enumerate(coll):
                if it is not None and it.index == index:
                    coll[i] = None
                    return

    def sell(self, collection: str, index: int) -> dict:
        state = self.state
        if collection == "jokers":
            return state.sell_joker(index)
        return state.sell_consumable(index)

    def reroll(self) -> dict:
        state = self.state
        free = int(state.current_round.get("free_rerolls", 0) or 0)
        if free > 0:
            state.current_round["free_rerolls"] = free - 1
            cost = 0
        else:
            cost = self.reroll_cost
            if state.dollars < cost:
                return {"ok": False, "error": "not enough money"}
            state.dollars -= cost
            self.reroll_cost += config.REROLL_COST_INCREASE
            self.rerolls_used += 1
        state.eval_hooks("reroll_shop")
        # the Lua restocks only the card slots; packs and vouchers stay
        # (button_callbacks.lua:2873-2886)
        self._refill_card_slots()
        return {"ok": True, "cost": cost, "remaining": state.dollars,
                "reroll_cost": self.reroll_cost}

    def _refill_card_slots(self) -> None:
        """Reroll restocks G.shop_jokers only; a Coupon Tag keeps them free."""
        state = self.state
        free = bool(getattr(state, "shop_free", False))
        for i, item in enumerate(self.items):
            if item is not None and item.kind == "booster":
                continue
            kind, key, name, cost, data = self._gen_slot(state.pools, state.rng)
            price = 0 if free else self._price(cost)
            self.items[i] = ShopItem(index=i, kind=kind, key=key, name=name,
                                     cost=price, data=data)

    # -- description --------------------------------------------------------
    def describe(self) -> str:
        parts = [it.describe() if it else "---sold---" for it in self.items]
        if self.vouchers:
            parts += [it.describe() if it else "---sold---" for it in self.vouchers]
        return " ".join(parts)

    def all_items(self) -> list[ShopItem]:
        return [it for it in (list(self.items) + list(self.vouchers)) if it]
