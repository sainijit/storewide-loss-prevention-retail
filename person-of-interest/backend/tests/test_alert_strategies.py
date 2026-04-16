"""Tests for alert strategies."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from backend.domain.entities.match_result import AlertPayload
from backend.strategy.alert import (
    LogAlertStrategy,
    MQTTAlertStrategy,
    WebSocketAlertStrategy,
)


def _make_alert():
    return AlertPayload(
        alert_id="alert-001",
        poi_id="poi-a",
        severity="high",
        timestamp="2025-01-15T12:00:00Z",
        match={"camera_id": "cam-01", "similarity_score": 0.9},
        poi_metadata={"notes": "test"},
    )


class TestLogAlertStrategy:
    def test_send_does_not_raise(self):
        strategy = LogAlertStrategy()
        # Should simply log, not raise
        strategy.send(_make_alert())

    def test_name(self):
        assert LogAlertStrategy().name() == "log"


class TestMQTTAlertStrategy:
    def test_send_publishes_to_mqtt(self):
        client = MagicMock()
        client.is_connected.return_value = True
        strategy = MQTTAlertStrategy(mqtt_client=client, topic="test/alerts")
        alert = _make_alert()

        strategy.send(alert)

        client.publish.assert_called_once_with("test/alerts", json.dumps(alert.to_dict()))

    def test_send_not_connected(self):
        client = MagicMock()
        client.is_connected.return_value = False
        strategy = MQTTAlertStrategy(mqtt_client=client)

        # Should not raise
        strategy.send(_make_alert())
        client.publish.assert_not_called()

    def test_send_no_client(self):
        strategy = MQTTAlertStrategy()
        # Should not raise
        strategy.send(_make_alert())

    def test_name(self):
        assert MQTTAlertStrategy().name() == "mqtt"


class TestWebSocketAlertStrategy:
    def test_name(self):
        assert WebSocketAlertStrategy().name() == "websocket"

    def test_register_unregister(self):
        strategy = WebSocketAlertStrategy()
        ws = MagicMock()
        strategy.register(ws)
        assert ws in strategy._connections
        strategy.unregister(ws)
        assert ws not in strategy._connections

    def test_send_sync_does_not_raise(self):
        strategy = WebSocketAlertStrategy()
        strategy.send(_make_alert())
