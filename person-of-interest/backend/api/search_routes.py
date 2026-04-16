"""Search API routes — historical and real-time search."""

from __future__ import annotations

import logging
import time
from typing import Optional

import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

log = logging.getLogger("poi.api.search")

router = APIRouter(prefix="/search", tags=["Search"])

_matching_service = None
_event_service = None
_embedding_factory = None
_faiss_repo = None


def init(matching_service, event_service, embedding_factory, faiss_repo) -> None:
    global _matching_service, _event_service, _embedding_factory, _faiss_repo
    _matching_service = matching_service
    _event_service = event_service
    _embedding_factory = embedding_factory
    _faiss_repo = faiss_repo


@router.post("")
async def search_history(
    image: UploadFile = File(...),
    start_time: str = Form(""),
    end_time: str = Form(""),
):
    """Search for a person in the historical events by uploading an image.

    Returns regions, timestamps, and duration for all matches.
    """
    img_bytes = await image.read()
    if not img_bytes:
        raise HTTPException(400, "Image file is required")

    # Generate embedding from query image
    result = _embedding_factory.generate_from_bytes(img_bytes)
    if "error" in result:
        raise HTTPException(422, result["error"])

    query_vector = np.array(result["embedding"], dtype=np.float32)

    # Search FAISS for matching POI
    t0 = time.perf_counter()
    matches = _faiss_repo.search(query_vector, top_k=10)
    query_latency = (time.perf_counter() - t0) * 1000

    if not matches:
        return {
            "event_type": "poi_history_result",
            "poi_id": None,
            "query_range": {"start": start_time, "end": end_time},
            "visits": [],
            "total_visits": 0,
            "search_stats": {
                "vectors_searched": _faiss_repo.total_vectors(),
                "query_latency_ms": round(query_latency, 2),
            },
        }

    # Get best match's POI ID
    best_faiss_id, best_distance = matches[0]
    poi_id = _faiss_repo.get_poi_id_for_faiss_id(best_faiss_id)

    if not poi_id:
        return {
            "event_type": "poi_history_result",
            "poi_id": None,
            "visits": [],
            "total_visits": 0,
            "search_stats": {
                "vectors_searched": _faiss_repo.total_vectors(),
                "query_latency_ms": round(query_latency, 2),
            },
        }

    # Fetch historical events
    history = _event_service.search_history(poi_id, start_time or None, end_time or None)
    history["search_stats"]["vectors_searched"] = _faiss_repo.total_vectors()
    history["search_stats"]["query_latency_ms"] = round(query_latency, 2)
    history["query_range"] = {"start": start_time, "end": end_time}
    history["query_timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    return history
