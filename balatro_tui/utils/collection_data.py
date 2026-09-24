"""收藏界面数据源:加载 game.lua 定义 + zh_CN 描述,构造每行的 #n# 填充值。

#n# 的取值逻辑参照游戏源码 card.lua:generate_UIBox_ability_table、
common_events.lua:generate_card_ui、tag.lua、back.lua。
动态数值按预览口径静态化:概率 normal=1、累计加成取初始值(0 或基础值)。
"""
from __future__ import annotations

from .loc_text import describe, load_descriptions, loc_name, render_text
from .lua_data import get_config, load_definitions

HAND_ZH = {
    "High Card": "高牌",
    "Pair": "对子",
    "Two Pair": "两对",
    "Three of a Kind": "三条",
    "Straight": "顺子",
    "Flush": "同花",
    "Full House": "葫芦",
    "Four of a Kind": "四条",
    "Straight Flush": "同花顺",
    "Five of a Kind": "五条",
    "Flush House": "同花葫芦",
    "Flush Five": "同花五条",
}
SUIT_ZH = {"Spades": "黑桃", "Hearts": "红桃", "Clubs": "梅花", "Diamonds": "方片"}
RARITY_ZH = {1: "普通", 2: "罕见", 3: "稀有", 4: "传奇"}
PH_ZH = {"ph_most_played": "最常用的牌型"}


def _hand(name):
    return HAND_ZH.get(name, name or "")


def _suit(name):
    return SUIT_ZH.get(name, name or "")


def _e(enh_key):
    return loc_name("Enhanced", enh_key or "")


