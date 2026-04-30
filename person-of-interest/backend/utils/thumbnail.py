"""Thumbnail capture utility — persistent per-camera frame grabber + bbox crop.

Two capture strategies are supported per camera:

1. MQTT image topic (preferred when available):
   SceneScape DLStreamer adapter publishes annotated frames on demand to
   scenescape/image/camera/{camera_id} when a "getimage" command is sent.
   We subscribe to that topic, cache the latest received frame, and also
   proactively request a fresh frame at match time.  This eliminates RTSP
   timing drift entirely because the image comes from the same pipeline that
   produced the detection bounding boxes.

2. RTSP grabber (fallback):
   A background thread continuously reads the RTSP stream and caches the
   latest frame.  Used for cameras that do not have publish_image configured.
"""

from __future__ import annotations

import base64
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import cv2
import numpy as np

log = logging.getLogger("poi.thumbnail")

# RTSP base URL pattern; override via RTSP_BASE_URL env var
_RTSP_BASE_URL = os.getenv("RTSP_BASE_URL", "rtsp://mediaserver:8554")

# MQTT broker for SceneScape image topic (same broker used by the MQTT consumer)
_MQTT_HOST = os.getenv("MQTT_HOST", "broker.scenescape.intel.com")
_MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

# Shared thread pool for async capture submissions
_executor = ThreadPoolExecutor(max_workers=16, thread_name_prefix="thumbnail")


def build_rtsp_url(camera_id: str) -> str:
    return f"{_RTSP_BASE_URL.rstrip('/')}/{camera_id}"


# ---------------------------------------------------------------------------
# MQTT image subscriber (preferred source — same frame as detection)
# ---------------------------------------------------------------------------

class _MqttImageSubscriber:
    """Subscribes to scenescape/image/camera/{camera_id} and caches the latest
    base64 JPEG frame published by DLStreamer sscape_adapter.

    Also publishes "getimage" to the pipeline control topic on demand so the
    adapter sends a fresh frame at exactly the right moment.
    """

    def __init__(self, camera_id: str, mqtt_host: str, mqtt_port: int) -> None:
        import paho.mqtt.client as mqtt  # type: ignore[import]
        self._camera_id = camera_id
        self._host = mqtt_host
        self._port = mqtt_port
        self._frame_b64: Optional[str] = None
        self._frame_event = threading.Event()
        self._lock = threading.Lock()

        self._image_topic = f"scenescape/image/camera/{camera_id}"
        # sscape_adapter listens on scenescape/cmd/camera/{cameraid} for "getimage"
        self._cmd_topic = f"scenescape/cmd/camera/{camera_id}"

        self._client = mqtt.Client(client_id=f"poi-thumbnail-{camera_id}")
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect

        self._thread = threading.Thread(target=self._run, daemon=True, name=f"mqtt-img-{camera_id}")
        self._thread.start()

    def _run(self) -> None:
        while True:
            try:
                self._client.connect(self._host, self._port, keepalive=30)
                self._client.loop_forever()
            except Exception as exc:
                log.warning("MQTT image subscriber for camera=%s disconnected: %s", self._camera_id, exc)
            time.sleep(3)

    def _on_connect(self, client, userdata, flags, rc) -> None:
        if rc == 0:
            client.subscribe(self._image_topic, qos=0)
            log.info("MQTT image subscriber connected for camera=%s topic=%s", self._camera_id, self._image_topic)
        else:
            log.warning("MQTT image subscriber failed rc=%d camera=%s", rc, self._camera_id)

    def _on_disconnect(self, client, userdata, rc) -> None:
        log.debug("MQTT image subscriber disconnected rc=%d camera=%s", rc, self._camera_id)

    def _on_message(self, client, userdata, msg) -> None:
        try:
            import json as _json
            data = _json.loads(msg.payload)
            b64 = data.get("image")
            if b64:
                with self._lock:
                    self._frame_b64 = b64
                self._frame_event.set()
                log.debug("MQTT image received for camera=%s (%d bytes)", self._camera_id, len(b64))
        except Exception as exc:
            log.debug("MQTT image parse error camera=%s: %s", self._camera_id, exc)

    def request_frame(self) -> None:
        """Ask the DLStreamer adapter to publish a fresh frame now."""
        try:
            self._client.publish(self._cmd_topic, "getimage", qos=0)
            log.debug("Sent getimage request for camera=%s", self._camera_id)
        except Exception as exc:
            log.debug("Failed to send getimage for camera=%s: %s", self._camera_id, exc)

    def get_latest_b64(self, wait_timeout: float = 2.0) -> Optional[str]:
        """Return the latest base64 JPEG. Waits up to wait_timeout seconds for
        the first frame if none cached yet."""
        with self._lock:
            if self._frame_b64:
                return self._frame_b64
        # Wait for a frame to arrive
        self._frame_event.wait(timeout=wait_timeout)
        with self._lock:
            return self._frame_b64

    def get_latest_frame(self, wait_timeout: float = 2.0) -> Optional[np.ndarray]:
        """Decode and return the latest frame as a numpy array."""
        b64 = self.get_latest_b64(wait_timeout)
        if b64 is None:
            return None
        try:
            raw = base64.b64decode(b64)
            buf = np.frombuffer(raw, dtype=np.uint8)
            frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)
            return frame
        except Exception as exc:
            log.debug("MQTT image decode error camera=%s: %s", self._camera_id, exc)
            return None


