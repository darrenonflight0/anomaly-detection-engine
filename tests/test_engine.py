"""Integration tests for the detection engine and the in-memory bus."""

import pytest

from app.config import get_settings
from app.detection.engine import AnomalyDetectionEngine
from app.detection.models import MetricEvent
from app.streaming.bus import InMemoryBus
from app.streaming.producer import MetricProducer


def _warm(engine: AnomalyDetectionEngine, producer: MetricProducer, n: int) -> None:
    for _ in range(n):
        engine.process(producer.next_event())


def test_steady_state_is_quiet():
    # A clean (anomaly-free) but realistic stream should rarely false-positive.
    engine = AnomalyDetectionEngine(get_settings())
    producer = MetricProducer(anomaly_probability=0.0, seed=3)
    flagged = 0
    total = 600
    for _ in range(total):
        flagged += int(engine.process(producer.next_event()).is_anomaly)
    assert flagged / total < 0.05, f"false-positive rate too high: {flagged}/{total}"


def test_latency_spike_is_flagged():
    engine = AnomalyDetectionEngine(get_settings())
    producer = MetricProducer(anomaly_probability=0.0, seed=4)
    _warm(engine, producer, 300)
    spike = producer.next_event().model_copy(update={"latency_ms": 950.0})
    res = engine.process(spike)
    assert res.is_anomaly
    assert any(a.metric == "latency_ms" for a in res.anomalies)


def test_error_rate_threshold_breach():
    engine = AnomalyDetectionEngine(get_settings())
    producer = MetricProducer(anomaly_probability=0.0, seed=5)
    _warm(engine, producer, 150)
    bad = producer.next_event().model_copy(update={"error_rate": 0.6, "status_code": 500})
    res = engine.process(bad)
    assert any(a.metric == "error_rate" for a in res.anomalies)


def test_engine_processes_producer_stream():
    engine = AnomalyDetectionEngine(get_settings())
    producer = MetricProducer(anomaly_probability=0.2, seed=1)
    flagged = 0
    for _ in range(800):
        res = engine.process(producer.next_event())
        flagged += int(res.is_anomaly)
    # With a high injection rate the engine must catch a meaningful share.
    assert flagged > 0
    assert engine.events_processed == 800


@pytest.mark.asyncio
async def test_inmemory_bus_roundtrip():
    bus = InMemoryBus()
    await bus.start()
    received = []

    async def consume():
        async for msg in bus.subscribe():
            received.append(msg)
            if len(received) >= 3:
                break

    import asyncio
    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0.05)  # let the subscriber attach
    for i in range(3):
        await bus.publish({"n": i})
    await asyncio.wait_for(consumer, timeout=2.0)
    assert received == [{"n": 0}, {"n": 1}, {"n": 2}]
    await bus.stop()