# --------------------------------------------------------------- 小丑牌
# 键为 game.lua 中的英文名,值为 (config) -> vars 列表,对照 card.lua 的 loc_vars 链
JOKER_VARS = {
    "Joker": lambda c: [c.get("mult")],
    "Jolly Joker": lambda c: [c.get("t_mult"), _hand(c.get("type"))],
    "Zany Joker": lambda c: [c.get("t_mult"), _hand(c.get("type"))],
    "Mad Joker": lambda c: [c.get("t_mult"), _hand(c.get("type"))],
    "Crazy Joker": lambda c: [c.get("t_mult"), _hand(c.get("type"))],
    "Droll Joker": lambda c: [c.get("t_mult"), _hand(c.get("type"))],
    "Sly Joker": lambda c: [c.get("t_chips"), _hand(c.get("type"))],
    "Wily Joker": lambda c: [c.get("t_chips"), _hand(c.get("type"))],
    "Clever Joker": lambda c: [c.get("t_chips"), _hand(c.get("type"))],
    "Devious Joker": lambda c: [c.get("t_chips"), _hand(c.get("type"))],
    "Crafty Joker": lambda c: [c.get("t_chips"), _hand(c.get("type"))],
    "Half Joker": lambda c: [c["extra"]["mult"], c["extra"]["size"]],
    "Fortune Teller": lambda c: [c.get("extra"), 0],
    "Steel Joker": lambda c: [c.get("extra"), 1],
    "Chaos the Clown": lambda c: [c.get("extra")],
    "Space Joker": lambda c: [1, c.get("extra")],
    "Stone Joker": lambda c: [c.get("extra"), 0],
    "Drunkard": lambda c: [c.get("d_size")],
    "Green Joker": lambda c: [c["extra"]["hand_add"], c["extra"]["discard_sub"], 0],
    "Credit Card": lambda c: [c.get("extra")],
    "Greedy Joker": lambda c: [c["extra"]["s_mult"], _suit(c["extra"]["suit"])],
    "Lusty Joker": lambda c: [c["extra"]["s_mult"], _suit(c["extra"]["suit"])],
    "Wrathful Joker": lambda c: [c["extra"]["s_mult"], _suit(c["extra"]["suit"])],
    "Gluttonous Joker": lambda c: [c["extra"]["s_mult"], _suit(c["extra"]["suit"])],
    "Blue Joker": lambda c: [c.get("extra"), (c.get("extra") or 0) * 52],
    "Hack": lambda c: [(c.get("extra") or 0) + 1],
    "Faceless Joker": lambda c: [c["extra"]["dollars"], c["extra"]["faces"]],
    "Juggler": lambda c: [c.get("h_size")],
    "Golden Joker": lambda c: [c.get("extra")],
    "Joker Stencil": lambda c: [c.get("x_mult", c.get("Xmult", 1))],
    "Ceremonial Dagger": lambda c: [c.get("mult")],
    "Banner": lambda c: [c.get("extra")],
    "Mystic Summit": lambda c: [c["extra"]["mult"], c["extra"]["d_remaining"]],
    "Loyalty Card": lambda c: [c["extra"]["Xmult"], c["extra"]["every"], c["extra"].get("remaining")],
    "8 Ball": lambda c: [1, c.get("extra")],
    "Dusk": lambda c: [(c.get("extra") or 0) + 1],
    "Fibonacci": lambda c: [c.get("extra")],
    "Scary Face": lambda c: [c.get("extra")],
    "Abstract Joker": lambda c: [c.get("extra"), 0],
    "Delayed Gratification": lambda c: [c.get("extra")],
    "Gros Michel": lambda c: [c["extra"]["mult"], 1, c["extra"]["odds"]],
    "Even Steven": lambda c: [c.get("extra")],
    "Odd Todd": lambda c: [c.get("extra")],
    "Scholar": lambda c: [c["extra"]["mult"], c["extra"]["chips"]],
    "Business Card": lambda c: [1, c.get("extra")],
    "Spare Trousers": lambda c: [c.get("extra"), _hand("Two Pair"), 0],
    "Ride the Bus": lambda c: [c.get("extra"), 0],
    "Egg": lambda c: [c.get("extra")],
    "Burglar": lambda c: [c.get("extra")],
    "Blackboard": lambda c: [c.get("extra"), _suit("Spades"), _suit("Clubs")],
    "Runner": lambda c: [c["extra"]["chips"], c["extra"]["chip_mod"]],
    "Ice Cream": lambda c: [c["extra"]["chips"], c["extra"]["chip_mod"]],
    "Constellation": lambda c: [c.get("extra"), 1],
    "Hiker": lambda c: [c.get("extra")],
    "To Do List": lambda c: [c["extra"]["dollars"], _hand(c.get("to_do_poker_hand") or "Pair")],
    "Astronomer": lambda c: [c.get("extra")],
    "Golden Ticket": lambda c: [c.get("extra")],
    "Acrobat": lambda c: [c.get("extra")],
    "Sock and Buskin": lambda c: [(c.get("extra") or 0) + 1],
    "Swashbuckler": lambda c: [0],
    "Troubadour": lambda c: [c["extra"]["h_size"], -(c["extra"].get("h_plays") or 0)],
    "Certificate": lambda c: [c.get("extra")],
    "Throwback": lambda c: [c.get("extra"), 1],
    "Hanging Chad": lambda c: [c.get("extra")],
    "Rough Gem": lambda c: [c.get("extra")],
    "Bloodstone": lambda c: [1, c["extra"]["odds"], c["extra"]["Xmult"]],
    "Arrowhead": lambda c: [c.get("extra")],
    "Onyx Agate": lambda c: [c.get("extra")],
    "Glass Joker": lambda c: [c.get("extra"), 1],
    "Flower Pot": lambda c: [c.get("extra")],
    "Wee Joker": lambda c: [c["extra"]["chips"], c["extra"]["chip_mod"]],
    "Merry Andy": lambda c: [c.get("d_size"), c.get("h_size")],
    "The Idol": lambda c: [c.get("extra"), "Q", _suit("Hearts")],
    "Seeing Double": lambda c: [c.get("extra")],
    "Matador": lambda c: [c.get("extra")],
    "Hit the Road": lambda c: [c.get("extra"), 1],
    "The Duo": lambda c: [c.get("Xmult", c.get("x_mult")), _hand(c.get("type"))],
    "The Trio": lambda c: [c.get("Xmult", c.get("x_mult")), _hand(c.get("type"))],
    "The Family": lambda c: [c.get("Xmult", c.get("x_mult")), _hand(c.get("type"))],
    "The Order": lambda c: [c.get("Xmult", c.get("x_mult")), _hand(c.get("type"))],
    "The Tribe": lambda c: [c.get("Xmult", c.get("x_mult")), _hand(c.get("type"))],
    "Cavendish": lambda c: [c["extra"]["Xmult"], 1, c["extra"]["odds"]],
    "Card Sharp": lambda c: [c["extra"]["Xmult"]],
    "Red Card": lambda c: [c.get("extra"), 0],
    "Madness": lambda c: [c.get("extra"), 1],
    "Square Joker": lambda c: [c["extra"]["chips"], c["extra"]["chip_mod"]],
    "Seance": lambda c: [_hand((c.get("extra") or {}).get("poker_hand") or "Straight Flush")],
    "Riff-raff": lambda c: [c.get("extra")],
    "Vampire": lambda c: [c.get("extra"), 1],
    "Hologram": lambda c: [c.get("extra"), 1],
    "Vagabond": lambda c: [c.get("extra")],
    "Baron": lambda c: [c.get("extra")],
    "Cloud 9": lambda c: [c.get("extra"), 0],
    "Rocket": lambda c: [c["extra"]["dollars"], c["extra"]["increase"]],
    "Obelisk": lambda c: [c.get("extra"), 1],
    "Photograph": lambda c: [c.get("extra")],
    "Gift Card": lambda c: [c.get("extra")],
    "Turtle Bean": lambda c: [c["extra"]["h_size"], c["extra"]["h_mod"]],
    "Erosion": lambda c: [c.get("extra"), 0, 52],
    "Reserved Parking": lambda c: [c["extra"]["dollars"], 1, c["extra"]["odds"]],
    "Mail-In Rebate": lambda c: [c.get("extra"), "8"],
    "To the Moon": lambda c: [c.get("extra")],
    "Hallucination": lambda c: [1, c.get("extra")],
    "Lucky Cat": lambda c: [c.get("extra"), 1],
    "Baseball Card": lambda c: [c.get("extra")],
    "Bull": lambda c: [c.get("extra"), 0],
    "Diet Cola": lambda c: [loc_name("Tag", "tag_double")],
    "Trading Card": lambda c: [c.get("extra")],
    "Flash Card": lambda c: [c.get("extra"), 0],
    "Popcorn": lambda c: [c.get("mult"), c.get("extra")],
    "Ramen": lambda c: [c.get("Xmult"), c.get("extra")],
    "Ancient Joker": lambda c: [c.get("extra"), _suit(c.get("ancient_suit") or "Spades")],
    "Walkie Talkie": lambda c: [c["extra"]["chips"], c["extra"]["mult"]],
    "Seltzer": lambda c: [c.get("extra")],
    "Castle": lambda c: [c["extra"]["chip_mod"], _suit(c.get("castle_suit") or "Spades"), c["extra"]["chips"]],
    "Smiley Face": lambda c: [c.get("extra")],
    "Campfire": lambda c: [c.get("extra"), 1],
    "Stuntman": lambda c: [c["extra"]["chip_mod"], c["extra"]["h_size"]],
    "Invisible Joker": lambda c: [c.get("extra"), 0],
    "Satellite": lambda c: [c.get("extra"), 0],
    "Shoot the Moon": lambda c: [c.get("extra")],
    "Driver's License": lambda c: [c.get("extra"), 0],
    "Bootstraps": lambda c: [c["extra"]["mult"], c["extra"]["dollars"], 0],
    "Caino": lambda c: [c.get("extra"), 1],
    "Triboulet": lambda c: [c.get("extra")],
    "Yorick": lambda c: [c["extra"]["xmult"], c["extra"]["discards"], 0, 1],
    "Chicot": lambda c: [],
    "Perkeo": lambda c: [c.get("extra")],
}


