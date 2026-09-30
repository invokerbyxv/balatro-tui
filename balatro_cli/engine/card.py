"""Playing-card / joker-card model, ported from balatro_source_code/card.lua.

Covers the subset of Card needed for hand evaluation + scoring + economy:

- rank -> id/nominal  (``set_base`` ~97, ``get_id`` ~957, ``get_nominal`` ~950)
- ``is_suit`` (~4064) with the flush_calc path
- ``is_face`` (~964) with the Pareidolia override
- enhancement / edition / seal ability tables

Ability model
-------------
Balatro stores a card's mutable effect values in ``self.ability`` (the merged
center config plus runtime counters).  We mirror that: ``card.ability`` is a
plain dict seeded from the enhancement center's ``config`` in centers.json and
then freely mutated at runtime (``played_this_ante``, ``forced_selection``,
``lucky_trigger``, ``perma_bonus``, ...), exactly like the Lua does.

Keys used by the engine (all optional):
    bonus        flat chips added on score        (Bonus / Stone)
    mult         flat mult added on score         (Mult / Lucky)
    x_mult       multiplier applied on score      (Glass)
    h_mult       flat mult while held in hand
    h_x_mult     multiplier while held in hand    (Steel)
    h_dollars    dollars at end of round while held (Gold)
    p_dollars    dollars when scored              (Lucky)
    Xmult        alias used by Glass data
    extra        edition/side value
    perma_bonus  permanent chips gained from Hiker

Enhancements / editions / seals are held as their *center keys* (``m_glass``,
``e_polychrome``, ``s_red``) so that the existing string-based helpers in
``render/text.py`` keep working; the numeric/behavioural data is looked up
through :attr:`Card.ability` and the edition properties.
"""

from __future__ import annotations

from itertools import count

RANK_IDS = {"2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8,
            "9": 9, "T": 10, "J": 11, "Q": 12, "K": 13, "A": 14}
RANK_RANKUPS = {"10": "T", **{r: r for r in RANK_IDS}}
ID_RANKS = {v: k for k, v in RANK_IDS.items()}

SUIT_NAME = {"S": "Spades", "H": "Hearts", "D": "Diamonds", "C": "Clubs"}
SUIT_LETTER = {v: k for k, v in SUIT_NAME.items()}
SUIT_NOMINAL = {"D": 0.01, "C": 0.02, "H": 0.03, "S": 0.04}
FACE_NOMINAL = {"J": 0.1, "Q": 0.2, "K": 0.3, "A": 0.4}

# Enhancement key -> center `effect` string (mirrors card.lua's self.ability.effect)
ENHANCEMENT_EFFECT = {
    "m_bonus": "Bonus Card",
    "m_mult": "Mult Card",
    "m_wild": "Wild Card",
    "m_glass": "Glass Card",
    "m_steel": "Steel Card",
    "m_stone": "Stone Card",
    "m_gold": "Gold Card",
    "m_lucky": "Lucky Card",
}

# Canonical seal names, as used by card.lua (`self.seal == 'Red'`).
SEAL_NAMES = {"red": "Red", "blue": "Blue", "gold": "Gold", "purple": "Purple"}

_stone_uid = count(1)


def rank_nominal(rank: str) -> int:
    """Card nominal (2-10 numeric, faces=10, Ace=11) - the scoring chip base."""
    return RANK_IDS[rank] if rank not in ("J", "Q", "K", "A") else (10 if rank != "A" else 11)


def normalize_seal(seal: str | None) -> str | None:
    if not seal:
        return None
    key = seal.lower()
    if key.startswith("s_"):
        key = key[2:]
    return key if key in SEAL_NAMES else None


def ability_from_config(cfg: dict | None, name: str = "", effect: str = "",
                        set_: str | None = None) -> dict:
    """Build an ability table from a center's `config`, exactly like
    `Card:set_ability` (card.lua:277-299).

    The raw config keys are kept alongside the normalized ones so that effect
    tables may read either `ability["Xmult"]` (as in centers.json) or
    `ability["x_mult"]` (as in the Lua's `self.ability`).
    """
    cfg = dict(cfg or {})
    ability = dict(cfg)                      # raw config keys (compat)
    ability.update({
        "name": name,
        "effect": effect,
        "set": set_,
        "mult": cfg.get("mult", 0) or 0,
        "h_mult": cfg.get("h_mult", 0) or 0,
        "h_x_mult": cfg.get("h_x_mult", 0) or 0,
        "h_dollars": cfg.get("h_dollars", 0) or 0,
        "p_dollars": cfg.get("p_dollars", 0) or 0,
        "t_mult": cfg.get("t_mult", 0) or 0,
        "t_chips": cfg.get("t_chips", 0) or 0,
        "x_mult": cfg.get("Xmult", 1) or 1,
        "h_size": cfg.get("h_size", 0) or 0,
        "d_size": cfg.get("d_size", 0) or 0,
        "extra": cfg.get("extra"),
        "type": cfg.get("type", "") or "",
        "order": cfg.get("order"),
        "perma_bonus": 0,
        "bonus": cfg.get("bonus", 0) or 0,
    })
    return ability


