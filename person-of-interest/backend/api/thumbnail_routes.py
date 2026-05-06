"""Thumbnail API — serves RTSP-captured face crops stored in Redis."""

from __future__ import annotations

import base64
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

log = logging.getLogger("poi.api.thumbnail")

router = APIRouter()
_event_repo = None


def init(event_repo) -> None:
    global _event_repo
    _event_repo = event_repo


@router.get("/thumbnail/{object_id:path}", response_class=Response)
def get_thumbnail(object_id: str):
    """Return the captured face crop for a tracked person or alert as JPEG.

    Accepts either an object_id (``cam:Camera_01:1``) or an alert_id
    (``alert-20260506-...``).  Both are stored under ``thumbnail:{key}``
    in Redis.
    """
    if _event_repo is None:
        raise HTTPException(status_code=503, detail="Thumbnail service not ready")

    b64 = _event_repo.get_thumbnail(object_id)
    if not b64:
        raise HTTPException(status_code=404, detail="Thumbnail not found or expired")

    try:
        image_bytes = base64.b64decode(b64)
    except Exception:
        raise HTTPException(status_code=500, detail="Thumbnail data corrupt")

    return Response(content=image_bytes, media_type="image/jpeg")
