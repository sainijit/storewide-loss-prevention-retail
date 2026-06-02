# Person of Interest (POI) Re-identification Overview

<!--hide_directive
<div class="component_card_widget">
  <a class="icon_github" href="https://github.com/sainijit/storewide-loss-prevention-retail/tree/main/person-of-interest">
     GitHub project
  </a>
  <a class="icon_document" href="https://github.com/sainijit/storewide-loss-prevention-retail/blob/main/person-of-interest/README.md">
     Readme
  </a>
</div>
hide_directive-->

The POI Re-identification system is a real-time retail loss-prevention application that
detects enrolled Persons of Interest (POIs) across multiple cameras and generates instant
security alerts. It also supports offline historical investigation to trace where a queried
person appeared across all cameras and time ranges.

## Overview

The **POI Re-identification** system leverages Intel® OpenVINO™ face detection and
re-identification models integrated with Intel® SceneScape spatial computing to deliver
real-time biometric person matching in multi-camera retail environments. By processing
256-dimensional face embeddings at the edge using FAISS vector search, the system enables
sub-second POI detection with minimal latency while maintaining data privacy — all biometric
processing stays local.

### Example Use Cases

- **Real-Time Suspect Detection:** Instantly alerts security personnel when an enrolled
  shoplifter or banned individual appears on any camera in the store.
- **Historical Investigation:** Enables loss-prevention analysts to upload a suspect's image
  and trace their movement across all cameras and time ranges, including region dwell times.
- **Multi-Camera Tracking:** Correlates person detections across multiple camera views using
  face re-identification embeddings for unified tracking.
- **Region-Based Analytics:** Tracks entry, exit, and dwell time per store zone (aisles,
  checkout, entrance) for behavioral analysis.

### Key Benefits

- **Edge-Optimized Inference:** All face detection and re-identification runs locally using
  Intel® OpenVINO™, ensuring data privacy and low latency.
- **Real-Time Alerting:** Sub-second alert pipeline from camera detection to security
  notification via WebSocket, MQTT, and webhook strategies.
- **Scalable Architecture:** Clean Architecture with microservices enables independent
  scaling of backend, UI, and alert service.
- **Flexible Deployment:** Docker Compose deployment with support for both local and
  registry-based image management.
- **SceneScape Integration:** Leverages Intel® SceneScape for spatial scene understanding,
  region tracking, and multi-camera calibration.

## How it Works

This section provides a high-level architecture view of the POI Re-identification system
and how it integrates with Intel® SceneScape and DLStreamer pipelines.

### System Architecture

```
┌───────────────────────────────────────────────────────────────────────────────┐
│                        Intel® SceneScape Platform                              │
│                                                                               │
│  ┌─────────────┐    ┌──────────────────────────────────────────┐              │
│  │  IP Cameras │───▶│ DLStreamer Pipeline Server                │              │
│  │  (RTSP)     │    │  ├─ person-detection-retail-0013         │              │
│  └─────────────┘    │  ├─ face-detection-retail-0004           │              │
│                     │  ├─ face-reidentification-retail-0095    │              │
│                     │  ├─ person-reidentification-retail-0277  │              │
│                     │  └─ gvatrack (short-term-imageless)      │              │
│                     └────────────────┬─────────────────────────┘              │
│                                      │ MQTT                                    │
│  ┌─────────────────┐                 │                                        │
│  │ Scene Controller │────────────────┼── scenescape/regulated/scene/+         │
│  │ (UUID tracking)  │                │                                        │
│  └─────────────────┘                 ├── scenescape/data/camera/+             │
│                                      │                                        │
│  ┌─────────────────┐                 │                                        │
│  │ MQTT Broker     │◀────────────────┘                                        │
│  │ (Mosquitto)     │                                                          │
│  └────────┬────────┘                                                          │
└───────────┼───────────────────────────────────────────────────────────────────┘
            │
            │ MQTT (TLS optional)
            ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│                         POI Re-identification System                           │
│                                                                               │
│  ┌──────────────────────────────────────────────────────────────────┐         │
│  │                    poi-backend (FastAPI, :8000)                    │         │
│  │                                                                    │         │
│  │  ┌─────────────────┐  ┌────────────────┐  ┌──────────────────┐   │         │
│  │  │ EventConsumer   │  │ MatchingService │  │ DetectionIndex   │   │         │
│  │  │ (MQTT → FAISS)  │──▶│ (Cache-Aside)  │  │ (offline search) │   │         │
│  │  └─────────────────┘  └───────┬────────┘  └────────┬─────────┘   │         │
│  │                               │                     │              │         │
│  │  ┌─────────────────┐  ┌──────▼─────────┐  ┌───────▼──────────┐   │         │
│  │  │ RegionConsumer  │  │ POI FAISS Index │  │ Detection FAISS  │   │         │
│  │  │ (zone tracking) │  │ (enrolled POIs) │  │ (all faces, 7d)  │   │         │
│  │  └─────────────────┘  └────────────────┘  └──────────────────┘   │         │
│  │                                                                    │         │
│  │  ┌─────────────────┐  ┌────────────────┐  ┌──────────────────┐   │         │
│  │  │ AlertService    │  │ OpenVINO       │  │ Search API       │   │         │
│  │  │ (observer, dedup│  │ (enrollment)   │  │ (offline query)  │   │         │
│  │  └────────┬────────┘  └────────────────┘  └──────────────────┘   │         │
│  └───────────┼────────────────────────────────────────────────────────┘         │
│              │ HTTP                                                             │
│  ┌───────────▼────────┐  ┌────────────────┐  ┌──────────────────┐             │
│  │ poi-alert-service  │  │ poi-redis      │  │ poi-ui (React)   │             │
│  │ (:8001)            │  │ (:6379)        │  │ (:3000)          │             │
│  │ WebSocket → UI     │  │ metadata/cache │  │ operator console │             │
│  └────────────────────┘  └────────────────┘  └──────────────────┘             │
└───────────────────────────────────────────────────────────────────────────────┘
```

