#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="${HOME}/Applications"
APP_NAME="Eve"
BUNDLE_ID="${EVE_APP_BUNDLE_ID:-local.eve.app}"
APP_PATH="${APP_DIR}/${APP_NAME}.app"
CONTENTS_DIR="${APP_PATH}/Contents"
MACOS_DIR="${CONTENTS_DIR}/MacOS"
RESOURCES_DIR="${CONTENTS_DIR}/Resources"
BUILD_DIR="${ROOT_DIR}/.build/eve-app"
PRODUCT="${BUILD_DIR}/${APP_NAME}"
MODE="${1:-run}"
RUNTIME_BIN="${HOME}/.eve_runtime/bin"

if [[ "$#" -gt 1 ]]; then
  echo "usage: $0 [run|build|--verify|--logs|--telemetry]" >&2
  exit 2
fi

mkdir -p "${BUILD_DIR}" "${MACOS_DIR}" "${RESOURCES_DIR}" "${RUNTIME_BIN}"

cp "${ROOT_DIR}/bin/eve_app_surface.sh" "${RUNTIME_BIN}/eve_app_surface.sh"
cp "${ROOT_DIR}/bin/eve_app_server.py" "${RUNTIME_BIN}/eve_app_server.py"
cp "${ROOT_DIR}/bin/eve_chat_backend_server.sh" "${RUNTIME_BIN}/eve_chat_backend_server.sh"
chmod +x \
  "${RUNTIME_BIN}/eve_app_surface.sh" \
  "${RUNTIME_BIN}/eve_app_server.py" \
  "${RUNTIME_BIN}/eve_chat_backend_server.sh"

mkdir -p "${HOME}/.eve_runtime/web/eve_app"
cp "${ROOT_DIR}/web/eve_app/index.html" "${HOME}/.eve_runtime/web/eve_app/index.html"
cp "${ROOT_DIR}/web/eve_app/styles.css" "${HOME}/.eve_runtime/web/eve_app/styles.css"
cp "${ROOT_DIR}/web/eve_app/app.js" "${HOME}/.eve_runtime/web/eve_app/app.js"

cat > "${HOME}/.eve_runtime/eve_app_surface.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/bin/eve_app_surface.sh" "$@"
SH
chmod +x "${HOME}/.eve_runtime/eve_app_surface.sh"

if [[ -d "/Applications/Xcode.app/Contents/Developer" ]]; then
  SWIFTC=(env DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcrun swiftc)
else
  SWIFTC=(swiftc)
fi

"${SWIFTC[@]}" -parse-as-library -O \
  -target "$(uname -m)-apple-macos13.0" \
  -framework SwiftUI \
  -framework AppKit \
  -framework WebKit \
  "${ROOT_DIR}/mac/EveChatApp.swift" \
  -o "${PRODUCT}"

cat > "${CONTENTS_DIR}/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>en</string>
  <key>CFBundleExecutable</key>
  <string>Eve</string>
  <key>CFBundleIconFile</key>
  <string>eve</string>
  <key>CFBundleIdentifier</key>
  <string>${BUNDLE_ID}</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>Eve</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>3.4</string>
  <key>CFBundleVersion</key>
  <string>11</string>
  <key>LSMinimumSystemVersion</key>
  <string>13.0</string>
  <key>NSPrincipalClass</key>
  <string>NSApplication</string>
  <key>NSHighResolutionCapable</key>
  <true/>
  <key>NSMicrophoneUsageDescription</key>
  <string>Eve uses the microphone only during a sensory session or dictation that you explicitly start. Audio is reduced locally to features and is not recorded.</string>
  <key>NSCameraUsageDescription</key>
  <string>Eve uses the camera only during a visual sensory session that you explicitly start. Frames are reduced locally to scene-change features and are not stored.</string>
  <key>NSSpeechRecognitionUsageDescription</key>
  <string>Eve transcribes speech you choose to dictate into the local conversation.</string>
  <key>NSAppTransportSecurity</key>
  <dict>
    <key>NSAllowsLocalNetworking</key>
    <true/>
  </dict>
</dict>
</plist>
PLIST

if [[ -x "${ROOT_DIR}/mac/build_icons.sh" ]]; then
  if ICON_ICNS="$("${ROOT_DIR}/mac/build_icons.sh")"; then
    cp "${ICON_ICNS}" "${RESOURCES_DIR}/eve.icns"
  elif [[ -f "${ROOT_DIR}/mac/generated/eve.icns" ]]; then
    # Some macOS/iconutil releases reject an otherwise complete legacy
    # iconset. Preserve the last validated local icon rather than blocking an
    # unrelated Eve application build.
    echo "Icon regeneration failed; using the existing validated eve.icns." >&2
    cp "${ROOT_DIR}/mac/generated/eve.icns" "${RESOURCES_DIR}/eve.icns"
  else
    echo "Eve icon regeneration failed and no validated fallback exists." >&2
    exit 1
  fi
elif [[ -f "${ROOT_DIR}/mac/generated/eve.icns" ]]; then
  cp "${ROOT_DIR}/mac/generated/eve.icns" "${RESOURCES_DIR}/eve.icns"
fi

cp "${PRODUCT}" "${MACOS_DIR}/${APP_NAME}"
chmod +x "${MACOS_DIR}/${APP_NAME}"
codesign --force --deep --sign - "${APP_PATH}" >/dev/null

pkill -x "${APP_NAME}" >/dev/null 2>&1 || true

SURFACE_PID_PATH="${HOME}/.eve_runtime/eve-app/eve-app.pid"
surface_pid="$(cat "${SURFACE_PID_PATH}" 2>/dev/null || true)"
if [[ -z "${surface_pid}" ]] && command -v lsof >/dev/null 2>&1; then
  surface_pid="$(lsof -tiTCP:3000 -sTCP:LISTEN 2>/dev/null | head -n 1 || true)"
fi
if [[ -n "${surface_pid}" ]] && kill -0 "${surface_pid}" 2>/dev/null; then
  surface_command="$(ps -p "${surface_pid}" -o command= 2>/dev/null || true)"
  if [[ "${surface_command}" == *eve_app_server.py* ]]; then
    kill "${surface_pid}" 2>/dev/null || true
    for _ in {1..20}; do
      kill -0 "${surface_pid}" 2>/dev/null || break
      sleep 0.1
    done
    kill -9 "${surface_pid}" 2>/dev/null || true
  fi
fi
rm -f "${SURFACE_PID_PATH}"

open_app() {
  /usr/bin/open -n "${APP_PATH}"
}

verify_running() {
  for _ in {1..40}; do
    if pgrep -x "${APP_NAME}" >/dev/null 2>&1; then
      echo "${APP_NAME} is running."
      return 0
    fi
    sleep 0.25
  done
  echo "${APP_NAME} did not launch." >&2
  return 1
}

case "${MODE}" in
  build|install)
    echo "Built ${APP_PATH}"
    ;;
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
    echo "usage: $0 [run|build|--verify|--logs|--telemetry]" >&2
    exit 2
    ;;
esac
