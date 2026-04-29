"""POI Re-identification System — Application Entry Point.

Wires all layers together following Clean Architecture:
  API → Service → Domain ← Infrastructure
"""

from __future__ import annotations

import logging
import os
import signal
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.api import camera_routes, poi_routes, search_routes, thumbnail_routes
from backend.consumers.mqtt_consumer import EventConsumer
from backend.consumers.scenescape_consumer import ScenescapeRegionConsumer
from backend.core.config import get_config
from backend.factory.factories import EmbeddingModelFactory
from backend.infrastructure.faiss.repository import FAISSRepository
from backend.infrastructure.mqtt.adapter import MQTTAdapter
from backend.infrastructure.redis.repository import (
    RedisCacheRepository,
    RedisEmbeddingMappingRepository,
    RedisEventRepository,
    RedisPOIRepository,
)
from backend.infrastructure.scenescape.adapter import ScenescapeAPIAdapter
from backend.observer.events import EventBus
from backend.service.alert_service import AlertService
from backend.service.event_service import EventService
from backend.service.matching_service import MatchingService
from backend.service.poi_service import POIService
from backend.strategy.alert import LogAlertStrategy, WebSocketAlertStrategy, AlertServiceStrategy
from backend.strategy.matching import CosineSimilarityStrategy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("poi.main")

# Global references for cleanup
_mqtt_adapter = None
_ws_strategy = None


def _alert_dict_to_ws_envelope(alert: dict) -> dict:
    """Convert a Redis-stored alert dict to the WS broadcast envelope format.

    Redis format uses event_type='poi_match_alert' with nested match/poi_metadata.
    WS envelope format uses alert_type='POI_MATCH' with flat metadata — matches
    the format the UI's mapEnvelopeToAlert() expects.
    """
    match = alert.get("match", {})
    poi_meta = alert.get("poi_metadata", {})
    return {
        "alert_type": "POI_MATCH",
        "metadata": {
            "alert_id": alert.get("alert_id", ""),
            "poi_id": alert.get("poi_id", ""),
            "severity": alert.get("severity", "medium"),
            "camera_id": match.get("camera_id", ""),
            "similarity_score": match.get("similarity_score", 0.0),
            "confidence": match.get("confidence", 0.0),
            "bbox": match.get("bbox", []),
            "frame_number": match.get("frame_number", 0),
            "thumbnail_path": match.get("thumbnail_path", ""),
            "notes": poi_meta.get("notes", ""),
            "enrollment_date": poi_meta.get("enrollment_date", ""),
            "total_previous_matches": poi_meta.get("total_previous_matches", 0),
        },
        "timestamp": alert.get("timestamp", ""),
    }

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    global _mqtt_adapter, _ws_strategy
    cfg = get_config()
    log.info("=== POI Re-identification System Starting ===")

    # ── Infrastructure ──
    log.info("Initializing FAISS repository...")
    faiss_repo = FAISSRepository()

    log.info("Initializing Redis repositories...")
    poi_repo = RedisPOIRepository()
    cache_repo = RedisCacheRepository()
    event_repo = RedisEventRepository()
    mapping_repo = RedisEmbeddingMappingRepository()

    log.info("Initializing SceneScape adapter...")
    scenescape = ScenescapeAPIAdapter()

    # ── Strategy ──
    matching_strategy = CosineSimilarityStrategy(faiss_repo)
    _ws_strategy = WebSocketAlertStrategy()
    # Give the WS strategy a reference to the running event loop so it can
    # schedule async broadcasts from the MQTT thread via run_coroutine_threadsafe.
    import asyncio as _asyncio
    _ws_strategy.set_event_loop(_asyncio.get_running_loop())

    alert_strategies = [LogAlertStrategy()]
    # Always register WS strategy — handles live alerts to connected UI clients
    alert_strategies.append(_ws_strategy)
    if "alert_service" in cfg.delivery_handlers:
        alert_strategies.append(AlertServiceStrategy(cfg.alert_service_url))

    # ── Observer ──
    event_bus = EventBus()

    # ── Service ──
    poi_service = POIService(poi_repo, faiss_repo, mapping_repo)
    matching_service = MatchingService(matching_strategy, cache_repo)
    event_service = EventService(event_repo)
    alert_service = AlertService(alert_strategies, event_repo, poi_repo, event_bus)

    # ── Consumer ──
    consumer = EventConsumer(matching_service, event_service, alert_service, event_bus, event_repo=event_repo)
    region_consumer = ScenescapeRegionConsumer(event_service)

    # ── MQTT ──
    if cfg.mqtt_host:
        log.info("Starting MQTT consumer...")
        _mqtt_adapter = MQTTAdapter(on_event=consumer.handle_event, on_region_event=region_consumer.handle_event)
        try:
            _mqtt_adapter.start()
        except Exception:
            log.exception("Failed to start MQTT — running without live events")
            _mqtt_adapter = None

    # ── Inject services into API routes ──
    poi_routes.init(poi_service)
    search_routes.init(
        matching_service, event_service, EmbeddingModelFactory.create(), faiss_repo
    )
    camera_routes.init(scenescape)
    thumbnail_routes.init(event_repo)

    log.info("FAISS: %d vectors indexed", faiss_repo.total_vectors())
    log.info("=== POI System Ready on %s:%d ===", cfg.api_host, cfg.api_port)

    yield

    # ── Shutdown ──
    log.info("Shutting down...")
    if _mqtt_adapter:
        _mqtt_adapter.stop()
    faiss_repo.save_to_disk()
    log.info("Shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title="POI Re-identification System",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API routes
    app.include_router(poi_routes.router, prefix="/api/v1")
    app.include_router(search_routes.router, prefix="/api/v1")
    app.include_router(camera_routes.router, prefix="/api/v1")
    app.include_router(thumbnail_routes.router, prefix="/api/v1")

    # WebSocket endpoint for live alerts (real-time + history on connect)
    @app.websocket("/ws/alerts")
    async def websocket_alerts(ws: WebSocket):
        import json as _json
        await ws.accept()

        # Replay historical alerts from Redis so page refresh keeps alert list
        event_repo_ws = RedisEventRepository()
        historical = event_repo_ws.get_recent_alerts(100)
        if historical:
            log.info("WS: replaying %d historical alerts to new client", len(historical))
        for alert_dict in reversed(historical):  # send oldest first
            try:
                envelope = _alert_dict_to_ws_envelope(alert_dict)
                await ws.send_text(_json.dumps(envelope))
            except Exception:
                break  # client disconnected mid-replay

        if _ws_strategy:
            _ws_strategy.register(ws)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            if _ws_strategy:
                _ws_strategy.unregister(ws)

    # Health check
    @app.get("/api/v1/status")
    async def status():
        faiss_repo = FAISSRepository()
        return {
            "status": "running",
            "faiss_vectors": faiss_repo.total_vectors(),
            "mqtt_connected": _mqtt_adapter.is_connected if _mqtt_adapter else False,
        }

    # Alerts endpoint
    @app.get("/api/v1/alerts")
    async def get_alerts():
        event_repo = RedisEventRepository()
        return event_repo.get_recent_alerts(50)

    # Mount uploads directory
    upload_dir = os.getenv("UPLOAD_DIR", "/data/uploads")
    os.makedirs(upload_dir, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=upload_dir), name="uploads")

    return app


app = create_app()


def main():
    cfg = get_config()
    log_level = cfg.log_level.lower()
    uvicorn.run(
        "backend.main:app",
        host=cfg.api_host,
        port=cfg.api_port,
        log_level=log_level,
        reload=False,
    )


if __name__ == "__main__":
    main()
