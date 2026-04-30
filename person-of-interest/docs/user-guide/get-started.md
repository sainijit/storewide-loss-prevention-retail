# Get Started

## Overview

POI Re-identification is a real-time retail loss-prevention system that detects enrolled
Persons of Interest across multiple cameras using face re-identification and FAISS vector
search. This guide walks you through deploying and configuring the application.

## Prerequisites

### System Requirements

- System must meet [minimum requirements](./get-started/system-requirements.md).
- Intel® SceneScape must be deployed and running with DLStreamer pipelines configured.

The POI system operates alongside Intel® SceneScape in a distributed architecture:

| Service          | Port  | Purpose                                           |
| ---------------- | ----- | ------------------------------------------------- |
| POI Backend      | 8000  | REST API, MQTT consumer, FAISS matching            |
| POI UI           | 3000  | React operator interface                           |
| Redis            | 6379  | Metadata, events, cache                            |
| Alert Service    | 8001  | Alert fan-out (WebSocket, MQTT, log)               |
| MCP Server       | 9000  | AI tools for Claude Desktop (LLM, VLM, OpenVINO)  |
| SceneScape       | 443   | Spatial scene management + DLStreamer pipelines     |

### Software Dependencies

- **Docker**: [Installation Guide](https://docs.docker.com/get-docker/)
  - Must be configured to run without sudo ([Post-install guide](https://docs.docker.com/engine/install/linux-postinstall/))
- **Git**: [Installation Guide](https://git-scm.com/book/en/v2/Getting-Started-Installing-Git)
- **Make**: Required for build and deployment commands

### Required Services

Before setting up the POI system, ensure these services are running:

#### 1. Intel® SceneScape

SceneScape provides the upstream inference pipeline (DLStreamer) and spatial scene management:

- Person detection via `person-detection-retail-0013`
- Face detection via `face-detection-retail-0004`
- Face re-identification via `face-reidentification-retail-0095` (256-d embeddings)
- Region tracking via regulated scene events

Refer to the [SceneScape documentation](../../scenescape/README.md) for setup instructions.

#### 2. MQTT Broker

SceneScape's MQTT broker must be accessible from the POI backend. The default configuration
connects to the broker bundled with SceneScape.

## Quick Start

### Step 1: Clone the Repository

```bash
git clone https://github.com/sainijit/storewide-loss-prevention-retail.git
cd storewide-loss-prevention-retail/person-of-interest
```

### Step 2: Initialize Environment

```bash
# Create .env from the example template
make init-env
```

Edit `.env` with your SceneScape connection details:

```bash
# SceneScape MQTT connection
MQTT_HOST=<scenescape-mqtt-host>
MQTT_PORT=1883

# SceneScape API (for camera list)
SCENESCAPE_API_URL=https://<scenescape-host>
SCENESCAPE_API_TOKEN=<your-api-token>

# Proxy (if required)
HTTP_PROXY=<http-proxy>
HTTPS_PROXY=<https-proxy>
NO_PROXY=localhost,127.0.0.1
```

### Step 3: Build the Application

```bash
# Build POI backend and UI images locally
make build REGISTRY=false
```

### Step 4: Launch the Application

```bash
# Start all services
make up
```

This launches the following containers:

| Container            | Image                        | Port  |
| -------------------- | ---------------------------- | ----- |
| `poi-backend`        | `person-of-interest-poi-backend` | 8000  |
| `poi-ui`             | `person-of-interest-ui`      | 3000  |
| `poi-redis`          | `redis:8.6.2`                | 6379  |
| `poi-alert-service`  | `intel/alert-service:0.0.1`  | 8001  |
| `poi-mcp-server`     | `person-of-interest-mcp-server` | 9000  |

### Step 5: Access the Interface

Open your browser and navigate to:

```text
http://<host-ip>:3000
```

The POI Backend API is available at:

```text
http://<host-ip>:8000/docs
```

### Step 6: Stop Services

```bash
# Stop all services
make down
```

## Advanced Configuration

### Environment Variables

The complete list of environment variables is available in `.env.example`. Key configuration
groups:

| Variable                | Default                     | Description                           |
| ----------------------- | --------------------------- | ------------------------------------- |
| `MQTT_HOST`             | `broker.scenescape.intel.com` | SceneScape MQTT broker host          |
| `MQTT_PORT`             | `1883`                      | MQTT broker port                      |
| `SIMILARITY_THRESHOLD`  | `0.6`                       | FAISS cosine similarity threshold     |
| `SEARCH_TOP_K`          | `10`                        | Number of FAISS search results        |
| `OBJECT_CACHE_TTL`      | `300`                       | Cache-Aside TTL (seconds)             |
| `ALERT_DEDUP_TTL`       | `300`                       | Alert dedup window (seconds)          |
| `FAISS_DIMENSION`       | `256`                       | Embedding vector dimension            |
| `INFERENCE_DEVICE`      | `CPU`                       | OpenVINO inference device             |
| `LOG_LEVEL`             | `INFO`                      | Logging level                         |
| `BENCHMARK_LATENCY`     | `false`                     | Enable FAISS latency logging          |

### Running Tests and Generating Coverage Report

1. **Run Tests**

   ```bash
   make test
   ```

2. **Run Tests with Coverage**

   ```bash
   make coverage
   ```

3. **Generate HTML Coverage Report**

   ```bash
   make coverage-html
   ```

   Open `backend/htmlcov/index.html` in your browser to view the report.

### Custom Build Configuration

If using a container registry, set the registry URL before building:

```bash
export REGISTRY=docker.io/username
make build
```

See [Build from Source](./get-started/build-from-source.md) for detailed build options.

## Next Steps

1. **Explore Features**: Learn about application capabilities in the [How to Use Guide](./how-to-use-application.md)
2. **Troubleshooting**: If you encounter issues, check the [Troubleshooting Guide](./troubleshooting.md)
3. **MQTT Pipeline**: Understand the data flow in the [MQTT Pipeline Design](./mqtt-pipeline-design.md)

<!--hide_directive
:::{toctree}
:hidden:

./get-started/system-requirements
./get-started/build-from-source

:::
hide_directive-->
