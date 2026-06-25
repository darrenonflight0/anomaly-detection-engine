"""Standalone telemetry producer for the Kafka deployment path.

Run this when ``SENTINEL_BUS=kafka`` and you want the producer out-of-process
(e.g. multiple producers, or producing into a shared cluster):

    python -m scripts.run_producer --rate 20

The API process should be started with ``SENTINEL_EMBEDDED_PRODUCER=false`` so it
only consumes.
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from app.config import settings
from app.streaming.bus import KafkaBus
from app.streaming.producer import MetricProducer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("sentinel.producer")


async def main(rate: float, anomaly_probability: float) -> None:
    bus = KafkaBus(settings)
    await bus.start()
    producer = MetricProducer(anomaly_probability=anomaly_probability)
    interval = 1.0 / max(0.1, rate)
    logger.info("producing to topic=%s at %.1f Hz", settings.kafka_topic, rate)
    sent = 0
    try:
        while True:
            await bus.publish(producer.next_event().model_dump())
            sent += 1
            if sent % 100 == 0:
                logger.info("sent %d events", sent)
            await asyncio.sleep(interval)
    except KeyboardInterrupt:
        pass
    finally:
        await bus.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sentinel Kafka producer")
    parser.add_argument("--rate", type=float, default=settings.producer_rate_hz,
                        help="events per second")
    parser.add_argument("--anomaly-prob", type=float, default=settings.anomaly_probability,
                        help="probability per tick of starting an anomaly")
    args = parser.parse_args()
    asyncio.run(main(args.rate, args.anomaly_prob))
