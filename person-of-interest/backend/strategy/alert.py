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

    def register(self, ws) -> None:
        self._connections.append(ws)

    def unregister(self, ws) -> None:
        if ws in self._connections:
            self._connections.remove(ws)

    async def send_async(self, alert: AlertPayload) -> None:
        data = json.dumps(alert.to_dict())
        dead = []
        for ws in self._connections:
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.remove(ws)

    def send(self, alert: AlertPayload) -> None:
        # Synchronous fallback — log only; real delivery is via send_async
        log.info("WebSocket alert queued: %s", alert.alert_id)

    def name(self) -> str:
        return "websocket"

    @property
    def connection_count(self) -> int:
        return len(self._connections)
