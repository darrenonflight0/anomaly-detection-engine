"""Message bus abstraction with two interchangeable backends.

* :class:`InMemoryBus` — an asyncio fan-out queue.  Zero dependencies, lets the
  whole pipeline run in a single process with no broker (great for demos/tests).
* :class:`KafkaBus` — real Apache Kafka via aiokafka, for the "production" path.

Both expose the same tiny contract (``publish`` / ``subscribe``), so the rest of
the app is oblivious to which one is wired in.  Messages are plain dicts.
"""

from __future__ import annotations

import abc
import asyncio
import json
import logging
from typing import AsyncIterator, List

from app.config import Settings

logger = logging.getLogger("sentinel.bus")


class MessageBus(abc.ABC):
    @abc.abstractmethod
    async def start(self) -> None: ...

    @abc.abstractmethod
    async def stop(self) -> None: ...

    @abc.abstractmethod
    async def publish(self, message: dict) -> None: ...

    @abc.abstractmethod
    def subscribe(self) -> AsyncIterator[dict]: ...


class InMemoryBus(MessageBus):
    def __init__(self, maxsize: int = 2000) -> None:
        self._subscribers: List[asyncio.Queue] = []
        self._maxsize = maxsize
        self.name = "memory"

    async def start(self) -> None:
        logger.info("InMemoryBus started")

    async def stop(self) -> None:
        self._subscribers.clear()

    async def publish(self, message: dict) -> None:
        for q in list(self._subscribers):
            if q.full():
                try:  # drop the oldest message to keep the stream live
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            await q.put(message)

    async def subscribe(self) -> AsyncIterator[dict]:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._maxsize)
        self._subscribers.append(q)
        try:
            while True:
                yield await q.get()
        finally:
            if q in self._subscribers:
                self._subscribers.remove(q)


class KafkaBus(MessageBus):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.name = "kafka"
        self._producer = None

    async def start(self) -> None:
        from aiokafka import AIOKafkaProducer

        self._producer = AIOKafkaProducer(
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            linger_ms=5,
        )
        await self._producer.start()
        logger.info("KafkaBus producer connected to %s",
                    self.settings.kafka_bootstrap_servers)

    async def stop(self) -> None:
        if self._producer is not None:
            await self._producer.stop()

    async def publish(self, message: dict) -> None:
        assert self._producer is not None, "KafkaBus.start() not called"
        await self._producer.send_and_wait(self.settings.kafka_topic, message)

    async def subscribe(self) -> AsyncIterator[dict]:
        from aiokafka import AIOKafkaConsumer

        consumer = AIOKafkaConsumer(
            self.settings.kafka_topic,
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            group_id=self.settings.kafka_group_id,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            auto_offset_reset="latest",
            enable_auto_commit=True,
        )
        await consumer.start()
        logger.info("KafkaBus consumer subscribed to %s", self.settings.kafka_topic)
        try:
            async for msg in consumer:
                yield msg.value
        finally:
            await consumer.stop()


def create_bus(settings: Settings) -> MessageBus:
    if settings.bus.lower() == "kafka":
        return KafkaBus(settings)
    return InMemoryBus()
