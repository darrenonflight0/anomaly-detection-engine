"""FastAPI application: the real-time transport around the detection engine.

Pipeline (single process):

    MetricProducer --publish--> MessageBus --subscribe--> AnomalyDetectionEngine
                                                              |
                                  history / alerts <----------+----> WebSocket fan-out

With ``SENTINEL_BUS=kafka`` the bus becomes real Kafka and the producer can also
be run out-of-process (scripts/run_producer.py).  With the default in-memory bus
everything runs here, so ``uvicorn app.main:app`` is a complete demo.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Deque, Dict, List, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.detection.engine import AnomalyDetectionEngine
from app.detection.models import MetricEvent
from app.streaming.bus import create_bus
from app.streaming.producer import MetricProducer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("sentinel")

STATIC_DIR = Path(__file__).parent / "static"


class ConnectionManager:
    """Tracks live WebSocket clients and broadcasts analysis results to them."""

    def __init__(self) -> None:
        self.active: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.active.discard(ws)

    async def broadcast(self, message: dict) -> None:
        dead: List[WebSocket] = []
        for ws in list(self.active):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


class AppState:
    def __init__(self) -> None:
        self.engine = AnomalyDetectionEngine(settings)
        self.manager = ConnectionManager()
        self.bus = create_bus(settings)
        self.history: Deque[dict] = deque(maxlen=settings.history_size)
        self.alerts: Deque[dict] = deque(maxlen=settings.alert_history_size)
        self.latest: dict | None = None
        self.tasks: List[asyncio.Task] = []


state = AppState()


async def _consume_loop() -> None:
    """Read events off the bus, run detection, persist and broadcast results."""
    async for raw in state.bus.subscribe():
        try:
            event = MetricEvent(**raw)
        except Exception:
            logger.exception("dropping malformed event")
            continue
        result = state.engine.process(event)
        payload = result.model_dump()
        state.latest = payload

        state.history.append({
            "t": result.timestamp,
            "latency_ms": event.latency_ms,
            "error_rate": event.error_rate,
            "traffic_rps": event.traffic_rps,
            "severity": result.severity,
            "is_anomaly": result.is_anomaly,
        })
        for anomaly in result.anomalies:
            state.alerts.appendleft(anomaly.model_dump())

        await state.manager.broadcast({"type": "update", "result": payload})


async def _produce_loop() -> None:
    """Embedded synthetic producer; publishes events to the bus at a fixed rate."""
    producer = MetricProducer(anomaly_probability=settings.anomaly_probability)
    interval = 1.0 / max(0.1, settings.producer_rate_hz)
    while True:
        event = producer.next_event()
        await state.bus.publish(event.model_dump())
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await state.bus.start()
    logger.info("bus=%s embedded_producer=%s rate=%.1fHz",
                settings.bus, settings.embedded_producer, settings.producer_rate_hz)
    state.tasks.append(asyncio.create_task(_consume_loop()))
    await asyncio.sleep(0.2)  # let the consumer subscribe before we publish
    if settings.embedded_producer:
        state.tasks.append(asyncio.create_task(_produce_loop()))
    try:
        yield
    finally:
        for task in state.tasks:
            task.cancel()
        await asyncio.gather(*state.tasks, return_exceptions=True)
        await state.bus.stop()


app = FastAPI(title="Sentinel — Real-Time Anomaly Detection", version="1.0.0",
              lifespan=lifespan)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "bus": getattr(state.bus, "name", settings.bus)}


@app.get("/api/state")
async def get_state() -> dict:
    return {
        "snapshot": state.engine.snapshot(),
        "latest": state.latest,
        "config": {
            "zscore_threshold": settings.zscore_threshold,
            "iforest_threshold": settings.iforest_threshold,
            "producer_rate_hz": settings.producer_rate_hz,
            "bus": settings.bus,
        },
    }


@app.get("/api/history")
async def get_history(limit: int = 300) -> JSONResponse:
    limit = max(1, min(limit, settings.history_size))
    items = list(state.history)[-limit:]
    return JSONResponse(items)


@app.get("/api/alerts")
async def get_alerts(limit: int = 50) -> JSONResponse:
    limit = max(1, min(limit, settings.alert_history_size))
    return JSONResponse(list(state.alerts)[:limit])


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await state.manager.connect(ws)
    try:
        await ws.send_json({
            "type": "snapshot",
            "snapshot": state.engine.snapshot(),
            "history": list(state.history)[-200:],
            "alerts": list(state.alerts)[:30],
            "latest": state.latest,
        })
        while True:  # keep the socket open; we only push, never expect input
            await ws.receive_text()
    except WebSocketDisconnect:
        state.manager.disconnect(ws)
    except Exception:
        state.manager.disconnect(ws)


@app.api_route("/", methods=["GET", "HEAD"])
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
