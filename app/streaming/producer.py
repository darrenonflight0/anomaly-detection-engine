"""Synthetic telemetry producer.

Generates a realistic stream of service metrics (latency, error rate, traffic)
with a gentle diurnal wobble and random noise, and periodically injects one of
five anomaly types so the detection engine has something to catch:

    latency      — a latency spike (slow dependency / GC pause)
    error        — an error-rate surge (bad deploy / failing downstream)
    traffic      — a request-rate surge (flash crowd / retries storm)
    cardinality  — an explosion of distinct users (scraping / botnet)
    heavy_hitter — one endpoint hammered (hot key / abusive client)

The same producer is used both embedded in the API process and as a standalone
Kafka producer (see ``scripts/run_producer.py``).
"""

from __future__ import annotations

import math
import random
import time
from typing import Optional

from app.detection.models import MetricEvent

ENDPOINTS = [
    "/api/login", "/api/search", "/api/checkout", "/api/feed",
    "/api/profile", "/api/upload", "/api/messages", "/health",
]
ENDPOINT_WEIGHTS = [10, 22, 8, 25, 14, 6, 12, 3]
REGIONS = ["us-east", "us-west", "eu-west", "ap-south"]
ANOMALY_TYPES = ["latency", "error", "traffic", "cardinality", "heavy_hitter"]


class MetricProducer:
    def __init__(self, anomaly_probability: float = 0.015, seed: Optional[int] = None) -> None:
        self.rng = random.Random(seed)
        self.anomaly_probability = anomaly_probability
        self.tick = 0
        self.base_latency = 85.0
        self.base_error = 0.012
        self.base_traffic = 520.0
        self._anomaly: Optional[dict] = None
        self._bot_counter = 0

    def _maybe_start_anomaly(self) -> None:
        if self._anomaly is None and self.rng.random() < self.anomaly_probability:
            self._anomaly = {
                "type": self.rng.choice(ANOMALY_TYPES),
                "ttl": self.rng.randint(18, 45),
            }

    def next_event(self) -> MetricEvent:
        self.tick += 1
        self._maybe_start_anomaly()

        # Baselines with a slow sinusoidal drift + gaussian noise.
        latency = self.rng.gauss(self.base_latency, 7) + 18 * math.sin(self.tick / 60)
        error = max(0.0, self.rng.gauss(self.base_error, 0.004))
        traffic = max(0.0, self.rng.gauss(self.base_traffic, 35)
                      + 90 * math.sin(self.tick / 80))
        endpoint = self.rng.choices(ENDPOINTS, weights=ENDPOINT_WEIGHTS, k=1)[0]
        user_id = f"u{self.rng.randint(1, 6000)}"
        region = self.rng.choice(REGIONS)
        status = 200

        if self._anomaly is not None:
            kind = self._anomaly["type"]
            if kind == "latency":
                latency *= self.rng.uniform(4.0, 8.0)
            elif kind == "error":
                error = min(1.0, error + self.rng.uniform(0.25, 0.6))
                status = self.rng.choice([500, 502, 503])
            elif kind == "traffic":
                traffic *= self.rng.uniform(3.0, 6.0)
            elif kind == "cardinality":
                user_id = f"bot-{self._bot_counter}"  # every request a new identity
                self._bot_counter += 1
            elif kind == "heavy_hitter":
                endpoint = "/api/checkout"  # a single endpoint dominates
            self._anomaly["ttl"] -= 1
            if self._anomaly["ttl"] <= 0:
                self._anomaly = None

        if error > 0.5 and status == 200:
            status = 500

        return MetricEvent(
            timestamp=time.time(),
            latency_ms=round(latency, 2),
            error_rate=round(error, 4),
            traffic_rps=round(traffic, 1),
            endpoint=endpoint,
            status_code=status,
            user_id=user_id,
            region=region,
        )
