"""Runtime configuration, sourced from environment variables / .env.

All settings are prefixed with ``SENTINEL_`` (e.g. ``SENTINEL_BUS=kafka``).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SENTINEL_", env_file=".env", extra="ignore"
    )

    # -- message bus ------------------------------------------------------
    bus: str = "memory"  # "memory" | "kafka"
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_topic: str = "metrics"
    kafka_group_id: str = "sentinel-detector"

    # -- embedded synthetic producer -------------------------------------
    embedded_producer: bool = True
    producer_rate_hz: float = 12.0
    anomaly_probability: float = 0.015  # chance per tick of starting an anomaly

    # -- warmup: suppress verdicts until the models have stabilised -------
    warmup_samples: int = 50

    # -- EMA trend / spike detection -------------------------------------
    ema_span: float = 30.0
    zscore_threshold: float = 3.5

    # -- T-Digest percentiles --------------------------------------------
    tdigest_compression: float = 200.0

    # -- Isolation Forest (multivariate, over standardised metric deviations)
    iforest_trees: int = 100
    iforest_sample_size: int = 256
    iforest_threshold: float = 0.68
    iforest_window: int = 500
    iforest_refit_interval: int = 100

    # -- HyperLogLog cardinality -----------------------------------------
    hll_precision: int = 14
    cardinality_window: int = 150
    cardinality_zthreshold: float = 3.0

    # -- Count-Min Sketch frequency --------------------------------------
    cms_width: int = 2048
    cms_depth: int = 5
    cms_window: int = 300
    heavy_hitter_threshold: float = 0.45

    # -- history / retention ---------------------------------------------
    history_size: int = 600
    alert_history_size: int = 200


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