def joker_vars(name: str, cfg: dict) -> list:
    fn = JOKER_VARS.get(name)
    if fn:
        try:
            return fn(cfg)
        except (KeyError, TypeError):
            pass
    extra = cfg.get("extra")
    return [extra] if isinstance(extra, (int, float)) else []


# --------------------------------------------------------------- 其他类别
def tarot_vars(key: str, cfg: dict) -> list:
    if key == "c_wheel_of_fortune":
        return [1, cfg.get("extra")]
    if key == "c_hermit":
        return [cfg.get("extra")]
    if key == "c_temperance":
        return [cfg.get("extra"), 0]
    if key == "c_high_priestess":
        return [cfg.get("planets")]
    if key == "c_emperor":
        return [cfg.get("tarots")]
    mh = cfg.get("max_highlighted")
    mod = cfg.get("mod_conv")
    if mod and mod not in ("up_rank", "card"):
        return [mh, _e(mod)]
    if key == "c_strength":
        return [mh]
    if cfg.get("suit_conv"):
        return [mh, _suit(cfg["suit_conv"])]
    if mh:
        return [mh]
    return []


def planet_vars(cfg: dict, hands: dict) -> list:
    ht = cfg.get("hand_type") or ""
    lv = hands.get(ht, {})
    return [1, _hand(ht), lv.get("l_mult"), lv.get("l_chips")]


