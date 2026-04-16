"""Match result domain entity."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class MatchResult:
    poi_id: str
    similarity_score: float
    faiss_distance: float
    embedding_id: Optional[str] = None

    @property
    def is_match(self) -> bool:
        return self.similarity_score > 0


@dataclass
class AlertPayload:
    alert_id: str
    poi_id: str
    severity: str
    timestamp: str
    match: dict
    poi_metadata: dict
    status: str = "New"

    def to_dict(self) -> dict:
        return {
            "event_type": "poi_match_alert",
            "timestamp": self.timestamp,
            "alert_id": self.alert_id,
            "poi_id": self.poi_id,
            "severity": self.severity,
            "match": self.match,
            "poi_metadata": self.poi_metadata,
            "status": self.status,
        }