# Registry: camera_id -> _MqttImageSubscriber
_mqtt_subscribers: dict[str, _MqttImageSubscriber] = {}
_mqtt_sub_lock = threading.Lock()


def _get_mqtt_subscriber(camera_id: str) -> _MqttImageSubscriber:
    with _mqtt_sub_lock:
        if camera_id not in _mqtt_subscribers:
            sub = _MqttImageSubscriber(camera_id, _MQTT_HOST, _MQTT_PORT)
            _mqtt_subscribers[camera_id] = sub
        return _mqtt_subscribers[camera_id]


# Set of camera IDs that have MQTT image publishing enabled
# Populated by prewarm_grabbers via RTSP_PREWARM_CAMERAS; overridden by
# MQTT_IMAGE_CAMERAS env var (comma-separated list)
_mqtt_image_cameras: set[str] = set(
    c.strip() for c in os.getenv("MQTT_IMAGE_CAMERAS", "").split(",") if c.strip()
)


def use_mqtt_image(camera_id: str) -> bool:
    """Return True if this camera should use MQTT image topic instead of RTSP."""
    return camera_id in _mqtt_image_cameras




class _FrameGrabber:
    """Background thread that continuously reads an RTSP stream and caches the
    latest frame. Reconnects automatically on stream errors."""

    _RECONNECT_DELAY = 2.0  # seconds between reconnect attempts

    def __init__(self, rtsp_url: str) -> None:
        self._url = rtsp_url
        self._frame: Optional[np.ndarray] = None
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._read_loop, daemon=True, name=f"grabber-{rtsp_url}")
        self._thread.start()

    def get_latest(self) -> Optional[np.ndarray]:
        """Return a copy of the most recently captured frame, or None."""
        with self._lock:
            return self._frame.copy() if self._frame is not None else None

    def _read_loop(self) -> None:
        while True:
            cap = cv2.VideoCapture(self._url, cv2.CAP_FFMPEG)
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)
            cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            connected = cap.isOpened()
            if not connected:
                cap.release()
                time.sleep(self._RECONNECT_DELAY)
                continue

            while True:
                ret, frame = cap.read()
                if not ret:
                    break  # stream error — reconnect
                with self._lock:
                    self._frame = frame

            cap.release()
            time.sleep(self._RECONNECT_DELAY)


# Registry: camera_id -> _FrameGrabber
_grabbers: dict[str, _FrameGrabber] = {}
_grabbers_lock = threading.Lock()


def _get_grabber(camera_id: str) -> _FrameGrabber:
    with _grabbers_lock:
        if camera_id not in _grabbers:
            url = build_rtsp_url(camera_id)
            log.info("Starting persistent RTSP grabber for camera=%s url=%s", camera_id, url)
            _grabbers[camera_id] = _FrameGrabber(url)
        return _grabbers[camera_id]


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def crop_bbox(frame: np.ndarray, bbox: dict, padding: int = 10) -> Optional[np.ndarray]:
    """Crop a region from frame using {x, y, width, height} top-left bbox dict."""
    h, w = frame.shape[:2]
    x1 = max(0, int(bbox.get("x", 0)) - padding)
    y1 = max(0, int(bbox.get("y", 0)) - padding)
    x2 = min(w, int(bbox.get("x", 0)) + int(bbox.get("width", 0)) + padding)
    y2 = min(h, int(bbox.get("y", 0)) + int(bbox.get("height", 0)) + padding)
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
    """Return a base64 JPEG thumbnail for camera_id cropped to bbox.

    If the camera is configured for MQTT image publishing (MQTT_IMAGE_CAMERAS),
    requests a fresh frame from the DLStreamer pipeline and waits for it — this
    gives a frame that is perfectly synchronised with the detection event.

    Falls back to the persistent RTSP grabber for cameras without MQTT image.
    """
    if use_mqtt_image(camera_id):
        sub = _get_mqtt_subscriber(camera_id)
        # Request a fresh frame from the pipeline, then wait briefly for delivery
        sub.request_frame()
        frame = sub.get_latest_frame(wait_timeout=3.0)
        if frame is None:
            log.warning("No MQTT image received for camera=%s — falling back to RTSP", camera_id)
            # Fall through to RTSP
        else:
            if bbox:
                crop = crop_bbox(frame, bbox)
                if crop is None or crop.size == 0:
                    log.debug("Bbox crop failed for camera=%s, using full frame", camera_id)
                    crop = frame
            else:
                crop = frame
            b64 = frame_to_base64_jpeg(crop)
            if b64:
                return b64
            log.warning("Failed to encode MQTT thumbnail for camera=%s", camera_id)

    # RTSP fallback
    grabber = _get_grabber(camera_id)
    frame = grabber.get_latest()
    if frame is None:
        log.warning("No cached frame yet for camera=%s — grabber may still be connecting", camera_id)
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


def prewarm_grabbers(camera_ids: list[str]) -> None:
    """Start persistent grabbers and MQTT image subscribers for all cameras
    immediately, so they are ready before the first match event."""
    for cam in camera_ids:
        _get_grabber(cam)
        if use_mqtt_image(cam):
            sub = _get_mqtt_subscriber(cam)
            # Request an initial frame so the cache is warm before first match
            sub.request_frame()
            log.info("Pre-warming MQTT image subscriber for camera=%s", cam)
