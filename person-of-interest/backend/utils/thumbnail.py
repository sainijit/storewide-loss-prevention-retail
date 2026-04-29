"""Thumbnail capture utility — grabs RTSP frame, crops bounding box, encodes JPEG."""

from __future__ import annotations

import base64
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import cv2
import numpy as np

log = logging.getLogger("poi.thumbnail")

# Shared bounded thread pool — prevents unbounded RTSP grabs under heavy load
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="thumbnail")

# RTSP base URL pattern; override via RTSP_BASE_URL env var
_RTSP_BASE_URL = os.getenv("RTSP_BASE_URL", "rtsp://mediaserver:8554")


def build_rtsp_url(camera_id: str) -> str:
    return f"{_RTSP_BASE_URL.rstrip('/')}/{camera_id}"


def grab_frame_rtsp(rtsp_url: str, timeout_ms: int = 5000) -> Optional[np.ndarray]:
    """Open RTSP stream, flush buffer, read a current frame, and release."""
    cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
    cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, timeout_ms)
    cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, timeout_ms)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    try:
        # Flush the RTSP decoder buffer by reading several frames.
        # Opening a fresh connection returns a buffered keyframe that can be
        # several seconds old; discarding the first few reads gives a current frame.
        frame = None
        for _ in range(8):
            ret, f = cap.read()
            if ret:
                frame = f
        return frame
    except Exception:
        log.debug("Exception reading RTSP frame from %s", rtsp_url)
        return None
    finally:
        cap.release()


def crop_bbox(frame: np.ndarray, bbox: dict, padding: int = 10) -> Optional[np.ndarray]:
    """Crop a region from frame using {x, y, width, height} top-left bbox dict."""
    h, w = frame.shape[:2]
    x1 = max(0, int(bbox["x"]) - padding)
    y1 = max(0, int(bbox["y"]) - padding)
    x2 = min(w, int(bbox["x"]) + int(bbox["width"]) + padding)
    y2 = min(h, int(bbox["y"]) + int(bbox["height"]) + padding)
    if x2 <= x1 or y2 <= y1:
        return None
    return frame[y1:y2, x1:x2]


def frame_to_base64_jpeg(image: np.ndarray, quality: int = 80) -> Optional[str]:
    """Encode a numpy image to a base64 JPEG string."""
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        return None
    return base64.b64encode(buf.tobytes()).decode("ascii")


def capture_thumbnail(camera_id: str, bbox: Optional[dict]) -> Optional[str]:
    """Grab RTSP frame for camera, crop bbox, return base64 JPEG string.

    Returns None on any failure — caller should fall back gracefully.
    """
    rtsp_url = build_rtsp_url(camera_id)
    frame = grab_frame_rtsp(rtsp_url)
    if frame is None:
        log.warning("Failed to grab RTSP frame for camera=%s url=%s", camera_id, rtsp_url)
        return None

    if bbox:
        crop = crop_bbox(frame, bbox)
        if crop is None or crop.size == 0:
            log.debug("Bbox crop failed for camera=%s bbox=%s, using full frame", camera_id, bbox)
            crop = frame
    else:
        crop = frame

    b64 = frame_to_base64_jpeg(crop)
    if b64 is None:
        log.warning("Failed to encode thumbnail for camera=%s", camera_id)
    return b64


def submit_capture(camera_id: str, bbox: Optional[dict]):
    """Submit a thumbnail capture to the shared thread pool. Returns a Future."""
    return _executor.submit(capture_thumbnail, camera_id, bbox)
