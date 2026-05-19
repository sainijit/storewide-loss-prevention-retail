#!/bin/bash
# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
#
# Download sample video from CAMERA_URL defined in configs/.env.example

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "${SCRIPT_DIR}")"
SAMPLE_DATA_DIR="${PROJECT_ROOT}/../scenescape/sample_data"
ZONE_CONFIG="${PROJECT_ROOT}/configs/zone_config.json"

# Load video_url and video_file from zone_config.json
if [ ! -f "${ZONE_CONFIG}" ]; then
    echo "ERROR: zone_config.json not found at ${ZONE_CONFIG}"
    exit 1
fi

CAMERA_URL=$(python3 -c "import json; print(json.load(open('${ZONE_CONFIG}')).get('video_url', ''))" 2>/dev/null)
FILENAME=$(python3 -c "import json; print(json.load(open('${ZONE_CONFIG}')).get('video_file', ''))" 2>/dev/null)

if [ -z "${CAMERA_URL}" ]; then
    echo "ERROR: video_url not found in ${ZONE_CONFIG}"
    exit 1
fi

if [ -z "${FILENAME}" ]; then
    echo "ERROR: video_file not found in ${ZONE_CONFIG}"
    exit 1
fi

echo "=========================================="
echo "Sample Video Download"
echo "=========================================="
echo "  URL:         ${CAMERA_URL}"
echo "  Destination: ${SAMPLE_DATA_DIR}"
echo ""

mkdir -p "${SAMPLE_DATA_DIR}"

OUTPUT_PATH="${SAMPLE_DATA_DIR}/${FILENAME}"

if [ -f "${OUTPUT_PATH}" ]; then
    echo "  ✓ Video already exists: ${OUTPUT_PATH}"
    exit 0
fi

echo "  Downloading ${FILENAME}..."
wget -q --show-progress -O "${OUTPUT_PATH}" "${CAMERA_URL}"

if [ -f "${OUTPUT_PATH}" ] && [ -s "${OUTPUT_PATH}" ]; then
    FILE_SIZE=$(du -h "${OUTPUT_PATH}" | cut -f1)
    echo "  ✓ Download complete: ${OUTPUT_PATH} (${FILE_SIZE})"
else
    echo "  ✗ Download failed"
    rm -f "${OUTPUT_PATH}"
    exit 1
fi
