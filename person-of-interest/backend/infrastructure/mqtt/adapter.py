"""MQTT adapter for SceneScape event ingestion."""

from __future__ import annotations

import json
import logging
import ssl
import threading
from typing import Callable, Optional

import paho.mqtt.client as mqtt

from backend.core.config import get_config

log = logging.getLogger("poi.mqtt")


class MQTTAdapter:
    """Adapter Pattern — wraps paho-mqtt to subscribe to SceneScape events."""

    def __init__(self, on_event: Callable[[str, dict], None]) -> None:
        self._cfg = get_config()
        self._on_event = on_event
        self._client: Optional[mqtt.Client] = None
        self._running = False

    def start(self) -> None:
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)

        if self._cfg.mqtt_ca_cert:
            self._client.tls_set(
                ca_certs=self._cfg.mqtt_ca_cert,
                cert_reqs=ssl.CERT_REQUIRED,
                tls_version=ssl.PROTOCOL_TLS_CLIENT,
            )
            self._client.tls_insecure_set(True)

        log.info("Connecting to MQTT %s:%d", self._cfg.mqtt_host, self._cfg.mqtt_port)
        self._client.connect(self._cfg.mqtt_host, self._cfg.mqtt_port)
        self._running = True
        self._client.loop_start()

    def stop(self) -> None:
        self._running = False
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            log.info("MQTT disconnected")

    def _on_connect(self, client, userdata, flags, rc, properties=None) -> None:
        if rc == 0:
            topic = self._cfg.mqtt_topic_event
            client.subscribe(topic)
            log.info("MQTT connected, subscribed to %s", topic)
        else:
            log.error("MQTT connection failed: rc=%s", rc)

    def _on_message(self, client, userdata, msg) -> None:
        if not self._running:
            return
        try:
            payload = json.loads(msg.payload)
            self._on_event(msg.topic, payload)
        except json.JSONDecodeError:
            log.warning("Invalid JSON on %s", msg.topic)
        except Exception:
            log.exception("Error handling MQTT message on %s", msg.topic)

    def _on_disconnect(self, client, userdata, flags, rc, properties=None) -> None:
        if self._running:
            log.warning("MQTT disconnected (rc=%s), reconnecting...", rc)

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected()