def spectral_vars(key: str, cfg: dict) -> list:
    e = cfg.get("extra")
    if key == "c_immolate" and isinstance(e, dict):
        return [e.get("destroy"), e.get("dollars")]
    if key == "c_ectoplasm":
        return [1]
    return [e] if isinstance(e, (int, float)) else []


def voucher_vars(cfg: dict) -> list:
    e = cfg.get("extra")
    return [] if e is None else [e]


def back_vars(key: str, cfg: dict) -> list:
    table = {
        "b_red": [cfg.get("discards")],
        "b_blue": [cfg.get("hands")],
        "b_yellow": [cfg.get("dollars")],
        "b_green": [cfg.get("extra_hand_bonus"), cfg.get("extra_discard_bonus")],
        "b_black": [cfg.get("joker_slot"), abs(cfg.get("hands") or 0)],
        "b_painted": [cfg.get("hand_size"), cfg.get("joker_slot")],
        "b_magic": [loc_name("Voucher", "v_crystal_ball"), loc_name("Tarot", "c_fool")],
        "b_nebula": [loc_name("Voucher", "v_telescope"), cfg.get("consumable_slot")],
        "b_zodiac": [
            loc_name("Voucher", "v_tarot_merchant"),
            loc_name("Voucher", "v_planet_merchant"),
            loc_name("Voucher", "v_overstock_norm"),
        ],
        "b_anaglyph": [loc_name("Tag", "tag_double")],
        "b_plasma": [cfg.get("ante_scaling")],
    }
    return table.get(key, [])


def enhanced_vars(key: str, cfg: dict) -> list:
    return {
        "m_glass": [cfg.get("Xmult"), 1, cfg.get("extra")],
        "m_gold": [cfg.get("h_dollars")],
        "m_lucky": [1, cfg.get("mult"), 5, cfg.get("dollars", cfg.get("p_dollars")), 15],
        "m_mult": [cfg.get("mult")],
        "m_steel": [cfg.get("h_x_mult")],
        "m_stone": [cfg.get("bonus")],
        "m_bonus": [cfg.get("bonus")],
    }.get(key, [])


