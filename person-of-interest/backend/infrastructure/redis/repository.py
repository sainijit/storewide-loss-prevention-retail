"""Redis-backed repository implementations."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from backend.core.config import get_config
from backend.domain.entities.event import MovementEvent
from backend.domain.entities.poi import POI, POIStatus, ReferenceImage, Severity
from backend.domain.interfaces.repository import (
    CacheRepository,
    EmbeddingMappingRepository,
    EventRepository,
    POIRepository,
)
from backend.infrastructure.redis.client import RedisClient

log = logging.getLogger("poi.redis.repo")


class RedisPOIRepository(POIRepository):
    """Stores POI metadata in Redis hashes."""

    PREFIX = "poi:"

    def __init__(self) -> None:
        self._r = RedisClient().client

    def save(self, poi: POI) -> None:
        key = f"{self.PREFIX}{poi.poi_id}"
        self._r.set(key, json.dumps(poi.to_dict()))
        self._r.sadd("poi:index", poi.poi_id)

    def get(self, poi_id: str) -> Optional[POI]:
        raw = self._r.get(f"{self.PREFIX}{poi_id}")
        if raw is None:
            return None
        return self._deserialize(json.loads(raw))

    def list_all(self) -> list[POI]:
        poi_ids = self._r.smembers("poi:index")
        pois = []
        for pid in sorted(poi_ids, reverse=True):
            poi = self.get(pid)
            if poi:
                pois.append(poi)
        return pois

    def delete(self, poi_id: str) -> bool:
        key = f"{self.PREFIX}{poi_id}"
        deleted = self._r.delete(key)
        self._r.srem("poi:index", poi_id)
        return deleted > 0

    def update_status(self, poi_id: str, status: str) -> None:
        poi = self.get(poi_id)
        if poi:
            poi.status = POIStatus(status)
            self.save(poi)

    @staticmethod
    def _deserialize(data: dict) -> POI:
        return POI(
            poi_id=data["poi_id"],
            severity=Severity(data["severity"]),
            notes=data.get("notes", ""),
            reference_images=[
                ReferenceImage(
                    source=img.get("source", "uploaded_image"),
                    embedding_id=img.get("embedding_id", ""),
                    vector_dim=img.get("vector_dim", 256),
                    image_path=img.get("image_path", ""),
                )
                for img in data.get("reference_images", [])
            ],
            status=POIStatus(data.get("status", "active")),
            enrolled_by=data.get("enrolled_by", "system"),
            created_at=data.get("timestamp", datetime.utcnow().isoformat() + "Z"),
            embedding_ids=[img.get("embedding_id", "") for img in data.get("reference_images", [])],
        )


class RedisCacheRepository(CacheRepository):
    """Cache-Aside: object_id → poi_id mapping."""

    PREFIX = "object:"

    def __init__(self) -> None:
        self._r = RedisClient().client

    def get_poi_for_object(self, object_id: str) -> Optional[str]:
        return self._r.get(f"{self.PREFIX}{object_id}")

    def set_poi_for_object(self, object_id: str, poi_id: str, ttl: int = 300) -> None:
        self._r.setex(f"{self.PREFIX}{object_id}", ttl, poi_id)


class RedisEventRepository(EventRepository):
    """Stores movement events and alerts in Redis."""

    def __init__(self) -> None:
        self._r = RedisClient().client
        self._cfg = get_config()

    def store_event(self, event: MovementEvent) -> None:
        key = f"event:{event.object_id}:{event.timestamp}"
        self._r.setex(
            key,
            self._cfg.appearance_ttl_days * 86400,
            json.dumps(event.to_dict()),
        )
        if event.poi_id:
            self._r.sadd(f"events:poi:{event.poi_id}", key)
            self._r.expire(f"events:poi:{event.poi_id}", self._cfg.appearance_ttl_days * 86400)

    def get_events_for_poi(
        self, poi_id: str, start_time: Optional[str] = None, end_time: Optional[str] = None
    ) -> list[dict]:
        keys = self._r.smembers(f"events:poi:{poi_id}")
        events = []
        for key in keys:
            raw = self._r.get(key)
            if raw:
                evt = json.loads(raw)
                ts = evt.get("timestamp", "")
                if start_time and ts < start_time:
                    continue
                if end_time and ts > end_time:
                    continue
                events.append(evt)
        events.sort(key=lambda e: e.get("timestamp", ""))
        return events

    def store_alert(self, alert: dict) -> None:
        alert_id = alert.get("alert_id", "")
        self._r.lpush("alerts:recent", json.dumps(alert))
        self._r.ltrim("alerts:recent", 0, 999)
        self._r.set(f"alert:{alert_id}", json.dumps(alert))
        self._r.expire(f"alert:{alert_id}", self._cfg.appearance_ttl_days * 86400)

    def get_recent_alerts(self, limit: int = 50) -> list[dict]:
        raw_list = self._r.lrange("alerts:recent", 0, limit - 1)
        return [json.loads(r) for r in raw_list]

    def is_alert_sent(self, object_id: str) -> bool:
        return self._r.exists(f"alert:sent:{object_id}") > 0

    def mark_alert_sent(self, object_id: str, ttl: int = 300) -> None:
        self._r.setex(f"alert:sent:{object_id}", ttl, "1")

    def store_thumbnail(self, object_id: str, b64_jpeg: str, ttl: int = 3600) -> None:
        """Store base64 JPEG thumbnail for an object. TTL defaults to 1 hour."""
        self._r.setex(f"thumbnail:{object_id}", ttl, b64_jpeg)

    def get_thumbnail(self, object_id: str) -> Optional[str]:
        raw = self._r.get(f"thumbnail:{object_id}")
        return raw.decode() if isinstance(raw, bytes) else raw

    def claim_thumbnail(self, object_id: str, ttl: int = 30) -> bool:
        """Atomically claim the right to capture thumbnail (NX). Returns True if claim acquired."""
        return bool(self._r.set(f"thumbnail:claiming:{object_id}", "1", ex=ttl, nx=True))

    def store_region_presence(self, object_id, timestamp, scene_id, region_id, region_name, camera_id=None):
        """Store region entry presence record."""
        import json
        key = f"region:presence:{scene_id}:{region_id}:{object_id}"
        data = {"first_seen": timestamp, "region_name": region_name, "camera_id": camera_id or ""}
        self._r.setex(key, 3600, json.dumps(data))  # 1h TTL

    def get_region_presence(self, object_id, scene_id, region_id):
        """Get region presence record."""
        import json
        key = f"region:presence:{scene_id}:{region_id}:{object_id}"
        raw = self._r.get(key)
        return json.loads(raw) if raw else None

    def delete_region_presence(self, object_id, scene_id, region_id):
        """Delete region presence record after exit."""
        key = f"region:presence:{scene_id}:{region_id}:{object_id}"
        self._r.delete(key)

    def store_region_dwell(self, object_id, timestamp, scene_id, region_id, region_name, dwell_sec=None):
        """Store region dwell record (entry + exit + duration)."""
        import json
        from datetime import datetime, timezone
        date_key = timestamp[:10] if len(timestamp) >= 10 else datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key = f"region:dwell:{object_id}:{scene_id}:{region_id}:{date_key}"
        data = {
            "object_id": object_id,
            "scene_id": scene_id,
            "region_id": region_id,
            "region_name": region_name,
            "exit_time": timestamp,
            "dwell_sec": dwell_sec,
        }
        self._r.setex(key, 86400 * 7, json.dumps(data))  # 7 day TTL


class RedisEmbeddingMappingRepository(EmbeddingMappingRepository):
    """Maps FAISS internal integer IDs to POI string IDs."""

    def __init__(self) -> None:
        self._r = RedisClient().client

    def map_faiss_to_poi(self, faiss_id: int, poi_id: str) -> None:
        self._r.set(f"faiss2poi:{faiss_id}", poi_id)
        self._r.sadd(f"poi2faiss:{poi_id}", str(faiss_id))

    def get_poi_for_faiss(self, faiss_id: int) -> Optional[str]:
        return self._r.get(f"faiss2poi:{faiss_id}")

    def remove_mappings_for_poi(self, poi_id: str) -> None:
        faiss_ids = self._r.smembers(f"poi2faiss:{poi_id}")
        pipe = self._r.pipeline()
        for fid in faiss_ids:
            pipe.delete(f"faiss2poi:{fid}")
        pipe.delete(f"poi2faiss:{poi_id}")
        pipe.execute()
