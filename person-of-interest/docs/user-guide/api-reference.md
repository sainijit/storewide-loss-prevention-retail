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

Removes a POI, its FAISS embeddings, and associated metadata.

**Response** (200 OK):

```json
{
  "deleted": true,
  "poi_id": "poi-a3f2c1b0"
}
```

---

### Historical Search

#### Search by Image

```text
POST /api/v1/search
```

Upload a face image and find all appearances across cameras within a time range.

**Request** (multipart/form-data):

| Field        | Type   | Required | Description                              |
| ------------ | ------ | -------- | ---------------------------------------- |
| `image`      | File   | Yes      | Face image of person to search (JPEG/PNG) |
| `start_time` | string | Yes      | ISO 8601 timestamp (e.g., `2026-01-01T00:00:00Z`) |
| `end_time`   | string | Yes      | ISO 8601 timestamp                       |

**Response** (200 OK):

```json
{
  "query_embedding_dim": 256,
  "faiss_matches": 3,
  "events_found": 42,
  "timeline": [
    {
      "timestamp": "2026-01-15T14:30:00Z",
      "camera_id": "Camera_01",
      "region": "entrance-zone",
      "poi_id": "poi-a3f2c1b0",
      "thumbnail_path": "/api/v1/thumbnail/cam:Camera_01:5"
    }
  ],
  "region_dwells": [
    {
      "region_id": "entrance-zone",
      "region_name": "Main Entrance",
      "total_dwell_sec": 145.5,
      "visits": 3
    }
  ]
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
[
  {
    "id": "Camera_01",
    "name": "Entrance Camera"
  }
]
```

---

### Alerts

#### List Recent Alerts

```text
GET /api/v1/alerts
```

Returns the last 50 POI match alerts.

**Response** (200 OK):

```json
[
  {
    "alert_id": "alert-20260115-143012-poi-a3f2c1b0",
    "poi_id": "poi-a3f2c1b0",
    "severity": "high",
    "camera_id": "Camera_01",
    "confidence": 0.87,
    "timestamp": "2026-01-15T14:30:12Z",
    "thumbnail_path": "/api/v1/thumbnail/cam:Camera_01:5"
  }
]
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
  "status": "healthy",
  "faiss_vectors": 12,
  "mqtt_connected": true,
  "redis_connected": true
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
