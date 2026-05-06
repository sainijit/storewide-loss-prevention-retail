"""Thumbnail capture utility — persistent per-camera frame grabber + bbox crop.

Two capture strategies are supported per camera:

1. MQTT image topic (preferred when available):
   A background thread continuously sends "getimage" commands to the
   SceneScape DLStreamer adapter, which publishes annotated frames to
   scenescape/image/camera/{camera_id}.  Each image includes a 'timestamp'
   field matching the corresponding detection data on the camera data topic.
   Frames are cached in a timestamp-keyed ring buffer so that at match time
   we can retrieve the *exact* frame that produced the detection bounding
   boxes — eliminating frame-vs-bbox drift entirely.

2. RTSP grabber (fallback):
   A background thread continuously reads the RTSP stream and caches the
   latest frame.  Used for cameras that do not have publish_image configured.
"""

from __future__ import annotations

import base64
import collections
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
    """Subscribes to scenescape/image/camera/{camera_id} and caches frames
    in a timestamp-keyed ring buffer.

    A background polling thread continuously sends "getimage" commands to
    the DLStreamer adapter (via its existing MQTT command interface).  Each
    published image carries a 'timestamp' field identical to the timestamp
    in the data message produced by the same processFrame() call.

    At match time, ``get_frame_by_timestamp(ts)`` retrieves the exact frame
    that generated the detection bounding boxes, eliminating the wrong-person
    thumbnail problem caused by frame drift.

    No SceneScape code changes are required — this uses the standard
    ``getimage`` MQTT command that sscape_adapter already supports.
    """

    _BUFFER_SIZE = 60  # keep last N frames (~6s at 10fps)
    _POLL_INTERVAL = 0.08  # seconds between getimage commands (~12.5 req/s)

    def __init__(self, camera_id: str, mqtt_host: str, mqtt_port: int) -> None:
        import paho.mqtt.client as mqtt  # type: ignore[import]
        self._camera_id = camera_id
        self._host = mqtt_host
        self._port = mqtt_port
        self._frame_b64: Optional[str] = None
        self._frame_event = threading.Event()
        self._lock = threading.Lock()
        self._cond = threading.Condition(threading.Lock())
        # Ring buffer: timestamp_str -> base64 JPEG
        self._frame_buffer: collections.OrderedDict[str, str] = collections.OrderedDict()

        self._image_topic = f"scenescape/image/camera/{camera_id}"
        self._cmd_topic = f"scenescape/cmd/camera/{camera_id}"

        self._client = mqtt.Client(client_id=f"poi-thumbnail-{camera_id}")
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect

        self._connected = threading.Event()

        self._thread = threading.Thread(target=self._run, daemon=True, name=f"mqtt-img-{camera_id}")
        self._thread.start()

        # Background polling thread sends getimage continuously
        self._poll_thread = threading.Thread(
            target=self._poll_loop, daemon=True, name=f"mqtt-poll-{camera_id}",
        )
        self._poll_thread.start()

    def _run(self) -> None:
        while True:
            try:
                self._client.connect(self._host, self._port, keepalive=30)
                self._client.loop_forever()
            except Exception as exc:
                log.warning("MQTT image subscriber for camera=%s disconnected: %s", self._camera_id, exc)
                self._connected.clear()
            time.sleep(3)

    def _poll_loop(self) -> None:
        """Continuously send getimage commands so the adapter publishes
        a steady stream of timestamped frames into our ring buffer."""
        while True:
            if self._connected.is_set():
                self.request_frame()
            time.sleep(self._POLL_INTERVAL)

    def _on_connect(self, client, userdata, flags, rc) -> None:
        if rc == 0:
            client.subscribe(self._image_topic, qos=0)
            self._connected.set()
            log.info("MQTT image subscriber connected for camera=%s topic=%s", self._camera_id, self._image_topic)
        else:
            log.warning("MQTT image subscriber failed rc=%d camera=%s", rc, self._camera_id)

    def _on_disconnect(self, client, userdata, rc) -> None:
        self._connected.clear()
        log.debug("MQTT image subscriber disconnected rc=%d camera=%s", rc, self._camera_id)

    def _on_message(self, client, userdata, msg) -> None:
        try:
            import json as _json
            data = _json.loads(msg.payload)
            b64 = data.get("image")
            ts = data.get("timestamp", "")
            if b64:
                with self._lock:
                    self._frame_b64 = b64
                    if ts:
                        self._frame_buffer[ts] = b64
                        while len(self._frame_buffer) > self._BUFFER_SIZE:
                            self._frame_buffer.popitem(last=False)
                self._frame_event.set()
                with self._cond:
                    self._cond.notify_all()
                log.debug("MQTT image cached for camera=%s ts=%s (%d bytes)", self._camera_id, ts, len(b64))
        except Exception as exc:
            log.debug("MQTT image parse error camera=%s: %s", self._camera_id, exc)

    def request_frame(self) -> None:
        """Ask the DLStreamer adapter to publish a fresh frame now."""
        try:
            self._client.publish(self._cmd_topic, "getimage", qos=0)
        except Exception:
            pass

    def request_frame_and_wait(self, timeout: float = 3.0) -> Optional[str]:
        """Send a getimage command and block until a new frame arrives.

        Used by offline search to grab a frame on demand rather than
        relying on the continuous polling buffer.
        """
        with self._cond:
            self.request_frame()
            self._cond.wait(timeout=timeout)
        with self._lock:
            return self._frame_b64

    def get_latest_b64(self, wait_timeout: float = 2.0) -> Optional[str]:
        """Return the latest base64 JPEG, waiting if needed."""
        with self._lock:
            if self._frame_b64:
                return self._frame_b64
        self._frame_event.wait(timeout=wait_timeout)
        with self._lock:
            return self._frame_b64

    def get_b64_by_timestamp(self, timestamp: str) -> Optional[str]:
        """Return the base64 JPEG for an exact timestamp match, or None."""
        with self._lock:
            return self._frame_buffer.get(timestamp)

    def _get_nearest_b64(self, timestamp: str) -> Optional[str]:
        """Return the base64 JPEG whose timestamp is closest to *timestamp*.

        Parses ISO-8601 timestamps and picks the frame with the smallest
        absolute time delta.  Returns None only when the buffer is empty.
        """
        from datetime import datetime

        def _parse_ts(ts: str) -> Optional[float]:
            for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
                try:
                    return datetime.strptime(ts, fmt).timestamp()
                except ValueError:
                    continue
            return None

        target = _parse_ts(timestamp)
        if target is None:
            return None

        with self._lock:
            if not self._frame_buffer:
                return None
            best_key: Optional[str] = None
            best_delta = float("inf")
            for key in self._frame_buffer:
                t = _parse_ts(key)
                if t is None:
                    continue
                delta = abs(t - target)
                if delta < best_delta:
                    best_delta = delta
                    best_key = key
            if best_key is not None:
                log.info(
                    "Nearest-timestamp frame: camera=%s requested=%s matched=%s delta=%.3fs",
                    self._camera_id, timestamp, best_key, best_delta,
                )
                return self._frame_buffer[best_key]
            return None

    def get_frame_by_timestamp(self, timestamp: str) -> Optional[np.ndarray]:
        """Return the frame matching a detection timestamp.

        Lookup order:
        1. Exact timestamp match (same frame that produced the detection).
        2. Nearest timestamp in the ring buffer (closest frame available).
        3. Latest cached frame (last resort).
        """
        b64 = self.get_b64_by_timestamp(timestamp)
        if b64:
            log.info("Timestamp-matched frame: camera=%s ts=%s (buf=%d)", self._camera_id, timestamp, len(self._frame_buffer))
            return self._decode_b64(b64)

        b64 = self._get_nearest_b64(timestamp)
        if b64:
            return self._decode_b64(b64)

        log.warning("No frames in buffer camera=%s ts=%s — using latest", self._camera_id, timestamp, )
        return self.get_latest_frame(wait_timeout=0.5)

    def get_latest_frame(self, wait_timeout: float = 2.0) -> Optional[np.ndarray]:
        """Decode and return the latest frame as a numpy array."""
        return self._decode_b64(self.get_latest_b64(wait_timeout))

    @staticmethod
    def _decode_b64(b64: Optional[str]) -> Optional[np.ndarray]:
        if b64 is None:
            return None
        try:
            raw = base64.b64decode(b64)
            buf = np.frombuffer(raw, dtype=np.uint8)
            return cv2.imdecode(buf, cv2.IMREAD_COLOR)
        except Exception:
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


