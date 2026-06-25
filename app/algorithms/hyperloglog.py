"""HyperLogLog: cardinality (count-distinct) estimation in tiny, fixed memory.

Counting unique items exactly costs O(n) memory.  HyperLogLog estimates the
number of distinct items using only ``m = 2**p`` small registers (one byte each
here), giving a relative error of roughly ``1.04 / sqrt(m)``.  With p=14 that is
16 KB of registers for a ~0.8% error regardless of whether you stream a thousand
or a billion items.

Intuition: hash each item to a uniform bit string.  In a stream of distinct
items, seeing a hash with ``r`` leading zeros suggests we have seen on the order
of ``2**r`` distinct items (such patterns are rare).  HLL splits the hash space
into ``m`` buckets, tracks the maximum leading-zero rank seen per bucket, and
combines them with a bias-corrected harmonic mean to tame the variance.

Used here to flag *cardinality spikes* — e.g. a sudden explosion in the number of
distinct source IPs or user-agents, a classic signature of scraping or a DDoS.

Complexity:
    add()    O(1)
    count()  O(m)
    memory   O(m) bytes
"""

from __future__ import annotations

import hashlib
import math
from typing import Iterable


class HyperLogLog:
    def __init__(self, precision: int = 14) -> None:
        if not 4 <= precision <= 18:
            raise ValueError("precision must be in [4, 18]")
        self.p = precision
        self.m = 1 << precision
        self.registers = bytearray(self.m)
        self.alpha = self._alpha(self.m)
        self._max_rank = 64 - self.p  # bits available for the leading-zero count

    @staticmethod
    def _alpha(m: int) -> float:
        if m == 16:
            return 0.673
        if m == 32:
            return 0.697
        if m == 64:
            return 0.709
        return 0.7213 / (1.0 + 1.079 / m)

    @staticmethod
    def _hash64(value) -> int:
        digest = hashlib.sha1(str(value).encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big")

    def add(self, value) -> None:
        x = self._hash64(value)
        idx = x >> (64 - self.p)                  # leading p bits select the bucket
        remaining = x & ((1 << self._max_rank) - 1)
        # rank = position of the left-most 1-bit within the remaining field, +1
        rank = self._max_rank - remaining.bit_length() + 1
        if rank > self.registers[idx]:
            self.registers[idx] = rank

    def update(self, values: Iterable) -> None:
        for v in values:
            self.add(v)

    def count(self) -> float:
        m = self.m
        harmonic = 0.0
        zeros = 0
        for r in self.registers:
            harmonic += 2.0 ** (-r)
            if r == 0:
                zeros += 1
        estimate = self.alpha * m * m / harmonic

        # Small-range correction: linear counting when many registers are empty.
        if estimate <= 2.5 * m and zeros > 0:
            estimate = m * math.log(m / zeros)
        return estimate

    def merge(self, other: "HyperLogLog") -> "HyperLogLog":
        """Union two sketches (register-wise max). Both must share precision."""
        if self.p != other.p:
            raise ValueError("cannot merge HyperLogLogs of different precision")
        out = HyperLogLog(self.p)
        for i in range(self.m):
            out.registers[i] = max(self.registers[i], other.registers[i])
        return out

    def __len__(self) -> int:
        return int(round(self.count()))
