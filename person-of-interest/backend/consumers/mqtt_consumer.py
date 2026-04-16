"""MQTT event consumer — processes SceneScape scene events."""

from __future__ import annotations

import logging
import re
from typing import Optional

from backend.observer.events import EventBus, MatchFoundEvent
from backend.service.alert_service import AlertService
from backend.service.event_service import EventService
from backend.service.matching_service import MatchingService

log = logging.getLogger("poi.consumer")

# Topic pattern: scenescape/event/{scene_id}/objects
TOPIC_RE = re.compile(
    r"scenescape/event/(?P<scene_id>[^/]+)/objects"
)


class EventConsumer:
    """Consumes MQTT scene events and orchestrates matching + alerting."""

    def __init__(
        self,
        matching_service: MatchingService,
        event_service: EventService,
        alert_service: AlertService,
        event_bus: EventBus,
    ) -> None:
        self._matching = matching_service
        self._events = event_service
        self._alerts = alert_service
        self._event_bus = event_bus

    def handle_event(self, topic: str, payload: dict) -> None:
        """Process a single MQTT message.

        Expected topic: scenescape/event/{scene_id}/objects
        Expected payload: { timestamp, id, name, objects[], ... }
        """
        m = TOPIC_RE.match(topic)
        if not m:
            return

        scene_id = m.group("scene_id")
        scene_name = payload.get("name", scene_id)
        timestamp = payload.get("timestamp", "")

        objects = payload.get("objects", [])
        entered = payload.get("entered", [])

        # Process all objects in the message
        all_objects = objects + entered
        seen_ids = set()

        for obj in all_objects:
            if obj.get("category") != "person" and obj.get("type") != "person":
                continue

            object_id = obj.get("id")
            if not object_id or object_id in seen_ids:
                continue
            seen_ids.add(object_id)

            # Extract embedding
            reid = obj.get("metadata", {}).get("reid", {})
            embedding_vector = reid.get("embedding_vector")
            if not embedding_vector:
                continue

            # Flatten nested array [[...]] → [...]
            if isinstance(embedding_vector, list) and len(embedding_vector) == 1:
                if isinstance(embedding_vector[0], list):
                    embedding_vector = embedding_vector[0]

            confidence = obj.get("confidence", 0.0)
            center_of_mass = obj.get("center_of_mass")

            # Determine camera from visibility or scene name
            visibility = obj.get("visibility", [])
            camera_id = visibility[0] if visibility else scene_name

            # Store movement event
            self._events.store_movement(
                object_id=object_id,
                timestamp=timestamp,
                camera_id=camera_id,
                region=scene_name,
            )

            # Match against POI index
            match = self._matching.match_object(object_id, embedding_vector)
            if match is None:
                continue

            # Build alert payload
            alert = self._alerts.create_alert_payload(
                match=match,
                object_id=object_id,
                timestamp=timestamp,
                camera_id=camera_id,
                region_name=scene_name,
                confidence=confidence,
                center_of_mass=center_of_mass,
            )

            # Update movement event with poi_id
            self._events.store_movement(
                object_id=object_id,
                timestamp=timestamp,
                camera_id=camera_id,
                region=scene_name,
                poi_id=match.poi_id,
            )

            # Publish MatchFoundEvent → triggers AlertService via Observer
            event = MatchFoundEvent(
                alert=alert,
                object_id=object_id,
                timestamp=timestamp,
            )
            self._event_bus.publish("match_found", event)
