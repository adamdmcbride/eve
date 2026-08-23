#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="${HOME}/Applications"
APP_NAME="Eve Monitor"
BUNDLE_ID="${EVE_MONITOR_BUNDLE_ID:-local.eve.monitor}"
APP_PATH="${APP_DIR}/${APP_NAME}.app"
CONTENTS_DIR="${APP_PATH}/Contents"
MACOS_DIR="${CONTENTS_DIR}/MacOS"
RESOURCES_DIR="${CONTENTS_DIR}/Resources"
BUILD_DIR="${ROOT_DIR}/.build/eve-monitor"
PRODUCT="${BUILD_DIR}/${APP_NAME}"
MODE="${1:-run}"

if [[ "$#" -gt 1 ]]; then
  echo "usage: $0 [run|--logs|--telemetry|--verify]" >&2
  exit 2
fi

mkdir -p "${BUILD_DIR}" "${MACOS_DIR}" "${RESOURCES_DIR}"

pkill -x "${APP_NAME}" >/dev/null 2>&1 || true

swiftc -parse-as-library -O \
  -framework SwiftUI \
  -framework AppKit \
  -framework Combine \
  -framework Charts \
  "${ROOT_DIR}/mac/EveMonitorSupport.swift" \
  "${ROOT_DIR}/mac/EveMonitorModel.swift" \
  "${ROOT_DIR}/mac/EveMonitorChromeViews.swift" \
  "${ROOT_DIR}/mac/EveMonitorConversationViews.swift" \
  "${ROOT_DIR}/mac/EveMonitorViews.swift" \
  "${ROOT_DIR}/mac/EveMonitorApp.swift" \
  -o "${PRODUCT}"

cat > "${CONTENTS_DIR}/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>en</string>
  <key>CFBundleExecutable</key>
  <string>Eve Monitor</string>
  <key>CFBundleIdentifier</key>
  <string>${BUNDLE_ID}</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>Eve Monitor</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>1.0</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSMinimumSystemVersion</key>
  <string>13.0</string>
  <key>NSPrincipalClass</key>
  <string>NSApplication</string>
  <key>NSAppTransportSecurity</key>
  <dict>
    <key>NSAllowsLocalNetworking</key>
    <true/>
  </dict>
</dict>
</plist>
PLIST

if [[ -f "${ROOT_DIR}/mac/generated/eve.icns" ]]; then
  cp "${ROOT_DIR}/mac/generated/eve.icns" "${RESOURCES_DIR}/eve.icns"
fi

cp "${PRODUCT}" "${MACOS_DIR}/${APP_NAME}"
chmod +x "${MACOS_DIR}/${APP_NAME}"

open_app() {
  /usr/bin/open -n "${APP_PATH}"
}

verify_running() {
  for _ in {1..30}; do
    if pgrep -x "${APP_NAME}" >/dev/null 2>&1; then
      echo "${APP_NAME} is running."
      return 0
    fi
    sleep 0.2
  done
  echo "${APP_NAME} did not launch." >&2
  return 1
}

case "${MODE}" in
  run)
    open_app
    ;;
  --verify|verify)
    open_app
    verify_running
    ;;
  --logs|logs)
    open_app
    verify_running
    /usr/bin/log stream --info --style compact --predicate "process == \"${APP_NAME}\""
    ;;
  --telemetry|telemetry)
    open_app
    verify_running
    /usr/bin/log stream --info --style compact --predicate "subsystem == \"${BUNDLE_ID}\" || process == \"${APP_NAME}\""
    ;;
  *)
    echo "usage: $0 [run|--logs|--telemetry|--verify]" >&2
    exit 2
    ;;
esac
