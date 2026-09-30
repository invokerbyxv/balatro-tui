"""Cached readers for the extracted assets/*.json (see data/extractor.py)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .pools import build_pools

ASSET_DIR = Path(__file__).resolve().parent.parent / "assets"


def _load(name: str) -> dict:
    return json.loads((ASSET_DIR / name).read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def centers() -> dict:
    return _load("centers.json")


@lru_cache(maxsize=None)
def blinds() -> dict:
    return _load("blinds.json")


@lru_cache(maxsize=None)
def cards() -> dict:
    return _load("cards.json")


@lru_cache(maxsize=None)
def tags() -> dict:
    """`self.P_TAGS` (game.lua:224) - the tag prototypes, keyed by tag key."""
    return _load("tags.json")


@lru_cache(maxsize=None)
def pools() -> dict:
    return build_pools(centers(), tags())


@lru_cache(maxsize=None)
def localization(locale: str = "en-us") -> dict:
    name = "loc_zh.json" if locale in ("zh", "zh_CN", "zh-cn") else "loc_en.json"
    return _load(name)


def backs_by_key() -> dict:
    """Name/resolve of all deck backs (set="Back")."""
    return {c["key"]: c for c in pools()["Back"]}