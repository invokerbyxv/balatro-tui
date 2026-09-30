"""Extract Balatro data tables from the Lua source into assets/*.json.

Source of truth: `balatro_source_code/` (version pinned by assets commit).

Extraction targets (all pure data literals):
- game.lua:  `self.P_CENTERS`  -> assets/centers.json   (jokers, tarots, planets,
             spectral, vouchers, enhanced, editions, seals, booster packs, backs)
- game.lua:  `self.P_BLINDS`   -> assets/blinds.json   (small/big/boss blinds)
- localization/{en-us,zh_CN}.lua -> assets/loc_en.json, assets/loc_zh.json
- game.lua:  `self.P_CARDS`    -> assets/cards.json    (the 52 base playing cards)

Poker-hand base levels are tiny + stable and live directly in config.HAND_LEVELS
rather than being parsed.
"""

from __future__ import annotations

import json
from pathlib import Path

from .luaparser import parse_assignment_table

_ROOT = Path(__file__).resolve().parents[2]          # repo root
SOURCE_DIR = _ROOT / "balatro_source_code"
ASSET_DIR = _ROOT / "balatro_cli" / "assets"

def default_source_dir() -> Path:
    return SOURCE_DIR


def _require_source() -> Path:
    d = default_source_dir()
    if not (d / "game.lua").exists():
        raise FileNotFoundError(f"Balatro source not found at {d}. Expected game.lua.")
    return d


def extract_centers(src: Path) -> dict:
    return parse_assignment_table((src / "game.lua").read_text(encoding="utf-8"), "self.P_CENTERS")


def extract_blinds(src: Path) -> dict:
    return parse_assignment_table((src / "game.lua").read_text(encoding="utf-8"), "self.P_BLINDS")


def extract_cards(src: Path) -> dict:
    return parse_assignment_table((src / "game.lua").read_text(encoding="utf-8"), "self.P_CARDS")


def extract_localization(src: Path, locale: str) -> dict:
    path = src / "localization" / f"{locale}.lua"
    if not path.exists():
        raise FileNotFoundError(f"locale {locale!r} not found: {path}")
    value = parse_assignment_table(path.read_text(encoding="utf-8"), "return")
    if not isinstance(value, dict):
        raise TypeError(f"localization {locale} did not parse to a table")
    return value


def write_json(asset_dir: Path, name: str, data) -> None:
    asset_dir.mkdir(parents=True, exist_ok=True)
    (asset_dir / name).write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    print(f"wrote {name}")


def extract_all(asset_dir: Path | None = None, src: Path | None = None) -> dict[str, int]:
    asset_dir = asset_dir or ASSET_DIR
    src = src or _require_source()

    centers = extract_centers(src)
    blinds = extract_blinds(src)
    cards = extract_cards(src)
    loc_en = extract_localization(src, "en-us")
    loc_zh = extract_localization(src, "zh_CN")

    write_json(asset_dir, "centers.json", centers)
    write_json(asset_dir, "blinds.json", blinds)
    write_json(asset_dir, "cards.json", cards)
    write_json(asset_dir, "loc_en.json", loc_en)
    write_json(asset_dir, "loc_zh.json", loc_zh)

    counts = {
        "centers": len(centers),
        "blinds": len(blinds),
        "cards": len(cards),
        "sets": sorted({c["set"] for c in centers.values() if isinstance(c, dict) and c.get("set")}),
    }
    print("counts:", counts)
    return counts


if __name__ == "__main__":
    extract_all()