def capture_thumbnail(camera_id: str, bbox: Optional[dict], timestamp: str = "") -> Optional[str]:
    """Return a base64 JPEG thumbnail for camera_id cropped to bbox.

    When a timestamp is provided and the camera uses MQTT image publishing,
    looks up the exact frame from the timestamp-keyed ring buffer — this
    gives a frame perfectly synchronised with the detection bounding box.

    Falls back to the latest cached MQTT frame or the persistent RTSP grabber.
    """
    if use_mqtt_image(camera_id):
        sub = _get_mqtt_subscriber(camera_id)
        if timestamp:
            frame = sub.get_frame_by_timestamp(timestamp)
        else:
            frame = sub.get_latest_frame(wait_timeout=3.0)
        if frame is None:
            log.warning("No MQTT image received for camera=%s — falling back to RTSP", camera_id)
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


def submit_capture(camera_id: str, bbox: Optional[dict], timestamp: str = ""):
    """Submit a thumbnail capture to the shared thread pool. Returns a Future."""
    return _executor.submit(capture_thumbnail, camera_id, bbox, timestamp)


def prewarm_grabbers(camera_ids: list[str]) -> None:
    """Start persistent grabbers and MQTT image subscribers for all cameras
    immediately, so they are ready before the first match event."""
    for cam in camera_ids:
        _get_grabber(cam)
        if use_mqtt_image(cam):
            _get_mqtt_subscriber(cam)
            log.info("Pre-warming MQTT image subscriber for camera=%s (continuous polling)", cam)
