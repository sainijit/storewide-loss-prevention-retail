"""Tests for ScenescapeRegionConsumer."""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from backend.consumers.scenescape_consumer import ScenescapeRegionConsumer


@pytest.fixture
def event_service():
    return MagicMock()


@pytest.fixture
def consumer(event_service):
    return ScenescapeRegionConsumer(event_service)


def test_handle_event_region_entry(consumer, event_service):
    """Person entering a region triggers store_region_entry."""
    topic = "scenescape/event/region/scene-001/zone-a/objects"
    payload = {
        "timestamp": "2025-01-15T12:00:00Z",
        "name": "Zone A",
        "entered": [{"id": "person-1", "category": "person", "visibility": ["cam-01"]}],
        "exited": [],
    }
    consumer.handle_event(topic, payload)
    event_service.store_region_entry.assert_called_once_with(
        "person-1", "2025-01-15T12:00:00Z", "scene-001", "zone-a", "Zone A", "cam-01"
    )
    event_service.store_region_exit.assert_not_called()


def test_handle_event_region_exit(consumer, event_service):
    """Person exiting a region triggers store_region_exit."""
    topic = "scenescape/event/region/scene-001/zone-a/objects"
    payload = {
        "timestamp": "2025-01-15T12:05:00Z",
        "name": "Zone A",
        "entered": [],
        "exited": [{"id": "person-1", "category": "person"}],
    }
    consumer.handle_event(topic, payload)
    event_service.store_region_exit.assert_called_once_with(
        "person-1", "2025-01-15T12:05:00Z", "scene-001", "zone-a", "Zone A"
    )
    event_service.store_region_entry.assert_not_called()


def test_handle_event_non_person_ignored(consumer, event_service):
    """Non-person objects are ignored."""
    topic = "scenescape/event/region/scene-001/zone-a/objects"
    payload = {
        "timestamp": "2025-01-15T12:00:00Z",
        "name": "Zone A",
        "entered": [{"id": "cart-1", "category": "cart", "visibility": []}],
        "exited": [{"id": "cart-2", "category": "vehicle"}],
    }
    consumer.handle_event(topic, payload)
    event_service.store_region_entry.assert_not_called()
    event_service.store_region_exit.assert_not_called()


def test_handle_event_non_matching_topic_ignored(consumer, event_service):
    """Non-region topics are silently ignored."""
    topic = "scenescape/event/bfb9f86b/objects"
    payload = {"timestamp": "2025-01-15T12:00:00Z", "objects": []}
    consumer.handle_event(topic, payload)
    event_service.store_region_entry.assert_not_called()
    event_service.store_region_exit.assert_not_called()


def test_handle_event_service_exception_does_not_propagate(consumer, event_service):
    """Exceptions in event_service are caught and do not raise."""
    event_service.store_region_entry.side_effect = RuntimeError("Redis down")
    topic = "scenescape/event/region/scene-001/zone-b/objects"
    payload = {
        "timestamp": "2025-01-15T12:00:00Z",
        "name": "Zone B",
        "entered": [{"id": "person-2", "category": "person", "visibility": []}],
        "exited": [],
    }
    # Should not raise
    consumer.handle_event(topic, payload)