### Data Flow: Online (Real-Time POI Detection)

```
Camera → DLStreamer → MQTT → EventConsumer → FAISS POI Search → AlertService → UI
```

1. DLStreamer processes camera frames at ~10 FPS, generating face embeddings (256-d).
2. The MQTT consumer extracts face embeddings from detection messages.
3. The MatchingService checks the Cache-Aside cache, then performs FAISS cosine search
   against enrolled POI embeddings.
4. On match (≥ threshold), an alert is dispatched via the Alert Service to the UI.

### Data Flow: Offline (Historical Search)

```
User uploads image → OpenVINO → Detection FAISS Search → Group by track → Return timeline
```

1. User uploads a face image via the Search API.
2. OpenVINO generates a 256-d query embedding (same model as DLStreamer).
3. The detection index (all faces seen in last 7 days) is searched.
4. Results are grouped by track/appearance, with entry and exit frames.
5. A timeline of appearances is returned, sorted by similarity.

### Key Components

- **POI Backend (FastAPI)**:
  The core application server handling POI enrollment, FAISS vector search, MQTT event
  consumption, alert generation, and REST API endpoints. Runs on port `8000`.

- **React UI**:
  A React + TypeScript single-page application providing the operator interface for
  POI enrollment, real-time alert monitoring, camera views, and historical search.
  Runs on port `3000`.

- **Redis**:
  In-memory data store for POI metadata, movement events, alert records, object-to-POI
  cache (Cache-Aside pattern), region presence tracking, and dwell time computation.

- **FAISS Vector Index**:
  Facebook AI Similarity Search index using `IndexFlatIP` on L2-normalized 256-dimensional
  vectors for cosine similarity matching. Provides sub-millisecond search across enrolled
  POI face embeddings.

- **Alert Service**:
  Dedicated microservice for alert fan-out — dispatches POI match alerts via logging,
  WebSocket (to UI), and MQTT channels. Runs on port `8001`.

- **Intel® SceneScape + DLStreamer**:
  Upstream inference pipeline providing person detection, face detection, and face
  re-identification via MQTT. DLStreamer runs the OpenVINO models; SceneScape provides
  spatial scene management, region tracking, and multi-camera coordination.

### Key Features

- **Feature 1**: Real-time POI face matching using FAISS cosine similarity on 256-d
  embeddings from `face-reidentification-retail-0095`.
- **Feature 2**: Historical search API — upload an image and get a timeline of where that
  person appeared across all cameras, with region dwell times and thumbnails.
- **Feature 3**: Multi-strategy alert delivery — WebSocket push to UI, MQTT publish, and
  webhook POST, with configurable dedup and suppression.
- **Feature 4**: Region entry/exit tracking with dwell time computation via SceneScape
  regulated scene events.

## Learn More

- [Get Started](./get-started.md): Follow step-by-step instructions to set up the application.
- [System Requirements](./get-started/system-requirements.md): Check the hardware and software requirements.
- [Build from Source](./get-started/build-from-source.md): How to build and deploy using Docker Compose.
- [How to Use the Application](./how-to-use-application.md): Explore the application's features and verify its functionality.
- [MQTT Pipeline Design](./mqtt-pipeline-design.md): Deep dive into the MQTT data flow and Redis data model.
- [API Reference](./api-reference.md): Comprehensive reference for the REST API endpoints.
- [Benchmarking](./benchmarking.md): Performance benchmarking and stream density testing.
- [Support and Troubleshooting](./troubleshooting.md): Find solutions to common issues.

<!--hide_directive
:::{toctree}
:hidden:

get-started
how-to-use-application
benchmarking
mqtt-pipeline-design
api-reference
troubleshooting
release-notes

:::
hide_directive-->