def tag_vars(key: str, cfg: dict) -> list:
    return {
        "tag_investment": [cfg.get("dollars")],
        "tag_handy": [cfg.get("dollars_per_hand"), 0],
        "tag_garbage": [cfg.get("dollars_per_discard"), 0],
        "tag_juggle": [cfg.get("h_size")],
        "tag_top_up": [cfg.get("spawn_jokers")],
        "tag_skip": [cfg.get("skip_bonus"), cfg.get("skip_bonus")],
        "tag_orbital": [_hand("High Card"), cfg.get("levels")],
        "tag_economy": [cfg.get("max")],
    }.get(key, [])


def blind_vars(entry: dict) -> list:
    out = []
    for v in entry.get("vars") or []:
        if isinstance(v, str) and v.startswith("localize:"):
            out.append(PH_ZH.get(v.split(":", 1)[1], ""))
        else:
            out.append(v)
    return out


# --------------------------------------------------------------- 行组装
def _desc(set_name: str, key: str, vars_: list) -> str:
    return describe(set_name, key, vars_) or "—"


def get_hand_levels(levels: dict | None = None) -> list[dict]:
    levels = levels or {}
    hands = load_definitions()["_hands"]
    rows = []
    for key, h in hands.items():
        lv = levels.get(key, h.get("level", 1))
        rows.append({
            "name": _hand(key),
            "level": lv,
            "chips": h.get("s_chips", 0) + h.get("l_chips", 0) * (lv - 1),
            "mult": h.get("s_mult", 0) + h.get("l_mult", 0) * (lv - 1),
            "_o": _order_of(h),
        })
    rows.sort(key=lambda r: r["_o"])
    for r in rows:
        r.pop("_o")
    return rows


def get_vouchers(owned: list[str] | None = None) -> list[dict]:
    defs = load_definitions()
    loc = load_descriptions()
    owned = set(owned) if owned is not None else None
    rows = []
    for key, entry in loc["Voucher"].items():
        if owned is not None and key not in owned:
            continue
        c = (defs.get("Voucher") or {}).get(key) or {}
        rows.append({
            "name": entry.get("name") or key,
            "desc": _desc("Voucher", key, voucher_vars(get_config(c))),
            "rarity": "高阶" if c.get("requires") else "基础",
            "price": str(c.get("cost") or "—"),
            "_o": _order_of(c),
        })
    rows.sort(key=lambda r: r["_o"])
    for r in rows:
        r.pop("_o")
    return rows


_INF = float("inf")


def _order_of(entry: dict) -> float:
    """game.lua 各收藏池统一按 order 升序排序(game.lua:826-842)。

    Back 池实际按 order-(unlocked and 100) 排序,预览视为全部解锁,等价于按 order。
    """
    o = entry.get("order") if entry else None
    return o if isinstance(o, (int, float)) else _INF


