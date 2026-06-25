"""The anomaly detection engine.

Each incoming :class:`MetricEvent` is pushed through a battery of streaming
structures, each owning one concern:

    * EMA              -> per-metric local trend + robust z-score (spike anomalies)
    * T-Digest         -> per-metric live p50/p95/p99 (percentile context)
    * Isolation Forest -> ONE multivariate outlier score over the standardised
                          (z-scored) deviations of all metrics jointly — catches
                          anomalous *combinations* a single metric can't reveal
    * HyperLogLog      -> unique-entity cardinality (detect diversity explosions)
    * Count-Min Sketch -> per-endpoint frequency (detect heavy hitters)

Division of labour: the EMA z-score is the sharp instrument for univariate
spikes; the Isolation Forest adds the orthogonal ability to flag joint outliers
(e.g. traffic and latency that are each individually plausible but never co-occur
in normal operation).

The engine is framework-agnostic: it takes events and returns
:class:`AnalysisResult` objects. The FastAPI layer handles transport.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

from app.algorithms import EMA, CountMinSketch, HyperLogLog, IsolationForest, TDigest
from app.config import Settings
from app.detection.models import (
    AnalysisResult,
    Anomaly,
    MetricEvent,
    MetricStat,
    TopKey,
)

SEVERITY_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
_FEATURE_CLIP = 8.0  # bound standardised features so warmup noise can't distort the forest


def _zscore_severity(z: float, base: float) -> str:
    a = abs(z)
    if a >= base + 4:
        return "critical"
    if a >= base + 2:
        return "high"
    if a >= base + 0.8:
        return "medium"
    return "low"


def _iforest_severity(score: float, base: float) -> str:
    if score >= base + 0.15:
        return "critical"
    if score >= base + 0.07:
        return "high"
    return "medium"


def _clip(x: float, lo: float = -_FEATURE_CLIP, hi: float = _FEATURE_CLIP) -> float:
    return max(lo, min(hi, x))


class MetricTracker:
    """EMA (trend/z-score) + T-Digest (percentiles) for one scalar metric."""

    def __init__(self, name: str, settings: Settings, direction: str = "both",
                 hard_threshold: Optional[float] = None, unit: str = "") -> None:
        self.name = name
        self.settings = settings
        self.direction = direction  # "high" | "both"
        self.hard_threshold = hard_threshold
        self.unit = unit
        self.ema = EMA(span=settings.ema_span)
        self.digest = TDigest(compression=settings.tdigest_compression)

    def update(self, value: float) -> float:
        """Ingest ``value``; return its z-score against the pre-update model."""
        value = float(value)
        z = self.ema.zscore(value)
        self.ema.update(value)
        self.digest.add(value)
        return z

    def evaluate(self, value: float, z: float, warm: bool) -> List[Anomaly]:
        if not warm:
            return []
        anomalies: List[Anomaly] = []
        directional = z if self.direction == "high" else abs(z)
        if directional >= self.settings.zscore_threshold:
            anomalies.append(Anomaly(
                metric=self.name, value=round(value, 3), score=round(z, 2),
                method="zscore", severity=_zscore_severity(z, self.settings.zscore_threshold),
                message=(f"{self.name} {value:g}{self.unit} is {z:+.1f}σ from its "
                         f"trend ({self.ema.value:.1f}{self.unit})"),
            ))
        if self.hard_threshold is not None and value >= self.hard_threshold:
            anomalies.append(Anomaly(
                metric=self.name, value=round(value, 3), score=round(value, 2),
                method="threshold", severity="high",
                message=(f"{self.name} {value:g}{self.unit} breached hard limit "
                         f"{self.hard_threshold:g}{self.unit}"),
            ))
        return anomalies

    def stat(self, value: float, z: float) -> MetricStat:
        return MetricStat(
            name=self.name,
            value=round(value, 3),
            ema=round(self.ema.value if self.ema.value is not None else value, 3),
            std=round(self.ema.std, 3),
            zscore=round(z, 2),
            p50=round(self.digest.percentile(50), 2),
            p95=round(self.digest.percentile(95), 2),
            p99=round(self.digest.percentile(99), 2),
        )


class MultivariateDetector:
    """A single Isolation Forest over the standardised deviation vector.

    Features are the per-metric z-scores (clipped), so the forest sees a roughly
    standard-normal cloud in normal operation and isolates joint outliers.
    """

    def __init__(self, settings: Settings, n_features: int) -> None:
        self.settings = settings
        self.window: Deque[List[float]] = deque(maxlen=settings.iforest_window)
        self.forest: Optional[IsolationForest] = None
        self._since_refit = 0

    def update(self, features: List[float]) -> float:
        features = [_clip(f) for f in features]
        score = self.forest.anomaly_score(features) if self.forest else 0.0
        self.window.append(features)
        self._since_refit += 1
        ready = len(self.window) >= max(50, self.settings.iforest_refit_interval)
        due = self._since_refit >= self.settings.iforest_refit_interval
        if ready and (self.forest is None or due):
            try:
                self.forest = IsolationForest(
                    n_trees=self.settings.iforest_trees,
                    sample_size=self.settings.iforest_sample_size,
                ).fit(list(self.window))
            except ValueError:
                self.forest = None
            self._since_refit = 0
        return score


class AnomalyDetectionEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.started_at = time.time()
        self.events_processed = 0
        self.anomalies_total = 0

        self.trackers: Dict[str, MetricTracker] = {
            "latency_ms": MetricTracker("latency_ms", settings, direction="high",
                                        hard_threshold=1000.0, unit="ms"),
            "error_rate": MetricTracker("error_rate", settings, direction="high",
                                        hard_threshold=0.25),
            "traffic_rps": MetricTracker("traffic_rps", settings, direction="both"),
        }
        self.multivariate = MultivariateDetector(settings, n_features=len(self.trackers))

        # Cardinality: a global sketch (total uniques) plus a windowed sketch
        # whose per-window counts feed an EMA so we can flag diversity spikes.
        self.hll_global = HyperLogLog(settings.hll_precision)
        self.hll_window = HyperLogLog(settings.hll_precision)
        self.card_ema = EMA(span=20)
        self._card_window_count = 0
        self.last_window_cardinality = 0.0

        # Frequency: a windowed Count-Min Sketch + the set of endpoints seen in
        # the window (the candidate keys for heavy-hitter queries).
        self.cms = CountMinSketch(settings.cms_width, settings.cms_depth)
        self._endpoints_seen: set[str] = set()
        self._cms_window_count = 0

    # -- cardinality ------------------------------------------------------
    def _update_cardinality(self, user_id: str, warm: bool) -> Optional[Anomaly]:
        self.hll_global.add(user_id)
        self.hll_window.add(user_id)
        self._card_window_count += 1
        if self._card_window_count < self.settings.cardinality_window:
            return None

        snapshot = self.hll_window.count()
        z = self.card_ema.zscore(snapshot)
        self.card_ema.update(snapshot)
        self.last_window_cardinality = snapshot
        self._card_window_count = 0
        self.hll_window = HyperLogLog(self.settings.hll_precision)

        if warm and z >= self.settings.cardinality_zthreshold:
            return Anomaly(
                metric="cardinality", value=round(snapshot, 1), score=round(z, 2),
                method="cardinality",
                severity=_zscore_severity(z, self.settings.cardinality_zthreshold),
                message=(f"Unique-entity count spiked to {snapshot:.0f}/window "
                         f"({z:+.1f}σ) — possible scraping or botnet"),
            )
        return None

    # -- frequency / heavy hitters ---------------------------------------
    def _update_frequency(self, endpoint: str, warm: bool) -> Tuple[List[TopKey], Optional[Anomaly]]:
        self.cms.add(endpoint)
        self._endpoints_seen.add(endpoint)
        self._cms_window_count += 1

        top = self._top_endpoints()
        anomaly: Optional[Anomaly] = None
        if warm and self.cms.total >= 30 and top:
            leader = top[0]
            if leader.fraction >= self.settings.heavy_hitter_threshold:
                anomaly = Anomaly(
                    metric="heavy_hitter", value=leader.count,
                    score=round(leader.fraction, 3), method="heavy_hitter",
                    severity="high" if leader.fraction >= 0.7 else "medium",
                    message=(f"Endpoint {leader.key} absorbed {leader.fraction:.0%} "
                             f"of traffic — heavy hitter / hot key"),
                )

        if self._cms_window_count >= self.settings.cms_window:
            self.cms = CountMinSketch(self.settings.cms_width, self.settings.cms_depth)
            self._endpoints_seen.clear()
            self._cms_window_count = 0
        return top, anomaly

    def _top_endpoints(self, k: int = 6) -> List[TopKey]:
        total = self.cms.total or 1
        scored = [(ep, self.cms.estimate(ep)) for ep in self._endpoints_seen]
        scored.sort(key=lambda kv: kv[1], reverse=True)
        return [
            TopKey(key=ep, count=c, fraction=round(c / total, 4))
            for ep, c in scored[:k]
        ]

    # -- main entry -------------------------------------------------------
    def process(self, event: MetricEvent) -> AnalysisResult:
        self.events_processed += 1
        warm = self.events_processed > self.settings.warmup_samples
        stats: List[MetricStat] = []
        anomalies: List[Anomaly] = []
        feature_vector: List[float] = []

        for name, tracker in self.trackers.items():
            value = getattr(event, name)
            z = tracker.update(value)
            stats.append(tracker.stat(value, z))
            anomalies.extend(tracker.evaluate(value, z, warm))
            feature_vector.append(z)

        iso = self.multivariate.update(feature_vector)
        if warm and iso >= self.settings.iforest_threshold:
            anomalies.append(Anomaly(
                metric="multivariate", value=round(iso, 3), score=round(iso, 3),
                method="isolation_forest",
                severity=_iforest_severity(iso, self.settings.iforest_threshold),
                message=(f"Joint metric state isolated with score {iso:.2f} — "
                         f"anomalous combination of latency/errors/traffic"),
            ))

        card_anomaly = self._update_cardinality(event.user_id, warm)
        if card_anomaly:
            anomalies.append(card_anomaly)

        top_endpoints, hh_anomaly = self._update_frequency(event.endpoint, warm)
        if hh_anomaly:
            anomalies.append(hh_anomaly)

        self.anomalies_total += len(anomalies)
        severity = "none"
        for a in anomalies:
            if SEVERITY_RANK[a.severity] > SEVERITY_RANK[severity]:
                severity = a.severity

        return AnalysisResult(
            timestamp=event.timestamp,
            event=event,
            stats=stats,
            anomalies=anomalies,
            cardinality={
                "unique_total": round(self.hll_global.count(), 0),
                "unique_window": round(self.hll_window.count(), 0),
                "last_window": round(self.last_window_cardinality, 0),
            },
            top_endpoints=top_endpoints,
            isolation_score=round(iso, 3),
            is_anomaly=bool(anomalies),
            severity=severity,
            events_processed=self.events_processed,
            anomalies_total=self.anomalies_total,
        )

    def snapshot(self) -> dict:
        """Lightweight status for the /api/state endpoint."""
        return {
            "uptime_seconds": round(time.time() - self.started_at, 1),
            "events_processed": self.events_processed,
            "anomalies_total": self.anomalies_total,
            "unique_users_total": round(self.hll_global.count(), 0),
            "metrics": list(self.trackers.keys()),
        }
