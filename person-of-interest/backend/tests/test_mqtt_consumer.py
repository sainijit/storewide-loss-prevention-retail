"""Tests for MQTT EventConsumer."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import numpy as np

from backend.consumers.mqtt_consumer import EventConsumer
from backend.domain.entities.match_result import AlertPayload, MatchResult
from backend.observer.events import EventBus


class TestEventConsumer:
    def _make_consumer(self, match_result=None):
        matching = MagicMock()
        matching.match_object.return_value = match_result

        events = MagicMock()

        alert_service = MagicMock()
        alert_service.create_alert_payload.return_value = AlertPayload(
            alert_id="alert-test",
            poi_id="poi-match",
            severity="high",
            timestamp="t",
            match={},
            poi_metadata={},
        )

        bus = EventBus()

        consumer = EventConsumer(matching, events, alert_service, bus)
        return consumer, matching, events, alert_service, bus

    def _make_payload(self, embedding=None, object_id="obj-1"):
        if embedding is None:
            embedding = [np.random.randn(256).tolist()]
        return {
            "id": "scene-1",
            "timestamp": "2025-01-15T12:30:00.000Z",
            "name": "storewide loss prevention",
            "objects": [
                {
                    "id": object_id,
                    "category": "person",
                    "confidence": 0.95,
                    "center_of_mass": {"x": 320, "y": 240, "width": 80, "height": 160},
                    "visibility": ["camera-01"],
                    "metadata": {
                        "reid": {
                            "embedding_vector": embedding,
                        }
                    },
                }
            ],
            "entered": [],
        }

    def test_processes_matching_person(self):
        match = MatchResult(poi_id="poi-match", similarity_score=0.9, faiss_distance=0.9)
        consumer, matching, events, alert_service, bus = self._make_consumer(match_result=match)

        topic = "scenescape/event/scene-1/objects"
        consumer.handle_event(topic, self._make_payload())

        matching.match_object.assert_called_once()
        alert_service.create_alert_payload.assert_called_once()
        # Two store_movement calls: one before match, one after with poi_id
        assert events.store_movement.call_count == 2

    def test_ignores_non_matching_topic(self):
        consumer, matching, _, _, _ = self._make_consumer()

        consumer.handle_event("some/other/topic", {})

        matching.match_object.assert_not_called()

    def test_ignores_non_person_objects(self):
        consumer, matching, events, _, _ = self._make_consumer()
        payload = self._make_payload()
        payload["objects"][0]["category"] = "vehicle"
        payload["objects"][0].pop("type", None)

        topic = "scenescape/event/scene-1/objects"
        consumer.handle_event(topic, payload)

        matching.match_object.assert_not_called()
        events.store_movement.assert_not_called()

    def test_skips_objects_without_embedding(self):
        consumer, matching, events, _, _ = self._make_consumer()
        payload = self._make_payload()
        payload["objects"][0]["metadata"]["reid"]["embedding_vector"] = None

        topic = "scenescape/event/scene-1/objects"
        consumer.handle_event(topic, payload)

        matching.match_object.assert_not_called()

    def test_no_match_found(self):
        consumer, matching, events, alert_service, _ = self._make_consumer(match_result=None)

        topic = "scenescape/event/scene-1/objects"
        consumer.handle_event(topic, self._make_payload())

        matching.match_object.assert_called_once()
        alert_service.create_alert_payload.assert_not_called()
        # Only one store_movement (pre-match), no second call with poi_id
        events.store_movement.assert_called_once()

    def test_flattens_nested_embedding(self):
        nested = [np.random.randn(256).tolist()]  # [[256 floats]]
        consumer, matching, _, _, _ = self._make_consumer(match_result=None)

        topic = "scenescape/event/scene-1/objects"
        consumer.handle_event(topic, self._make_payload(embedding=nested))

        # Verify the embedding passed to match_object is flat
        call_args = matching.match_object.call_args[0]
        embedding_passed = call_args[1]
        assert len(embedding_passed) == 256
        assert not isinstance(embedding_passed[0], list)

    def test_dedup_objects_by_id(self):
        consumer, matching, _, _, _ = self._make_consumer(match_result=None)
        payload = self._make_payload(object_id="dup-obj")
        # Add same object to entered list
        payload["entered"] = [payload["objects"][0].copy()]

        topic = "scenescape/event/scene-1/objects"
        consumer.handle_event(topic, payload)

        # Should only be called once despite the object appearing twice
        matching.match_object.assert_called_once()

    def test_publishes_match_found_event(self):
        match = MatchResult(poi_id="poi-m", similarity_score=0.85, faiss_distance=0.85)
        consumer, _, _, _, bus = self._make_consumer(match_result=match)
        observer_cb = MagicMock()
        bus.subscribe("match_found", observer_cb)

        topic = "scenescape/event/scene-1/objects"
        consumer.handle_event(topic, self._make_payload())

        observer_cb.assert_called_once()
        event = observer_cb.call_args[0][0]
        assert event.object_id == "obj-1"

    def test_uses_visibility_for_camera_id(self):
        consumer, _, events, _, _ = self._make_consumer(match_result=None)
        payload = self._make_payload()
        payload["objects"][0]["visibility"] = ["camera-05"]

        topic = "scenescape/event/scene-1/objects"
        consumer.handle_event(topic, payload)

        call_kwargs = events.store_movement.call_args[1]
        assert call_kwargs["camera_id"] == "camera-05"

    def test_falls_back_to_scene_name_for_camera_id(self):
        consumer, _, events, _, _ = self._make_consumer(match_result=None)
        payload = self._make_payload()
        payload["objects"][0]["visibility"] = []
        payload["name"] = "store-scene"

        topic = "scenescape/event/scene-1/objects"
        consumer.handle_event(topic, payload)

        call_kwargs = events.store_movement.call_args[1]
        assert call_kwargs["camera_id"] == "store-scene"
