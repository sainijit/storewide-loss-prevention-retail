"""MQTT event consumer — processes SceneScape scene events for POI face matching.

Primary topic: scenescape/data/camera/{camera_id}
  Payload: per-camera DLStreamer output with person detections and face sub_objects.
  Person objects contain body-reid embeddings; face sub_objects (when present) contain
  face-reid embeddings from face-reidentification-retail-0095 — the SAME model used
  during POI enrollment.  Only face sub_object embeddings are used for FAISS matching.

  Dedup key: f"cam:{camera_id}:{person_int_id}" with 60s TTL.

Secondary topic (monitoring only): scenescape/external/{scene_id}/person
  Carries global UUIDs, reid_state, and body-reid embeddings (person-reidentification-
  retail-0277).  Body embeddings are a DIFFERENT embedding space from the face model
  and must NOT be used for FAISS comparison against face-enrolled POIs.
  External topic is subscribed to for reid_state logging and future cross-camera
  UUID correlation only.

Embedding space alignment:
  Enrollment (EmbeddingModelFactory):  face-reidentification-retail-0095, 256-dim,
                                       with landmark alignment preprocessing.
  Runtime (camera topic face objects): face-reidentification-retail-0095, 256-dim,
                                       simple resize preprocessing (no landmark align).
  Both are in the same base model embedding space → FAISS cosine similarity is valid.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import struct
from typing import List, Optional

from backend.observer.events import EventBus, MatchFoundEvent
from backend.service.alert_service import AlertService
from backend.service.event_service import EventService
from backend.service.matching_service import MatchingService
from backend.utils.thumbnail import submit_capture

log = logging.getLogger("poi.consumer")

# Primary: camera topic — face embeddings from face-reidentification-retail-0095
CAMERA_TOPIC_RE = re.compile(r"scenescape/data/camera/(?P<camera_id>[^/]+)$")

# Secondary (monitoring only): external topic — body embeddings + global UUID + reid_state
EXTERNAL_TOPIC_RE = re.compile(r"scenescape/external/(?P<scene_id>[^/]+)/person$")

# Keep alias for existing imports
TOPIC_RE = CAMERA_TOPIC_RE

# Minimum face detection confidence to attempt FAISS matching
FACE_CONFIDENCE_THRESHOLD = 0.80


def _decode_embedding_b64(b64_str: str) -> Optional[List[float]]:
    """Decode a base64-encoded IEEE-754 float32 embedding vector."""
    try:
        raw = base64.b64decode(b64_str)
        n = len(raw) // 4
        if n == 0:
            return None
        return list(struct.unpack(f"{n}f", raw))
    except Exception:
        log.debug("Failed to decode base64 embedding")
        return None


def _parse_embedding(raw) -> Optional[List[float]]:
    """Parse an embedding from any wire format.

    Handles:
      - list / nested list  ([[f1, f2, ...]] or [f1, f2, ...])
      - JSON string         ('[[f1, f2, ...]]' or '[f1, f2, ...]')
      - base64 string       (IEEE-754 float32 packed binary, legacy camera topic)
    """
    if raw is None or raw == "":
        return None

    if isinstance(raw, list):
        flat = raw[0] if raw and isinstance(raw[0], list) else raw
        try:
            return [float(x) for x in flat] if flat else None
        except (TypeError, ValueError):
            return None

    if isinstance(raw, str):
        # Try JSON array first (external topic format)
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                flat = parsed[0] if parsed and isinstance(parsed[0], list) else parsed
                return [float(x) for x in flat] if flat else None
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
        # Fall back to base64 binary (legacy camera topic format)
        return _decode_embedding_b64(raw)

    return None


class EventConsumer:
    """Consumes MQTT scene events and orchestrates matching + alerting."""

    def __init__(
        self,
        matching_service: MatchingService,
        event_service: EventService,
        alert_service: AlertService,
        event_bus: EventBus,
        event_repo=None,
    ) -> None:
        self._matching = matching_service
        self._events = event_service
        self._alerts = alert_service
        self._event_bus = event_bus
        self._event_repo = event_repo  # used for thumbnail Redis ops

    def handle_event(self, topic: str, payload: dict) -> None:
        """Route incoming MQTT message to the appropriate handler."""
        if CAMERA_TOPIC_RE.match(topic):
            self._handle_camera_event(topic, payload)
        elif EXTERNAL_TOPIC_RE.match(topic):
            self._handle_external_event(topic, payload)

    # ── Primary: camera topic face embeddings ───────────────────────────────

    def _handle_camera_event(self, topic: str, payload: dict) -> None:
        """Process scenescape/data/camera/{camera_id} messages.

        Extracts face sub_object embeddings (face-reidentification-retail-0095)
        for FAISS matching.  Body-level reid embeddings are ignored — they come
        from person-reidentification-retail-0277, a different embedding space.

        Only persons whose face sub_objects exceed FACE_CONFIDENCE_THRESHOLD are
        processed.  Dedup key is f"cam:{camera_id}:{person_int_id}" with 60s TTL
        to suppress repeated alerts for the same person-in-frame.
        """
        m = CAMERA_TOPIC_RE.match(topic)
        if not m:
            return

        camera_id = m.group("camera_id")
        timestamp = payload.get("timestamp", "")

        objects = payload.get("objects", {})
        if isinstance(objects, dict):
            persons = objects.get("person", [])
        elif isinstance(objects, list):
            persons = [o for o in objects
                       if o.get("category") == "person" or o.get("type") == "person"]
        else:
            return

        seen_ids: set = set()

        for obj in persons:
            person_int_id = obj.get("id")
            if person_int_id is None or person_int_id in seen_ids:
                continue
            seen_ids.add(person_int_id)

            # Only process persons that have face sub_objects with usable embeddings.
            # Body-level embedding is intentionally ignored (wrong embedding space).
            embedding_vector: Optional[List[float]] = None
            best_face_conf = 0.0
            best_face_bbox = None

            for face in obj.get("sub_objects", {}).get("face", []):
                face_conf = face.get("confidence", 0.0)
                if face_conf < FACE_CONFIDENCE_THRESHOLD:
                    log.debug(
                        "Skipping low-confidence face: camera=%s person=%s conf=%.3f",
                        camera_id, person_int_id, face_conf,
                    )
                    continue
                raw = face.get("metadata", {}).get("reid", {}).get("embedding_vector", "")
                vec = _parse_embedding(raw)
                if vec and face_conf > best_face_conf:
                    embedding_vector = vec
                    best_face_conf = face_conf
                    best_face_bbox = face.get("bounding_box_px")

            if not embedding_vector:
                log.debug("No face embedding for camera=%s person=%s — skipping FAISS", camera_id, person_int_id)
                continue

            log.info(
                "Face embedding found: camera=%s person=%s conf=%.3f dim=%d",
                camera_id, person_int_id, best_face_conf, len(embedding_vector),
            )

            # Use person bounding box for thumbnail crop; fall back to face bbox
            person_bbox = obj.get("bounding_box_px") or best_face_bbox

            # Stable dedup key within a camera session
            object_id = f"cam:{camera_id}:{person_int_id}"

            self._run_matching(
                object_id=object_id,
                embedding_vector=embedding_vector,
                timestamp=timestamp,
                camera_id=camera_id,
                confidence=best_face_conf,
                bounding_box=person_bbox,
            )

    # ── Secondary: external topic (monitoring / UUID tracking only) ──────────

    def _handle_external_event(self, topic: str, payload: dict) -> None:
        """Process scenescape/external/{scene_id}/person messages.

        Monitoring only — body-reid embeddings on this topic are from
        person-reidentification-retail-0277, a different embedding space from
        the face-reidentification-retail-0095 model used for POI enrollment.
        FAISS matching is NOT performed here.

        Logs reid_state transitions for observability and stores movement events
        so the timeline tracks all detected persons, not only those with faces.
        """
        m = EXTERNAL_TOPIC_RE.match(topic)
        if not m:
            return

        timestamp = payload.get("timestamp", "")
        scene_name = payload.get("name", m.group("scene_id"))

        objects = payload.get("objects", [])
        if isinstance(objects, dict):
            persons = objects.get("person", [])
        elif isinstance(objects, list):
            persons = [o for o in objects
                       if o.get("type") == "person" or o.get("category") == "person"]
        else:
            return

        for obj in persons:
            object_id = obj.get("id")
            if not object_id:
                continue
            reid_state = obj.get("reid_state", "")
            visibility = obj.get("visibility", [])
            camera_id = visibility[0] if visibility else scene_name
            log.debug(
                "External topic: uuid=%s reid_state=%r camera=%s (monitoring only)",
                object_id, reid_state, camera_id,
            )
            self._events.store_movement(
                object_id=object_id,
                timestamp=timestamp,
                camera_id=camera_id,
                region=camera_id,
            )

    # ── Shared matching + alerting ──────────────────────────────────────────

    def _run_matching(
        self,
        object_id: str,
        embedding_vector: List[float],
        timestamp: str,
        camera_id: Optional[str],
        confidence: float,
        bounding_box,
    ) -> None:
        """Run FAISS lookup and emit alerts for a confirmed detection."""
        display_camera = camera_id or "unknown"

        # Record movement before matching attempt
        self._events.store_movement(
            object_id=object_id,
            timestamp=timestamp,
            camera_id=display_camera,
            region=display_camera,
        )

        match = self._matching.match_object(object_id, embedding_vector)
        if match is None:
            return

        log.info(
            "POI match: poi=%s uuid=%s camera=%s similarity=%.3f",
            match.poi_id, object_id, display_camera, match.similarity_score,
        )

        # Capture thumbnail from RTSP — only when we have a valid camera_id
        thumbnail_path = ""
        if camera_id and self._event_repo and self._event_repo.claim_thumbnail(object_id, ttl=30):
            future = submit_capture(camera_id, bounding_box)
            try:
                b64 = future.result(timeout=6)
                if b64:
                    self._event_repo.store_thumbnail(object_id, b64, ttl=3600)
                    thumbnail_path = f"/api/v1/thumbnail/{object_id}"
                    log.info("Thumbnail captured for uuid=%s camera=%s", object_id, camera_id)
                else:
                    log.warning("Thumbnail returned no data for uuid=%s camera=%s", object_id, camera_id)
            except Exception:
                log.warning("Thumbnail timed out or failed for uuid=%s camera=%s", object_id, camera_id)
        elif not camera_id:
            log.warning("No camera_id for uuid=%s — thumbnail skipped (visibility empty)", object_id)
        elif self._event_repo and self._event_repo.get_thumbnail(object_id):
            thumbnail_path = f"/api/v1/thumbnail/{object_id}"

        alert = self._alerts.create_alert_payload(
            match=match,
            object_id=object_id,
            timestamp=timestamp,
            camera_id=display_camera,
            region_name=display_camera,
            confidence=confidence,
            center_of_mass=bounding_box,
            thumbnail_path=thumbnail_path,
        )

        # Update movement event with the matched poi_id
        self._events.store_movement(
            object_id=object_id,
            timestamp=timestamp,
            camera_id=display_camera,
            region=display_camera,
            poi_id=match.poi_id,
        )

        self._event_bus.publish("match_found", MatchFoundEvent(
            alert=alert,
            object_id=object_id,
            timestamp=timestamp,
        ))
