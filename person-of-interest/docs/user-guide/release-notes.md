# Release Notes

- [Version 1.0.0](#version-100)

## Current Release

### Version 1.0.0

**Release Date**: April 2026

**Features**:

- Real-time POI face matching using FAISS cosine similarity on 256-d embeddings from
  `face-reidentification-retail-0095`
- POI enrollment via REST API with automatic face detection and embedding generation
  using Intel® OpenVINO™
- Historical search API — upload an image and get a timeline of appearances across all
  cameras, with region dwell times and thumbnails
- Multi-strategy alert delivery — WebSocket (to UI), MQTT publish, webhook POST, and
  logging, with configurable dedup and suppression
- React + TypeScript UI for POI management, real-time alert monitoring, and historical
  investigation
- Cache-Aside pattern for object-to-POI mapping — avoids repeated FAISS searches for the
  same tracked person
- Region entry/exit tracking with dwell time computation via Intel® SceneScape regulated
  scene events
- MCP server with LLM, VLM, OpenVINO, Docker, Redis, and POI data tools for Claude Desktop
  integration
- Docker Compose deployment with five services: backend, UI, Redis, alert service, and
  MCP server
- Full test suite with 110 passing tests covering matching, alerting, MQTT consumption,
  region tracking, and enrollment

**OpenVINO™ Models Used**:

| Model                                | Purpose                | Output               |
| ------------------------------------ | ---------------------- | -------------------- |
| `face-detection-retail-0004`         | Face detection         | Face bounding boxes  |
| `face-reidentification-retail-0095`  | Face re-identification | 256-d float32 vector |

**HW Used for Validation**:

- Intel® Xeon® Scalable Processor (4th Generation)
- Ubuntu 22.04 LTS

**Known Issues/Limitations**:

- FAISS uses `IndexFlatIP` (exact search) — for very large POI galleries (10,000+ embeddings),
  consider switching to `IndexIVFFlat` for approximate nearest neighbor search.
- Thumbnail capture depends on RTSP stream availability from the camera; if RTSP is not
  configured, thumbnails may be empty.
- The MCP server AI tools (LLM/VLM) require a separately deployed inference endpoint
  (e.g., Ollama, vLLM) — they are not included in the default deployment.
- SceneScape integration is required for region tracking and dwell time features; without
  SceneScape, only per-camera tracking is available.
- Alert dedup window is per `(object_id, poi_id)` pair — a different POI match for the same
  person will generate a new alert immediately.
