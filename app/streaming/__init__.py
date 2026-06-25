"""Streaming transport: a pluggable bus (Kafka or in-memory) and a producer."""

from app.streaming.bus import InMemoryBus, KafkaBus, MessageBus, create_bus
from app.streaming.producer import MetricProducer

__all__ = ["MessageBus", "InMemoryBus", "KafkaBus", "create_bus", "MetricProducer"]
