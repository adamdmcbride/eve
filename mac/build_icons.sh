#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_DIR="${ROOT_DIR}/mac/generated"
ICONSET_DIR="${BUILD_DIR}/Eve.iconset"
MASTER_PNG="${BUILD_DIR}/eve-icon-1024.png"
ICNS_PATH="${BUILD_DIR}/eve.icns"
GENERATOR_BIN="${BUILD_DIR}/eve-icon-generator"

mkdir -p "${BUILD_DIR}"
rm -rf "${ICONSET_DIR}"
mkdir -p "${ICONSET_DIR}"

swiftc -O -framework AppKit "${ROOT_DIR}/mac/generate_eve_icon.swift" -o "${GENERATOR_BIN}"
"${GENERATOR_BIN}" "${MASTER_PNG}"

for size in 16 32 128 256 512; do
  double_size=$((size * 2))
  sips -z "${size}" "${size}" "${MASTER_PNG}" --out "${ICONSET_DIR}/icon_${size}x${size}.png" >/dev/null
  sips -z "${double_size}" "${double_size}" "${MASTER_PNG}" --out "${ICONSET_DIR}/icon_${size}x${size}@2x.png" >/dev/null
done

iconutil -c icns "${ICONSET_DIR}" -o "${ICNS_PATH}"
echo "${ICNS_PATH}"
