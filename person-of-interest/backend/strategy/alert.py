"""Alert delivery strategies — Strategy pattern."""

from __future__ import annotations

import json
import logging
from typing import Optional

from backend.domain.entities.match_result import AlertPayload
from backend.domain.interfaces.alert import AlertStrategy

log = logging.getLogger("poi.strategy.alert")


class LogAlertStrategy(AlertStrategy):
    """Log alerts to stdout."""

    def send(self, alert: AlertPayload) -> None:
        log.warning(
            "ALERT [%s] poi=%s severity=%s similarity=%.2f camera=%s",
            alert.alert_id,
            alert.poi_id,
            alert.severity,
            alert.match.get("similarity_score", 0),
            alert.match.get("camera_id", "unknown"),
        )

    def name(self) -> str:
        return "log"


class MQTTAlertStrategy(AlertStrategy):
    """Publish alerts to an MQTT topic."""

    def __init__(self, mqtt_client=None, topic: str = "poi/alerts") -> None:
        self._mqtt = mqtt_client
        self._topic = topic

    def send(self, alert: AlertPayload) -> None:
        if self._mqtt and self._mqtt.is_connected():
            self._mqtt.publish(self._topic, json.dumps(alert.to_dict()))
            log.info("Alert published to MQTT topic %s", self._topic)
        else:
            log.warning("MQTT not connected, alert not published: %s", alert.alert_id)

    def name(self) -> str:
        return "mqtt"


class WebSocketAlertStrategy(AlertStrategy):
    """Broadcast alerts via WebSocket to connected UI clients."""

    def __init__(self) -> None:
        self._connections: list = []
        self._loop = None

    def set_event_loop(self, loop) -> None:
        """Store reference to the running asyncio event loop."""
        self._loop = loop

    def register(self, ws) -> None:
        self._connections.append(ws)

    def unregister(self, ws) -> None:
        if ws in self._connections:
            self._connections.remove(ws)

    async def send_async(self, alert: AlertPayload) -> None:
        """Broadcast in WS envelope format (same as alert-service broadcasts)."""
        match = alert.match
        poi_meta = alert.poi_metadata
        envelope = {
            "alert_type": "POI_MATCH",
            "metadata": {
                "alert_id": alert.alert_id,
                "poi_id": alert.poi_id,
                "severity": alert.severity,
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
            "timestamp": alert.timestamp,
        }
        data = json.dumps(envelope)
        dead = []
        for ws in self._connections:
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.remove(ws)

    def send(self, alert: AlertPayload) -> None:
        """Schedule async broadcast on the event loop (called from MQTT thread)."""
        import asyncio
        loop = self._loop
        if loop and loop.is_running() and self._connections:
            asyncio.run_coroutine_threadsafe(self.send_async(alert), loop)
            log.info("WebSocket alert scheduled for %d client(s): %s", len(self._connections), alert.alert_id)
        else:
            log.info("WebSocket alert queued (no clients or no loop): %s", alert.alert_id)

    def name(self) -> str:
        return "websocket"

    @property
    def connection_count(self) -> int:
        return len(self._connections)


class AlertServiceStrategy(AlertStrategy):
    """POST alerts to intel/alert-service REST API."""

    def __init__(self, alert_service_url: str) -> None:
        self._url = alert_service_url.rstrip("/")

    def send(self, alert: AlertPayload) -> None:
        import requests
        payload = {
            "alert_type": "POI_MATCH",
            "timestamp": alert.timestamp,
            "metadata": {
                "alert_id": alert.alert_id,
                "poi_id": alert.poi_id,
                "severity": alert.severity,
                "camera_id": alert.match.get("camera_id", ""),
                "similarity_score": alert.match.get("similarity_score", 0),
                "confidence": alert.match.get("confidence", 0),
                "bbox": alert.match.get("bbox", [0, 0, 0, 0]),
                "frame_number": alert.match.get("frame_number", 0),
                "thumbnail_path": alert.match.get("thumbnail_path", ""),
                "notes": alert.poi_metadata.get("notes", ""),
                "enrollment_date": alert.poi_metadata.get("enrollment_date", ""),
                "total_previous_matches": alert.poi_metadata.get("total_previous_matches", 0),
            },
        }
        try:
            resp = requests.post(
                f"{self._url}/api/v1/alerts",
                json=payload,
                timeout=5,
                proxies={"http": None, "https": None},  # bypass system proxy for internal calls
            )
            resp.raise_for_status()
            log.info("Alert forwarded to alert-service: %s", alert.alert_id)
        except Exception:
            log.exception("Failed to POST alert to alert-service: %s", alert.alert_id)

    def name(self) -> str:
        return "alert_service"
