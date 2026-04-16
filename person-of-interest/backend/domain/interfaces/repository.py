"""Repository interfaces (ports) for the domain layer."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import numpy as np

from backend.domain.entities.poi import POI
from backend.domain.entities.event import MovementEvent


class POIRepository(ABC):
    """Interface for POI metadata storage."""

    @abstractmethod
    def save(self, poi: POI) -> None: ...

    @abstractmethod
    def get(self, poi_id: str) -> Optional[POI]: ...

    @abstractmethod
    def list_all(self) -> list[POI]: ...

    @abstractmethod
    def delete(self, poi_id: str) -> bool: ...

    @abstractmethod
    def update_status(self, poi_id: str, status: str) -> None: ...


class EmbeddingRepository(ABC):
    """Interface for vector storage (FAISS)."""

    @abstractmethod
    def add(self, poi_id: str, vectors: list[np.ndarray]) -> list[int]: ...

    @abstractmethod
    def search(self, vector: np.ndarray, top_k: int = 5) -> list[tuple[int, float]]: ...

    @abstractmethod
    def remove(self, poi_id: str) -> None: ...

    @abstractmethod
    def get_poi_id_for_faiss_id(self, faiss_id: int) -> Optional[str]: ...

    @abstractmethod
    def save_to_disk(self) -> None: ...

    @abstractmethod
    def total_vectors(self) -> int: ...


class CacheRepository(ABC):
    """Interface for object_id → poi_id cache (Cache-Aside pattern)."""

    @abstractmethod
    def get_poi_for_object(self, object_id: str) -> Optional[str]: ...

    @abstractmethod
    def set_poi_for_object(self, object_id: str, poi_id: str, ttl: int = 300) -> None: ...


class EventRepository(ABC):
    """Interface for movement event storage."""

    @abstractmethod
    def store_event(self, event: MovementEvent) -> None: ...

    @abstractmethod
    def get_events_for_poi(
        self, poi_id: str, start_time: Optional[str] = None, end_time: Optional[str] = None
    ) -> list[dict]: ...

    @abstractmethod
    def get_recent_alerts(self, limit: int = 50) -> list[dict]: ...

    @abstractmethod
    def store_alert(self, alert: dict) -> None: ...

    @abstractmethod
    def is_alert_sent(self, object_id: str) -> bool: ...

    @abstractmethod
    def mark_alert_sent(self, object_id: str, ttl: int = 300) -> None: ...


class EmbeddingMappingRepository(ABC):
    """Interface for mapping FAISS internal IDs to POI IDs."""

    @abstractmethod
    def map_faiss_to_poi(self, faiss_id: int, poi_id: str) -> None: ...

    @abstractmethod
    def get_poi_for_faiss(self, faiss_id: int) -> Optional[str]: ...

    @abstractmethod
    def remove_mappings_for_poi(self, poi_id: str) -> None: ...