def enhancement_config(enhancement: str | None) -> dict:
    """Merged ability dict for an enhancement center key (``{}`` when unknown)."""
    if not enhancement:
        return {}
    try:
        from ..data import loader
        center = loader.centers().get(enhancement) or {}
    except Exception:  # assets missing -> degrade to no ability
        return {}
    return ability_from_config(center.get("config"), name=center.get("name", ""),
                               effect=center.get("effect")
                               or ENHANCEMENT_EFFECT.get(enhancement, ""),
                               set_=center.get("set"))


def edition_config(edition: str | None) -> dict:
    """Merged edition dict for an edition center key (``{}`` when unknown)."""
    if not edition:
        return {}
    try:
        from ..data import loader
        center = loader.centers().get(edition) or {}
    except Exception:
        return {}
    cfg = dict(center.get("config") or {})
    cfg["type"] = (center.get("name") or edition[2:] if edition.startswith("e_") else edition).lower()
    return cfg


class Card:
    """A playing card or a joker/consumable, mirroring card.lua's Card."""

    __slots__ = ("rank", "suit", "enhancement", "edition", "seal", "debuffed",
                 "ability", "is_joker", "key", "unique_val", "shattered")

    def __init__(self, rank: str, suit: str, enhancement: str | None = None,
                 edition: str | None = None, seal: str | None = None):
        self.rank = rank
        self.suit = suit
        # enhancement: 'm_bonus', 'm_mult', 'm_glass', ... (Enhanced set key)
        self.enhancement = enhancement
        # edition: 'e_foil', 'e_holo', 'e_polychrome', 'e_negative'
        self.edition = edition
        # seal: 'red' | 'blue' | 'gold' | 'purple'  (card.lua's 'Red'/'Blue'/...)
        self.seal = normalize_seal(seal)
        self.debuffed = False
        # runtime ability table (bonus/mult/x_mult/h_*/p_dollars + counters)
        self.ability: dict = enhancement_config(enhancement)
        # the two fields below let a Card double as a joker/consumable carrier
        self.is_joker = False
        self.key: str | None = None
        self.unique_val = 0
        # Glass Card shatter flag (card.lua's `v.shattered`).
        self.shattered = False

    # -- identity -------------------------------------------------------------
    @property
    def id(self) -> int:
        """Mirror Card:get_id(): stone cards get a unique negative id."""
        if self.enhancement == "m_stone":
            if not self.unique_val:
                self.unique_val = -next(_stone_uid)
            return self.unique_val
        return RANK_IDS[self.rank]

    @property
    def is_face(self) -> bool:
        """Mirror Card:is_face() (debuff-aware callers use the blind's variant)."""
        if self.debuffed:
            return False
        return self.id in (11, 12, 13)

    @property
    def effect(self) -> str:
        return self.ability.get("effect", "")

    @property
    def edition_type(self) -> str | None:
        if not self.edition:
            return None
        return self.edition[2:] if self.edition.startswith("e_") else self.edition

    def nominal(self) -> float:
        base = rank_nominal(self.rank)
        base = -1000 if self.enhancement == "m_stone" else base
        return base + SUIT_NOMINAL[self.suit] + FACE_NOMINAL.get(self.rank, 0.0)

    def is_suit(self, suit: str, wild_beats_double: bool = False) -> bool:
        """Mirror is_suit(flush_calc): stone is never a suit; Wild counts for all."""
        if self.debuffed:
            return False
        if self.enhancement == "m_stone":
            return False
        if self.enhancement == "m_wild":
            return True
        return self.suit == suit

    def set_debuff(self, value: bool = True) -> None:
        self.debuffed = bool(value)

    # -- chip / mult contributions (card.lua 976-1031) -------------------------
    def get_chip_bonus(self) -> int:
        if self.debuffed:
            return 0
        if self.effect == "Stone Card":
            return self.ability.get("bonus", 0) + self.ability.get("perma_bonus", 0)
        return rank_nominal(self.rank) + self.ability.get("bonus", 0) + self.ability.get("perma_bonus", 0)

    def get_chip_mult(self, rng=None) -> int:
        """Flat mult. Lucky cards roll; without an rng the roll is skipped."""
        if self.debuffed:
            return 0
        if self.effect == "Lucky Card":
            if rng is None:
                return 0
            if rng.chance("lucky_mult", 5):
                self.ability["lucky_trigger"] = True
                return self.ability.get("mult", 0)
            return 0
        return self.ability.get("mult", 0)

    def get_chip_x_mult(self) -> float:
        if self.debuffed:
            return 0.0
        x = self.ability.get("x_mult", 1) or 1
        if x <= 1:
            return 0.0
        return float(x)

    def get_chip_h_mult(self) -> int:
        if self.debuffed:
            return 0
        return self.ability.get("h_mult", 0)

    def get_chip_h_x_mult(self) -> float:
        if self.debuffed:
            return 0.0
        return float(self.ability.get("h_x_mult", 0) or 0)

    def get_p_dollars(self, rng=None) -> int:
        """Card:get_p_dollars() - Gold seal +$3, Lucky card rolls $20."""
        if self.debuffed:
            return 0
        ret = 3 if self.seal == "gold" else 0
        p = self.ability.get("p_dollars", 0) or 0
        if p > 0:
            if self.effect == "Lucky Card":
                if rng is not None and rng.chance("lucky_money", 15):
                    self.ability["lucky_trigger"] = True
                    ret += p
            else:
                ret += p
        return ret

    def get_edition_effect(self) -> dict:
        """Card:get_edition() -> {chip_mod / mult_mod / x_mult_mod}."""
        if self.debuffed or not self.edition:
            return {}
        cfg = edition_config(self.edition)
        out: dict = {}
        if self.edition == "e_holo":
            out["mult_mod"] = cfg.get("extra", 10)
        elif self.edition == "e_foil":
            out["chip_mod"] = cfg.get("extra", 50)
        elif self.edition == "e_polychrome":
            out["x_mult_mod"] = cfg.get("extra", 1.5)
        return out

    @property
    def negative(self) -> bool:
        return self.edition == "e_negative"

    # -- economy --------------------------------------------------------------
    @property
    def sell_cost(self) -> int:
        return max(1, 0 if self.enhancement else 1)

    def copy(self) -> "Card":
        c = Card(self.rank, self.suit, self.enhancement, self.edition,
                 f"s_{self.seal}" if self.seal else None)
        c.debuffed = self.debuffed
        c.ability = dict(self.ability)
        c.unique_val = self.unique_val
        return c

    def __repr__(self) -> str:
        seal = f":{self.seal}" if self.seal else ""
        enh = f"[{self.enhancement}]" if self.enhancement else ""
        return f"{self.rank}{self.suit}{enh}{seal}"

    # -- ordering helpers ------------------------------------------------------
    def sort_key(self) -> tuple:
        return (self.rank in RANK_IDS and RANK_IDS[self.rank] or 0, self.suit)


