"""Event Service — stores movement events and supports historical queries."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Optional

from backend.domain.entities.event import MovementEvent
from backend.domain.interfaces.repository import EventRepository

log = logging.getLogger("poi.service.event")


class EventService:
    """Handles movement event storage and historical search aggregation."""

    def __init__(self, event_repo: EventRepository) -> None:
        self._repo = event_repo

    def store_movement(
        self,
        object_id: str,
        timestamp: str,
        camera_id: str,
        region: str,
        poi_id: Optional[str] = None,
        embedding_ref: Optional[str] = None,
    ) -> None:
        event = MovementEvent(
            object_id=object_id,
            timestamp=timestamp,
            camera_id=camera_id,
            region=region,
            poi_id=poi_id,
            embedding_reference=embedding_ref,
        )
        self._repo.store_event(event)

    def search_history(
        self,
        poi_id: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> dict:
        events = self._repo.get_events_for_poi(poi_id, start_time, end_time)
        if not events:
            return {
                "event_type": "poi_history_result",
                "poi_id": poi_id,
                "visits": [],
                "total_visits": 0,
                "search_stats": {"vectors_searched": 0, "query_latency_ms": 0},
            }

        # Aggregate events into visits (grouped by date)
        visits_by_date: dict[str, list[dict]] = defaultdict(list)
        for evt in events:
            ts = evt.get("timestamp", "")
            date = ts[:10] if len(ts) >= 10 else "unknown"
            visits_by_date[date].append(evt)

        visits = []
        for date, day_events in sorted(visits_by_date.items()):
            timestamps = [e["timestamp"] for e in day_events]
            cameras = list({e.get("camera_id", "") for e in day_events})
            regions = list({e.get("region", "") for e in day_events if e.get("region")})
            entry = min(timestamps)
            exit_time = max(timestamps) if len(timestamps) > 1 else None
            duration = None
            if exit_time and entry != exit_time:
                try:
                    from datetime import datetime
                    fmt = "%Y-%m-%dT%H:%M:%S"
                    t0 = datetime.fromisoformat(entry.replace("Z", "+00:00"))
                    t1 = datetime.fromisoformat(exit_time.replace("Z", "+00:00"))
                    duration = (t1 - t0).total_seconds()
                except Exception:
                    pass
            visits.append(
                {
                    "date": date,
                    "entry_time": entry,
                    "exit_time": exit_time,
                    "cameras_visited": cameras,
                    "regions": regions,
                    "region_name": regions[0] if regions else "",
                    "duration_sec": duration,
                    "thumbnail": day_events[0].get("thumbnail", ""),
                    "alert_id": "",
                }
            )

        return {
            "event_type": "poi_history_result",
            "poi_id": poi_id,
            "query_range": {"start": start_time or "", "end": end_time or ""},
            "visits": visits,
            "total_visits": len(visits),
            "search_stats": {
                "vectors_searched": len(events),
                "query_latency_ms": 0,
            },
        }