def get_rows(category: str) -> list[dict]:
    defs = load_definitions()
    loc = load_descriptions()
    rows: list[dict] = []

    def center(set_name: str, key: str) -> dict:
        return (defs.get(set_name) or {}).get(key) or {}

    if category == "jokers":
        for key, entry in loc["Joker"].items():
            c = center("Joker", key)
            cfg = get_config(c)
            rows.append({
                "name": entry.get("name") or key,
                "desc": _desc("Joker", key, joker_vars(c.get("name", ""), cfg)),
                "price": str(c.get("cost") or "—"),
                "rarity": RARITY_ZH.get(c.get("rarity"), "—"),
                "_o": _order_of(c),
            })
    elif category in ("tarots", "planets", "spectrals"):
        set_name = {"tarots": "Tarot", "planets": "Planet", "spectrals": "Spectral"}[category]
        for key, entry in loc[set_name].items():
            c = center(set_name, key)
            cfg = get_config(c)
            if set_name == "Tarot":
                vars_ = tarot_vars(key, cfg)
            elif set_name == "Planet":
                vars_ = planet_vars(cfg, defs["_hands"])
            else:
                vars_ = spectral_vars(key, cfg)
            rows.append({
                "name": entry.get("name") or key,
                "desc": _desc(set_name, key, vars_),
                "price": str(c.get("cost") or "—"),
                "rarity": "—",
                "_o": _order_of(c),
            })
    elif category == "vouchers":
        for key, entry in loc["Voucher"].items():
            c = center("Voucher", key)
            rows.append({
                "name": entry.get("name") or key,
                "desc": _desc("Voucher", key, voucher_vars(get_config(c))),
                "price": str(c.get("cost") or "—"),
                "rarity": "高阶" if c.get("requires") else "基础",
                "_o": _order_of(c),
            })
    elif category == "decks":
        for key, entry in loc["Back"].items():
            c = center("Back", key)
            rows.append({
                "name": entry.get("name") or key,
                "desc": _desc("Back", key, back_vars(key, get_config(c))),
                "price": "—",
                "rarity": "挑战" if key == "b_challenge" else "—",
                "_o": _order_of(c),
            })
    elif category == "enhancements":
        for key, entry in loc["Enhanced"].items():
            c = center("Enhanced", key)
            cfg = get_config(c)
            desc = describe("Enhanced", key, enhanced_vars(key, cfg))
            if key == "m_bonus" and not desc:
                desc = render_text(loc["Other"]["card_chips"]["text"], [cfg.get("bonus")])
            rows.append({"name": entry.get("name") or key, "desc": desc or "—", "price": "—", "rarity": "—", "_o": _order_of(c)})
    elif category == "seals":
        for i, key in enumerate(("gold_seal", "red_seal", "blue_seal", "purple_seal")):
            entry = loc["Other"].get(key) or {}
            rows.append({"name": entry.get("name") or key, "desc": _desc("Other", key, []), "price": "—", "rarity": "—", "_o": i})
    elif category == "editions":
        for key, entry in loc["Edition"].items():
            c = center("Edition", key)
            extra = get_config(c).get("extra", 1 if key == "e_negative_consumable" else None)
            rows.append({
                "name": entry.get("name") or key,
                "desc": _desc("Edition", key, [extra]),
                "price": "—",
                "rarity": "—",
                "_o": _order_of(c),
            })
    elif category == "boosters":
        for key, c in (defs.get("Booster") or {}).items():
            cfg = get_config(c)
            name = (loc.get("Booster", {}).get(key) or {}).get("name") or c.get("name") or key
            rows.append({
                "name": name,
                "desc": f"每包 {cfg.get('extra')} 张，可选 {cfg.get('choose')} 张",
                "price": str(c.get("cost") or "—"),
                "rarity": c.get("kind") or "—",
                "_o": _order_of(c),
            })
    elif category == "tags":
        for key, entry in loc["Tag"].items():
            c = center("Tag", key)
            rows.append({
                "name": entry.get("name") or key,
                "desc": _desc("Tag", key, tag_vars(key, get_config(c))),
                "price": "—",
                "rarity": "—",
                "_o": _order_of(c),
            })
    elif category == "blinds":
        for key, entry in loc["Blind"].items():
            c = center("Blind", key)
            rows.append({
                "name": entry.get("name") or key,
                "desc": _desc("Blind", key, blind_vars(c)),
                "price": "—",
                "rarity": "Boss" if isinstance(c.get("boss"), dict) else "—",
                "_o": _order_of(c),
            })
    elif category == "stake":
        for key, entry in loc["Stake"].items():
            c = center("Stake", key)
            rows.append({
                "name": entry.get("name") or key,
                "desc": _desc("Stake", key, blind_vars(c)),
                "price": "—",
                "rarity": "Boss" if isinstance(c.get("boss"), dict) else "—",
                "_o": _order_of(c),
            })
    else:
        raise KeyError(f"未知分类: {category}")
    # 与游戏收藏池一致:按 order 升序(稳定排序,无 order 的留在末尾)
    rows.sort(key=lambda r: r["_o"])
    for r in rows:
        r.pop("_o")
    return rows
