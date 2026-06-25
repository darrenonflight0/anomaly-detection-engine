"""T-Digest: streaming quantile (percentile) estimation in bounded memory.

A t-digest summarises a distribution as a small set of *centroids* (a mean and a
weight).  Centroids near the tails of the distribution are kept small so that
extreme quantiles (p99, p999) stay accurate, while centroids near the median are
allowed to absorb more weight.  The size of the digest is bounded by the
``compression`` parameter, independent of how many points are streamed through
it.

This is the "merging" variant of Ted Dunning's t-digest.  The amount of weight a
centroid may hold is governed by a scale function ``k(q)``; a run of centroids
may be merged together as long as it does not span more than one unit of ``k``.

    k(q) = compression / (2*pi) * arcsin(2q - 1)

Because ``k`` is steep near q=0 and q=1, only a little weight is permitted in the
tails, which is exactly where percentile accuracy matters for anomaly detection.

Complexity:
    add()       amortised O(1)            (buffered, periodic O(m log m) merge)
    quantile()  O(m)  where m <= ~compression centroids
    memory      O(compression)
"""

from __future__ import annotations

import math
from typing import List


class TDigest:
    def __init__(self, compression: float = 100.0) -> None:
        if compression < 20:
            raise ValueError("compression should be >= 20 for useful accuracy")
        self.compression = float(compression)
        # Each centroid is a mutable [mean, weight] pair, kept sorted by mean.
        self._centroids: List[List[float]] = []
        self._buffer: List[List[float]] = []
        # Buffer unmerged points and flush in batches to amortise the merge cost.
        self._buffer_limit = max(64, int(compression) * 5)
        self.count = 0.0

    # -- ingestion --------------------------------------------------------
    def add(self, x: float, weight: float = 1.0) -> None:
        if weight <= 0:
            raise ValueError("weight must be positive")
        x = float(x)
        if math.isnan(x) or math.isinf(x):
            return
        self._buffer.append([x, float(weight)])
        self.count += weight
        if len(self._buffer) >= self._buffer_limit:
            self._flush()

    def batch_update(self, values) -> None:
        for v in values:
            self.add(v)

    # -- scale function ---------------------------------------------------
    def _k(self, q: float) -> float:
        q = min(1.0, max(0.0, q))
        return self.compression / (2.0 * math.pi) * math.asin(2.0 * q - 1.0)

    def _flush(self) -> None:
        if not self._buffer:
            return
        merged = self._centroids + self._buffer
        merged.sort(key=lambda c: c[0])
        self._buffer = []
        self._centroids = self._compress(merged)

    def _compress(self, centroids: List[List[float]]) -> List[List[float]]:
        total = sum(c[1] for c in centroids)
        if total <= 0:
            return []
        out: List[List[float]] = []
        cum = 0.0  # cumulative weight strictly below the current centroid
        cur_mean, cur_weight = centroids[0]
        for mean, weight in centroids[1:]:
            q_left = cum / total
            q_right = (cum + cur_weight + weight) / total
            # Merge while the proposed centroid spans <= one unit of k.
            if self._k(q_right) - self._k(q_left) <= 1.0:
                cur_weight += weight
                cur_mean += (mean - cur_mean) * weight / cur_weight
            else:
                out.append([cur_mean, cur_weight])
                cum += cur_weight
                cur_mean, cur_weight = mean, weight
        out.append([cur_mean, cur_weight])
        return out

    # -- queries ----------------------------------------------------------
    def quantile(self, q: float) -> float:
        """Estimate the value at quantile ``q`` in [0, 1]."""
        self._flush()
        n = len(self._centroids)
        if n == 0:
            return float("nan")
        if n == 1:
            return self._centroids[0][0]

        total = sum(c[1] for c in self._centroids)
        target = q * total

        # Cumulative weight at the *centre* of each centroid.
        centres = []
        cum = 0.0
        for mean, weight in self._centroids:
            centres.append((cum + weight / 2.0, mean))
            cum += weight

        if target <= centres[0][0]:
            return self._centroids[0][0]
        if target >= centres[-1][0]:
            return self._centroids[-1][0]

        for i in range(1, n):
            c0, m0 = centres[i - 1]
            c1, m1 = centres[i]
            if target <= c1:
                frac = (target - c0) / (c1 - c0) if c1 > c0 else 0.0
                return m0 + frac * (m1 - m0)
        return self._centroids[-1][0]

    def percentile(self, p: float) -> float:
        """Convenience wrapper: ``p`` given as 0-100."""
        return self.quantile(p / 100.0)

    def cdf(self, x: float) -> float:
        """Estimate P(X <= x), the rank of ``x`` in [0, 1]."""
        self._flush()
        if not self._centroids:
            return float("nan")
        total = sum(c[1] for c in self._centroids)
        cum = 0.0
        for mean, weight in self._centroids:
            if x < mean:
                break
            cum += weight
        return min(1.0, cum / total)

    @property
    def num_centroids(self) -> int:
        return len(self._centroids) + len(self._buffer)

    def __len__(self) -> int:
        return int(self.count)