def card_id(rank: str) -> int:
    return RANK_IDS[rank]


def new_playing_card(rank: str, suit: str, enhancement: str | None = None,
                     edition: str | None = None, seal: str | None = None) -> Card:
    return Card(rank, suit, enhancement, edition, seal)


class JokerCard(Card):
    """A joker/consumable carrier card (card.lua ability.set == 'Joker').

    Keeps per-joker runtime counters (``ability.mult``, tallies, x_mult, ...)
    which the joker effect table mutates exactly like the Lua ``self.ability``.
    """

    __slots__ = ()

    def __init__(self, key: str, name: str = "", cfg: dict | None = None,
                 edition: str | None = None, rarity: int = 1, cost: int = 0,
                 set_: str = "Joker"):
        super().__init__("J", "S", None, edition, None)
        self.key = key
        self.is_joker = set_ == "Joker"
        self.ability = ability_from_config(cfg, name=name or key, set_=set_)
        self.ability["rarity"] = rarity
        self.ability["cost"] = cost

    def __eq__(self, other) -> bool:
        """Compare against another carrier card *or* a bare centers key."""
        if isinstance(other, str):
            return self.key == other
        if isinstance(other, Card):
            return self.key == getattr(other, "key", None) and self is other
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.key)

    def __repr__(self) -> str:
        return f"<{self.key}>"
