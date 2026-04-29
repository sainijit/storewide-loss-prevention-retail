"""Tests for MQTT EventConsumer."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from backend.consumers.mqtt_consumer import (
    REID_STATE_MATCHED,
    REID_STATE_QUERY_NO_MATCH,
    REID_STATES_READY,
    EventConsumer,
    _parse_embedding,
)
from backend.domain.entities.match_result import AlertPayload, MatchResult
from backend.observer.events import EventBus

# External topic that carries global UUIDs + reid_state
_EXT_TOPIC = "scenescape/external/scene-1/person"
# Legacy camera topic
_CAM_TOPIC = "scenescape/data/camera/Camera_01"


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

    def _make_payload(self, embedding=None, object_id="obj-uuid-1", reid_state=None):
        """Build an external-topic style payload (objects is a list)."""
        if embedding is None:
            embedding = [np.random.randn(256).tolist()]  # nested [[...]]
        obj = {
            "id": object_id,
            "category": "person",
            "type": "person",
            "confidence": 0.95,
            "visibility": ["camera-01"],
            "metadata": {
                "reid": {
                    "embedding_vector": embedding,
                }
            },
        }
        if reid_state is not None:
            obj["reid_state"] = reid_state
        return {
            "id": "scene-1",
            "timestamp": "2025-01-15T12:30:00.000Z",
            "name": "storewide loss prevention",
            "objects": [obj],
        }

    # ── Basic routing ───────────────────────────────────────────────────────

    def test_ignores_non_matching_topic(self):
        consumer, matching, _, _, _ = self._make_consumer()
        consumer.handle_event("some/other/topic", {})
        matching.match_object.assert_not_called()

    def test_routes_external_topic(self):
        match = MatchResult(poi_id="poi-match", similarity_score=0.9, faiss_distance=0.9)
        consumer, matching, _, _, _ = self._make_consumer(match_result=match)
        consumer.handle_event(_EXT_TOPIC, self._make_payload())
        matching.match_object.assert_called_once()

    def test_routes_legacy_camera_topic(self):
        """Legacy camera topic is a no-op (external topic is primary, prevents false positives)."""
        match = MatchResult(poi_id="poi-match", similarity_score=0.9, faiss_distance=0.9)
        consumer, matching, _, _, _ = self._make_consumer(match_result=match)
        cam_payload = {
            "timestamp": "t",
            "objects": {
                "person": [{
                    "id": "42",
                    "confidence": 0.9,
                    "metadata": {"reid": {"embedding_vector": [np.random.randn(256).tolist()]}},
                }]
            }
        }
        consumer.handle_event(_CAM_TOPIC, cam_payload)
        # Camera topic is intentionally suppressed — no FAISS matching without reid_state
        matching.match_object.assert_not_called()

    # ── Person filtering ────────────────────────────────────────────────────

    def test_ignores_non_person_objects(self):
        consumer, matching, events, _, _ = self._make_consumer()
        payload = self._make_payload()
        payload["objects"][0]["category"] = "vehicle"
        payload["objects"][0].pop("type", None)
        consumer.handle_event(_EXT_TOPIC, payload)
        matching.match_object.assert_not_called()
        events.store_movement.assert_not_called()

    def test_skips_objects_without_embedding(self):
        consumer, matching, _, _, _ = self._make_consumer()
        payload = self._make_payload()
        payload["objects"][0]["metadata"]["reid"]["embedding_vector"] = None
        consumer.handle_event(_EXT_TOPIC, payload)
        matching.match_object.assert_not_called()

    # ── reid_state gating ───────────────────────────────────────────────────

    def test_skips_faiss_when_pending_collection(self):
        """reid_state=pending_collection must skip FAISS but still store movement."""
        consumer, matching, events, _, _ = self._make_consumer()
        payload = self._make_payload(reid_state="pending_collection")
        consumer.handle_event(_EXT_TOPIC, payload)
        matching.match_object.assert_not_called()
        events.store_movement.assert_called_once()  # timeline entry only

    def test_proceeds_when_reid_state_matched(self):
        """reid_state=matched must trigger FAISS lookup."""
        match = MatchResult(poi_id="poi-m", similarity_score=0.9, faiss_distance=0.9)
        consumer, matching, _, _, _ = self._make_consumer(match_result=match)
        payload = self._make_payload(reid_state=REID_STATE_MATCHED)
        consumer.handle_event(_EXT_TOPIC, payload)
        matching.match_object.assert_called_once()

    def test_proceeds_when_reid_state_query_no_match(self):
        """reid_state=query_no_match (first visit, confirmed person) must trigger FAISS."""
        match = MatchResult(poi_id="poi-m", similarity_score=0.9, faiss_distance=0.9)
        consumer, matching, _, _, _ = self._make_consumer(match_result=match)
        payload = self._make_payload(reid_state=REID_STATE_QUERY_NO_MATCH)
        consumer.handle_event(_EXT_TOPIC, payload)
        matching.match_object.assert_called_once()

    def test_proceeds_when_reid_state_absent(self):
        """No reid_state field = backward compat, FAISS must run."""
        match = MatchResult(poi_id="poi-m", similarity_score=0.9, faiss_distance=0.9)
        consumer, matching, _, _, _ = self._make_consumer(match_result=match)
        payload = self._make_payload()  # no reid_state
        consumer.handle_event(_EXT_TOPIC, payload)
        matching.match_object.assert_called_once()

    def test_skips_unknown_reid_states(self):
        """Any reid_state value not in REID_STATES_READY must block FAISS."""
        consumer, matching, _, _, _ = self._make_consumer()
        for state in ("collecting", "initializing", "lost", "new_object", "pending_collection"):
            consumer, matching, _, _, _ = self._make_consumer()
            payload = self._make_payload(reid_state=state)
            consumer.handle_event(_EXT_TOPIC, payload)
            matching.match_object.assert_not_called()

    # ── Global UUID cross-camera ────────────────────────────────────────────

    def test_uses_uuid_as_object_id(self):
        """object_id passed to match_object must be the UUID from the message."""
        match = MatchResult(poi_id="poi-m", similarity_score=0.9, faiss_distance=0.9)
        consumer, matching, _, _, _ = self._make_consumer(match_result=match)
        uuid = "fc66d95f-e2b9-42aa-9ce0-382be7f22826"
        payload = self._make_payload(object_id=uuid, reid_state=REID_STATE_MATCHED)
        consumer.handle_event(_EXT_TOPIC, payload)
        call_args = matching.match_object.call_args[0]
        assert call_args[0] == uuid

    def test_uses_visibility_for_camera_id(self):
        consumer, _, events, _, _ = self._make_consumer(match_result=None)
        payload = self._make_payload()
        payload["objects"][0]["visibility"] = ["Camera_05"]
        consumer.handle_event(_EXT_TOPIC, payload)
        call_kwargs = events.store_movement.call_args[1]
        assert call_kwargs["camera_id"] == "Camera_05"

    def test_falls_back_to_scene_name_when_visibility_empty(self):
        consumer, _, events, _, _ = self._make_consumer(match_result=None)
        payload = self._make_payload()
        payload["objects"][0]["visibility"] = []
        payload["name"] = "store-scene"
        consumer.handle_event(_EXT_TOPIC, payload)
        call_kwargs = events.store_movement.call_args[1]
        assert call_kwargs["camera_id"] == "store-scene"

    def test_dedup_objects_by_uuid(self):
        """Same UUID appearing twice in one message should only be processed once."""
        consumer, matching, _, _, _ = self._make_consumer(match_result=None)
        payload = self._make_payload(object_id="dup-uuid")
        payload["objects"].append(payload["objects"][0].copy())
        consumer.handle_event(_EXT_TOPIC, payload)
        matching.match_object.assert_called_once()

    # ── Embedding parsing ───────────────────────────────────────────────────

    def test_flattens_nested_embedding(self):
        """[[f1, f2, ...]] → [f1, f2, ...] (external topic JSON format)."""
        nested = [np.random.randn(256).tolist()]
        consumer, matching, _, _, _ = self._make_consumer(match_result=None)
        consumer.handle_event(_EXT_TOPIC, self._make_payload(embedding=nested))
        call_args = matching.match_object.call_args[0]
        embedding_passed = call_args[1]
        assert len(embedding_passed) == 256
        assert not isinstance(embedding_passed[0], list)

    def test_parses_json_string_embedding(self):
        """Embedding as JSON string (wire format from external topic)."""
        floats = np.random.randn(256).tolist()
        json_str = json.dumps([floats])  # "[[f1, f2, ...]]"
        consumer, matching, _, _, _ = self._make_consumer(match_result=None)
        consumer.handle_event(_EXT_TOPIC, self._make_payload(embedding=json_str))
        call_args = matching.match_object.call_args[0]
        embedding_passed = call_args[1]
        assert len(embedding_passed) == 256

    # ── Match + alert flow ──────────────────────────────────────────────────

    def test_no_match_skips_alert(self):
        consumer, matching, events, alert_service, _ = self._make_consumer(match_result=None)
        consumer.handle_event(_EXT_TOPIC, self._make_payload())
        matching.match_object.assert_called_once()
        alert_service.create_alert_payload.assert_not_called()
        events.store_movement.assert_called_once()  # pre-match only

    def test_match_emits_alert_and_event_bus(self):
        match = MatchResult(poi_id="poi-match", similarity_score=0.9, faiss_distance=0.9)
        consumer, matching, events, alert_service, bus = self._make_consumer(match_result=match)

        consumer.handle_event(_EXT_TOPIC, self._make_payload())

        matching.match_object.assert_called_once()
        alert_service.create_alert_payload.assert_called_once()
        # Two store_movement calls: pre-match + post-match with poi_id
        assert events.store_movement.call_count == 2

    def test_publishes_match_found_event(self):
        match = MatchResult(poi_id="poi-m", similarity_score=0.85, faiss_distance=0.85)
        consumer, _, _, _, bus = self._make_consumer(match_result=match)
        observer_cb = MagicMock()
        bus.subscribe("match_found", observer_cb)

        consumer.handle_event(_EXT_TOPIC, self._make_payload(object_id="uuid-123"))

        observer_cb.assert_called_once()
        event = observer_cb.call_args[0][0]
        assert event.object_id == "uuid-123"


# ── _parse_embedding unit tests ─────────────────────────────────────────────

class TestParseEmbedding:
    def test_none_returns_none(self):
        assert _parse_embedding(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_embedding("") is None

    def test_flat_list(self):
        data = list(range(256))
        result = _parse_embedding(data)
        assert result == [float(x) for x in data]

    def test_nested_list(self):
        data = [list(range(256))]
        result = _parse_embedding(data)
        assert len(result) == 256
        assert result[0] == 0.0

    def test_json_string_flat(self):
        data = list(range(256))
        result = _parse_embedding(json.dumps(data))
        assert len(result) == 256

    def test_json_string_nested(self):
        data = [list(range(256))]
        result = _parse_embedding(json.dumps(data))
        assert len(result) == 256
