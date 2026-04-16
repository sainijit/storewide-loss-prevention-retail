"""Tests for EventService."""

from __future__ import annotations

from unittest.mock import MagicMock

from backend.service.event_service import EventService


class TestEventService:
    def _make_service(self):
        repo = MagicMock()
        return EventService(repo), repo

    def test_store_movement(self):
        service, repo = self._make_service()
        service.store_movement(
            object_id="obj-1",
            timestamp="2025-01-15T12:00:00Z",
            camera_id="cam-01",
            region="aisle1",
            poi_id="poi-x",
        )
        repo.store_event.assert_called_once()
        evt = repo.store_event.call_args[0][0]
        assert evt.object_id == "obj-1"
        assert evt.camera_id == "cam-01"
        assert evt.poi_id == "poi-x"

    def test_search_history_empty(self):
        service, repo = self._make_service()
        repo.get_events_for_poi.return_value = []

        result = service.search_history("poi-x")

        assert result["event_type"] == "poi_history_result"
        assert result["total_visits"] == 0
        assert result["visits"] == []

    def test_search_history_groups_by_date(self):
        service, repo = self._make_service()
        repo.get_events_for_poi.return_value = [
            {"timestamp": "2025-01-15T10:00:00Z", "camera_id": "cam-01", "region": "aisle1"},
            {"timestamp": "2025-01-15T14:00:00Z", "camera_id": "cam-02", "region": "aisle2"},
            {"timestamp": "2025-01-16T09:00:00Z", "camera_id": "cam-01", "region": "aisle1"},
        ]

        result = service.search_history("poi-x")

        assert result["total_visits"] == 2
        assert result["visits"][0]["date"] == "2025-01-15"
        assert result["visits"][1]["date"] == "2025-01-16"
        # Day 1 had two cameras
        assert set(result["visits"][0]["cameras_visited"]) == {"cam-01", "cam-02"}
        # Region name should be present
        assert result["visits"][0]["region_name"] != ""

    def test_search_history_with_time_range(self):
        service, repo = self._make_service()
        repo.get_events_for_poi.return_value = []

        service.search_history("poi-x", start_time="2025-01-14", end_time="2025-01-16")

        repo.get_events_for_poi.assert_called_once_with("poi-x", "2025-01-14", "2025-01-16")

    def test_search_history_single_event_per_day(self):
        service, repo = self._make_service()
        repo.get_events_for_poi.return_value = [
            {"timestamp": "2025-01-15T10:00:00Z", "camera_id": "cam-01"},
        ]

        result = service.search_history("poi-x")

        assert result["total_visits"] == 1
        visit = result["visits"][0]
        assert visit["entry_time"] == "2025-01-15T10:00:00Z"
        assert visit["exit_time"] is None  # Only one event
