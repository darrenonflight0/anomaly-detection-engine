"""Count-Min Sketch: streaming frequency estimation in sub-linear memory.

A Count-Min Sketch estimates how many times each key has been seen without
storing the keys themselves.  It is a ``depth x width`` table of counters; each
key is hashed by ``depth`` independent hash functions and increments one counter
per row.  The estimate for a key is the *minimum* of its counters, since
collisions can only ever inflate a counter, never deflate it.

Error guarantee: with width = ceil(e/epsilon) and depth = ceil(ln(1/delta)), the
estimate overshoots the true count by at most ``epsilon * N`` (N = total events)
with probability at least ``1 - delta``.  Estimates are therefore one-sided:
``estimate(key) >= true_count(key)`` always holds.

Used here to track per-dimension event frequencies (endpoints, status codes,
tenants) and surface *heavy hitters* and frequency anomalies without keeping an
unbounded dictionary.

The ``depth`` hashes are generated cheaply with the Kirsch-Mitzenmacher trick:
``h_i(x) = (h1(x) + i * h2(x)) mod width`` behaves like independent hashing.

Complexity:
    add()       O(depth)
    estimate()  O(depth)
    memory      O(depth * width)
"""

from __future__ import annotations

import hashlib
import math
from typing import List, Tuple


class CountMinSketch:
    def __init__(self, width: int = 2048, depth: int = 5) -> None:
        if width <= 0 or depth <= 0:
            raise ValueError("width and depth must be positive")
        self.width = width
        self.depth = depth
        self.table: List[List[int]] = [[0] * width for _ in range(depth)]
        self.total = 0

    @classmethod
    def from_error(cls, epsilon: float = 0.001, delta: float = 0.01) -> "CountMinSketch":
        """Size the sketch from an error target.

        ``epsilon`` is the additive error as a fraction of total count; ``delta``
        is the probability of exceeding it.
        """
        width = math.ceil(math.e / epsilon)
        depth = math.ceil(math.log(1.0 / delta))
        return cls(width=width, depth=depth)

    def _indices(self, value) -> List[int]:
        digest = hashlib.sha256(str(value).encode("utf-8")).digest()
        h1 = int.from_bytes(digest[:8], "big")
        h2 = int.from_bytes(digest[8:16], "big") | 1  # force odd -> better spread
        return [(h1 + i * h2) % self.width for i in range(self.depth)]

    def add(self, value, count: int = 1) -> None:
        if count <= 0:
            raise ValueError("count must be positive")
        for row, idx in enumerate(self._indices(value)):
            self.table[row][idx] += count
        self.total += count

    def estimate(self, value) -> int:
        return min(self.table[row][idx] for row, idx in enumerate(self._indices(value)))

    def heavy_hitters(self, candidates, threshold: float) -> List[Tuple[object, int]]:
        """Return candidates whose estimated frequency fraction exceeds ``threshold``.

        Count-Min cannot enumerate keys on its own, so the caller supplies the
        set of keys to test (typically the distinct keys seen recently).
        """
        if self.total == 0:
            return []
        cut = threshold * self.total
        hits = [(c, self.estimate(c)) for c in candidates]
        hits = [(c, n) for c, n in hits if n >= cut]
        hits.sort(key=lambda kv: kv[1], reverse=True)
        return hits
