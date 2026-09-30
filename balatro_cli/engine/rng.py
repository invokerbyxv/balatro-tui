"""Deterministic, string-keyed PRNG.

Balatro's RNG (`pseudoseed`/`pseudorandom` in misc_functions.lua) advances a
per-string-key deterministic stream stored in G.GAME.pseudorandom.  We don't need
bit-for-bit Lua parity for the CLI - we need the *same guarantees*: reproducible
from a seed string, with separate key streams so different events don't interfere
(and an identical seed always reproduces an identical run/golden transcript).

Design: a master seed string gives each key its own `random.Random` instance,
seeded by a stable hash of (run_seed, key).

Probability model
-----------------
Card/joker luck rolls in the source read
``pseudorandom(key) < G.GAME.probabilities.normal / denom``.  ``normal`` starts at
1 and Oops! All 6s doubles it (card.lua:608), so we expose it as
:attr:`RNG.probabilities_normal` and route every roll through :meth:`RNG.chance`.
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
        # G.GAME.probabilities.normal
        self.probabilities_normal = 1

    def copy(self) -> "RNG":
        other = RNG(self.seed)
        other.probabilities_normal = self.probabilities_normal
        for k, stream in self._streams.items():
            clone = random.Random()
            clone.setstate(stream.getstate())
            other._streams[k] = clone
        return other

    def _stream(self, key: str) -> "random.Random":
        r = self._streams.get(key)
        if r is None:
            r = random.Random(_hash_to_int(f"{self.seed}:{key}"))
            self._streams[key] = r
        return r

    # -- raw streams ---------------------------------------------------------
    def rand(self, key: str) -> float:
        """Float in [0, 1) - mirrors pseudorandom(key) (advances the stream)."""
        return self._stream(key).random()

    def num(self, key: str, min_n: int, max_n: int) -> int:
        return self._stream(key).randint(min_n, max_n)

    def pick(self, key: str, items: list[T]) -> T:
        return self._stream(key).choice(list(items))

    def pick_index(self, key: str, items: list[T]) -> int:
        """Like pick() but returns the index (Lua's pseudorandom_element key)."""
        if not items:
            raise ValueError("pick_index from empty sequence")
        return self._stream(key).randrange(len(items))

    def shuffle(self, key: str, items: list[T]) -> list[T]:
        out = list(items)
        self._stream(key).shuffle(out)
        return out

    def weighted_pick(self, key: str, items: list[T], weights: list[float]) -> T:
        return self.weighted_pick_index(key, items, weights)[0]

    def weighted_pick_index(self, key: str, items: list[T],
                            weights: list[float]) -> tuple[T, int]:
        r = self._stream(key)
        total = sum(weights)
        x = r.random() * total
        for i, (item, w) in enumerate(zip(items, weights)):
            x -= w
            if x < 0:
                return item, i
        return items[-1], len(items) - 1

    # -- probability rolls ---------------------------------------------------
    def roll(self, key: str) -> float:
        """Raw roll in [0, 1); `pseudorandom(key)`."""
        return self._stream(key).random()

    def chance(self, key: str, denominator: float, numerator: float = 1.0) -> bool:
        """``pseudorandom(key) < normal * numerator / denominator``."""
        if denominator <= 0:
            return False
        return self.roll(key) < (self.probabilities_normal * numerator) / denominator

    def one_in(self, key: str, denominator: float) -> bool:
        return self.chance(key, denominator)
