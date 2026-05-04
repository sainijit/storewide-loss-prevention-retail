# API Reference

**Version: 1.0.0**

## Base URL

```text
http://<host-ip>:8000/api/v1
```

## Endpoints

### POI Management

#### Create POI

```text
POST /api/v1/poi
```

Enroll a new Person of Interest by uploading 1–5 face images.

**Request** (multipart/form-data):

| Field         | Type           | Required | Description                          |
| ------------- | -------------- | -------- | ------------------------------------ |
| `images`      | File[]         | Yes      | 1–5 face images (JPEG/PNG)           |
| `severity`    | string         | No       | `low`, `medium` (default), or `high` |
| `description` | string         | No       | Free-text notes about the suspect    |

**Response** (201 Created):

```json
{
  "poi_id": "poi-a3f2c1b0",
  "severity": "high",
  "notes": "Shoplifting suspect",
  "reference_images": [
    {
      "embedding_id": "emb-0001",
      "vector_dim": 256
    }
  ],
  "status": "active",
  "created_at": "2026-01-15T12:00:00Z"
}
```

#### List POIs

```text
GET /api/v1/poi
```

Returns all enrolled POIs sorted by creation date (newest first).

**Response** (200 OK):

```json
[
  {
    "poi_id": "poi-a3f2c1b0",
    "severity": "high",
    "notes": "Shoplifting suspect",
    "status": "active",
    "created_at": "2026-01-15T12:00:00Z"
  }
]
```

#### Get POI

```text
GET /api/v1/poi/{poi_id}
```

Returns details for a single POI.

#### Delete POI

```text
DELETE /api/v1/poi/{poi_id}
```

Removes a POI, its FAISS embeddings, and associated metadata. Redis metadata is deleted
first (authoritative source), then FAISS vectors, then embedding mappings.

**Response** (200 OK):

```json
{
  "status": "deleted",
  "poi_id": "poi-a3f2c1b0"
}
```

---

### Historical Search

#### Search by Image

```text
POST /api/v1/search
```

Upload a face image and find all appearances across cameras within a time range. The
backend generates a 256-d face embedding from the query image, searches FAISS for matching
POIs, and returns a timeline of visits grouped by date with region dwell information.

**Request** (multipart/form-data):

| Field        | Type   | Required | Description                              |
| ------------ | ------ | -------- | ---------------------------------------- |
| `image`      | File   | Yes      | Face image of person to search (JPEG/PNG) |
| `start_time` | string | No       | ISO 8601 timestamp (e.g., `2026-01-01T00:00:00Z`) |
| `end_time`   | string | No       | ISO 8601 timestamp                       |

**Response** (200 OK):

```json
{
  "event_type": "poi_history_result",
  "poi_id": "poi-a3f2c1b0",
  "query_range": {
    "start": "2026-01-01T00:00:00Z",
    "end": "2026-12-31T23:59:59Z"
  },
  "visits": [
    {
      "date": "2026-01-15",
      "entry_time": "2026-01-15T14:30:00Z",
      "exit_time": "2026-01-15T14:35:00Z",
      "cameras_visited": ["Camera_01"],
      "regions": ["entrance-zone"],
      "region_name": "entrance-zone",
      "duration_sec": 300.0,
      "region_dwells": [
        {
          "region_name": "entrance-zone",
          "entry_time": "2026-01-15T14:30:00Z",
          "exit_time": "2026-01-15T14:35:00Z",
          "dwell_sec": 300.0,
          "camera_id": "Camera_01"
        }
      ],
      "thumbnail": "/api/v1/thumbnail/cam:Camera_01:5",
      "alert_id": ""
    }
  ],
  "total_visits": 1,
  "search_stats": {
    "vectors_searched": 12,
    "query_latency_ms": 1.23
  },
  "query_timestamp": "2026-01-20T10:00:00Z"
}
```

---

### Camera Management

#### List Cameras

```text
GET /api/v1/cameras
```

Returns available cameras from SceneScape.

**Response** (200 OK):

```json
{
  "cameras": [
    {
      "id": "Camera_01",
      "name": "Entrance Camera"
    }
  ],
  "count": 1
}
```

#### Get Camera

```text
GET /api/v1/cameras/{camera_id}
```

Returns details for a single camera from SceneScape.

---

### Alerts

#### List Recent Alerts

```text
GET /api/v1/alerts
```

Returns the last 50 POI match alerts. Each alert contains nested `match` and `poi_metadata`
objects.

**Response** (200 OK):

```json
[
  {
    "event_type": "poi_match_alert",
    "alert_id": "alert-20260115-143012-poi-a3f2c1b0",
    "poi_id": "poi-a3f2c1b0",
    "severity": "high",
    "timestamp": "2026-01-15T14:30:12Z",
    "status": "New",
    "match": {
      "camera_id": "Camera_01",
      "confidence": 0.91,
      "similarity_score": 0.87,
      "bbox": [200, 150, 280, 380],
      "frame_number": 0,
      "thumbnail_path": "/api/v1/thumbnail/cam:Camera_01:5"
    },
    "poi_metadata": {
      "notes": "Shoplifting suspect",
      "enrollment_date": "2026-01-10T08:00:00Z",
      "total_previous_matches": 3
    }
  }
]
```

#### Clear Alerts

```text
DELETE /api/v1/alerts
```

Deletes all alert records and the recent-alerts list.

**Response** (200 OK):

```json
{
  "deleted_count": 5
}
```

---

### System Status

#### Health Check

```text
GET /api/v1/status
```

Returns system health including FAISS vector count and MQTT connection state.

**Response** (200 OK):

```json
{
  "status": "running",
  "faiss_vectors": 12,
  "mqtt_connected": true
}
```

---

### Thumbnails

#### Get Thumbnail

```text
GET /api/v1/thumbnail/{object_id}
```

Serves a captured JPEG thumbnail for a detected object.

**Response** (200 OK): JPEG image binary
