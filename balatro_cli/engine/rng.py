"""Deterministic, string-keyed PRNG.

Balatro's RNG (`pseudoseed`/`pseudorandom` in misc_functions.lua) advances a
per-string-key deterministic stream stored in G.GAME.pseudorandom. We don't need
bit-for-bit Lua parity for the CLI — we need the *same guarantees*: reproducible
from a seed string, with separate key streams so different events don't interfere
(and an identical seed always reproduces an identical run/golden transcript).

Design: a master seed string gives each key its own `random.Random` instance,
seeded by a stable hash of (run_seed, key).
"""

from __future__ import annotations

import hashlib
import random
from typing import TypeVar

T = TypeVar("T")


def _hash_to_int(seed: str) -> int:
    return int.from_bytes(hashlib.sha256(seed.encode("utf-8")).digest()[:8], "big")


class RNG:
    def __init__(self, seed: str):
        self.seed = seed
        self._streams: dict[str, "random.Random"] = {}

    def _stream(self, key: str) -> "random.Random":
        r = self._streams.get(key)
        if r is None:
            r = random.Random(_hash_to_int(f"{self.seed}:{key}"))
            self._streams[key] = r
        return r

    def rand(self, key: str) -> float:
        """Float in [0, 1)."""
        return self._stream(key).random()

    def num(self, key: str, min_n: int, max_n: int) -> int:
        return self._stream(key).randint(min_n, max_n)

    def pick(self, key: str, items: list[T]) -> T:
        return self._stream(key).choice(list(items))

    def shuffle(self, key: str, items: list[T]) -> list[T]:
        out = list(items)
        self._stream(key).shuffle(out)
        return out

    def weighted_pick(self, key: str, items: list[T], weights: list[float]) -> T:
        r = self._stream(key)
        total = sum(weights)
        x = r.random() * total
        for item, w in zip(items, weights):
            x -= w
            if x < 0:
                return item
        return items[-1]