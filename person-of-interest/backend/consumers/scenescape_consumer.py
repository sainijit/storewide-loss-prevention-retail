"""SceneScape regulated scene event consumer — region entry/exit tracking.

Subscribes to: scenescape/regulated/scene/{scene_id}
Payload: objects list with per-person `regions` dict
Region entry/exit is detected by diffing current vs previous region membership.

Payload structure per person object:
  {
    id: str,
    category: "person",
    visibility: [camera_id, ...],
    metadata: {...},
    regions: {
      region_id: {"entered": timestamp},
      ...
    }
  }
"""

from __future__ import annotations

import logging
import re
import time
from typing import Dict, Set

from backend.service.event_service import EventService

log = logging.getLogger("poi.consumer.scenescape")

# Topic: scenescape/regulated/scene/{scene_id}  (SceneScape v2026+)
REGION_TOPIC_RE = re.compile(r"scenescape/regulated/scene/(?P<scene_id>[^/]+)$")


class ScenescapeRegionConsumer:
    """Handles region entry/exit events from the regulated scene MQTT topic.

    Uses stateful diffing: detects entry when a region_id appears in a person's
    `regions` dict for the first time, and exit when it disappears.
    """

    # Max age (seconds) before stale entries are evicted from _region_presence
    _PRESENCE_MAX_AGE = 3600  # 1 hour
    _EVICTION_INTERVAL = 60  # seconds between eviction sweeps

    def __init__(self, event_service: EventService) -> None:
        self._event_service = event_service
        # {object_id: (set of region_ids, last_seen_timestamp)}
        self._region_presence: Dict[str, Set[str]] = {}
        self._last_seen: Dict[str, float] = {}
        self._last_eviction = 0.0

    def handle_event(self, topic: str, payload: dict) -> None:
        m = REGION_TOPIC_RE.match(topic)
        if not m:
            log.debug("Topic %s does not match regulated scene pattern, ignoring", topic)
            return

        self._evict_stale()

        scene_id = m.group("scene_id")
        timestamp = payload.get("timestamp", "")

        objects = payload.get("objects", [])
        # Regulated topic objects is a list; also accept dict for robustness
        if isinstance(objects, dict):
            persons = objects.get("person", [])
        elif isinstance(objects, list):
            persons = [o for o in objects if o.get("category") == "person" or o.get("type") == "person"]
        else:
            return

        current_ids: set = set()

        for obj in persons:
            object_id = obj.get("id", "")
            if not object_id:
                continue
            current_ids.add(object_id)

            cameras = obj.get("visibility", [])
            camera_id = cameras[0] if cameras else None

            # Regions dict: {region_id: {"entered": timestamp, ...}}
            regions_now: Set[str] = set(obj.get("regions", {}).keys())
            regions_before: Set[str] = self._region_presence.get(object_id, set())

            entered_regions = regions_now - regions_before
            exited_regions = regions_before - regions_now

            for region_id in entered_regions:
                region_info = obj.get("regions", {}).get(region_id, {})
                entry_ts = region_info.get("entered", timestamp)
                region_name = region_info.get("name", region_id)
                try:
                    self._event_service.store_region_entry(
                        object_id, entry_ts, scene_id, region_id, region_name, camera_id
                    )
                    log.info(
                        "Region ENTER: obj=%s scene=%s region=%s camera=%s",
                        object_id, scene_id, region_id, camera_id,
                    )
                except Exception:
                    log.exception("Error storing region entry for obj %s region %s", object_id, region_id)

            for region_id in exited_regions:
                region_name = region_id  # name not available on exit; use id
                try:
                    self._event_service.store_region_exit(
                        object_id, timestamp, scene_id, region_id, region_name
                    )
                    log.info(
                        "Region EXIT: obj=%s scene=%s region=%s",
                        object_id, scene_id, region_id,
                    )
                except Exception:
                    log.exception("Error storing region exit for obj %s region %s", object_id, region_id)

            self._region_presence[object_id] = regions_now
            self._last_seen[object_id] = time.monotonic()

        # Clean up presence tracking for objects no longer in scene
        gone_ids = set(self._region_presence.keys()) - current_ids
        for object_id in gone_ids:
            old_regions = self._region_presence.pop(object_id, set())
            self._last_seen.pop(object_id, None)
            for region_id in old_regions:
                try:
                    self._event_service.store_region_exit(
                        object_id, timestamp, scene_id, region_id, region_id
                    )
                    log.info(
                        "Region EXIT (object left scene): obj=%s scene=%s region=%s",
                        object_id, scene_id, region_id,
                    )
                except Exception:
                    log.exception("Error storing implicit region exit for obj %s", object_id)

    def _evict_stale(self) -> None:
        """Remove entries older than _PRESENCE_MAX_AGE to prevent unbounded growth."""
        now = time.monotonic()
        if now - self._last_eviction < self._EVICTION_INTERVAL:
            return
        self._last_eviction = now
        cutoff = now - self._PRESENCE_MAX_AGE
        stale = [oid for oid, ts in self._last_seen.items() if ts < cutoff]
        for oid in stale:
            self._region_presence.pop(oid, None)
            self._last_seen.pop(oid, None)
        if stale:
            log.info("Evicted %d stale entries from region presence tracker", len(stale))
