"""Exponential Moving Average with online variance, for trend & spike detection.

A plain moving average needs a window buffer; an EMA needs a single number and
weights recent points more heavily, making it ideal for streaming trend
tracking.  Each update applies:

    ema  <- ema + alpha * (x - ema)

We also maintain an exponentially-weighted *variance* (West's incremental
formula) so the detector adapts its sensitivity to how noisy the stream is:

    diff <- x - ema_prev
    ema  <- ema_prev + alpha * diff
    emv  <- (1 - alpha) * (emv + alpha * diff * diff)

From the EMA and its standard deviation we derive a robust z-score; a value many
standard deviations away from the local mean is flagged as a point anomaly.  The
short-vs-long EMA gap doubles as a trend signal.

``alpha`` may be given directly, or via ``span`` (alpha = 2 / (span + 1)), the
same convention used by pandas' ewm.

Complexity: O(1) time and memory per update.
"""

from __future__ import annotations

import math
from typing import Optional


class EMA:
    def __init__(self, alpha: Optional[float] = None, span: Optional[float] = None) -> None:
        if alpha is None and span is None:
            span = 20.0
        if span is not None:
            if span < 1:
                raise ValueError("span must be >= 1")
            alpha = 2.0 / (span + 1.0)
        if not 0.0 < alpha <= 1.0:
            raise ValueError("alpha must be in (0, 1]")
        self.alpha = float(alpha)
        self.mean: Optional[float] = None
        self._var = 0.0
        self.n = 0

    def update(self, x: float) -> float:
        x = float(x)
        self.n += 1
        if self.mean is None:
            self.mean = x
            self._var = 0.0
            return self.mean
        diff = x - self.mean
        incr = self.alpha * diff
        self.mean += incr
        # Exponentially weighted variance (West, 1979).
        self._var = (1.0 - self.alpha) * (self._var + diff * incr)
        return self.mean

    @property
    def value(self) -> Optional[float]:
        return self.mean

    @property
    def variance(self) -> float:
        return self._var

    @property
    def std(self) -> float:
        return math.sqrt(self._var)

    # A deviation from a zero-variance history is maximally surprising; we report
    # a large but bounded z (rather than +inf) so messages stay readable.
    _DEGENERATE_Z = 12.0

    def zscore(self, x: float) -> float:
        """Standard deviations between ``x`` and the current local mean.

        Returns 0.0 until enough data has accumulated to form a stable estimate.
        """
        if self.mean is None or self.n < 2:
            return 0.0
        diff = float(x) - self.mean
        s = self.std
        if s < 1e-9:
            # Degenerate: the stream has been perfectly flat. Any non-trivial
            # deviation (relative to the level) is a strong anomaly; trivial
            # numerical wobble is not.
            rel = abs(diff) / (abs(self.mean) + 1.0)
            if rel < 1e-3:
                return 0.0
            return math.copysign(self._DEGENERATE_Z, diff)
        return diff / s

    def is_anomaly(self, x: float, threshold: float = 3.0) -> bool:
        return abs(self.zscore(x)) >= threshold
