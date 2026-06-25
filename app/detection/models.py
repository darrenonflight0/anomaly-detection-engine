"""Pydantic models for events flowing through the engine and out to clients."""

from __future__ import annotations

import time
from typing import Dict, List

from pydantic import BaseModel, Field


class MetricEvent(BaseModel):
    """A single telemetry sample emitted by a monitored service."""

    timestamp: float = Field(default_factory=time.time)
    latency_ms: float
    error_rate: float
    traffic_rps: float
    endpoint: str
    status_code: int
    user_id: str
    region: str


class MetricStat(BaseModel):
    """Per-metric statistical snapshot for the current sample."""

    name: str
    value: float
    ema: float
    std: float
    zscore: float
    p50: float
    p95: float
    p99: float


class Anomaly(BaseModel):
    """A single detected anomaly with provenance."""

    metric: str
    value: float
    score: float
    method: str  # zscore | isolation_forest | threshold | cardinality | heavy_hitter
    severity: str  # low | medium | high | critical
    message: str
    timestamp: float = Field(default_factory=time.time)


class TopKey(BaseModel):
    key: str
    count: int
    fraction: float


class AnalysisResult(BaseModel):
    """Everything the engine concludes about one sample — the WS/REST payload."""

    timestamp: float
    event: MetricEvent
    stats: List[MetricStat]
    anomalies: List[Anomaly]
    cardinality: Dict[str, float]
    top_endpoints: List[TopKey]
    isolation_score: float  # joint multivariate outlier score across all metrics
    is_anomaly: bool
    severity: str
    events_processed: int
    anomalies_total: int
