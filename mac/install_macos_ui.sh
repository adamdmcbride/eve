#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="${HOME}/Applications"
LAUNCH_AGENT_DIR="${HOME}/Library/LaunchAgents"
PYTHON_BIN="/Library/Developer/CommandLineTools/usr/bin/python3"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="$(command -v python3)"
fi
EVE_SERVICE_NAMESPACE="$("${PYTHON_BIN}" "${ROOT_DIR}/eve_profile.py" namespace 2>/dev/null || true)"
EVE_SERVICE_NAMESPACE="${EVE_SERVICE_NAMESPACE:-local.eve}"
MENU_AGENT_LABEL="${EVE_SERVICE_NAMESPACE}-menu"
MENU_AGENT_PLIST="${LAUNCH_AGENT_DIR}/${MENU_AGENT_LABEL}.plist"
ARCHIVE_ROOT="${HOME}/.eve_runtime/retired-apps/$(date -u +%Y%m%dT%H%M%SZ)"
MODE="${1:-install}"

RETIRED_APP_NAMES=(
  "Eve Chat"
  "Eve Monitor"
  "Eve Presence"
  "Eve Menu"
  "Open Eve"
  "Eve Home"
)

if [[ "${MODE}" != "install" && "${MODE}" != "--dry-run" ]]; then
  echo "usage: $0 [install|--dry-run]" >&2
  exit 2
fi

print_plan() {
  cat <<PLAN
Canonical product boundary:
  keep: ${APP_DIR}/Eve.app
  keep separate: ${APP_DIR}/Eve Control.app (the current Eve Home product)
  retire: ${RETIRED_APP_NAMES[*]}

Eve.app is a shared living timeline for Eve's messages, public thought stream,
verified actions, reflections, and conversations. Monitor, Presence, Chat,
menu-helper, launcher-wrapper, and the superseded Eve Home.app are no longer
separate products. OpenClaw remains a headless body/action service. The current
Eve Home product, Eve Control.app, remains independent.
PLAN
}

if [[ "${MODE}" == "--dry-run" ]]; then
  print_plan
  exit 0
fi

mkdir -p "${APP_DIR}" "${LAUNCH_AGENT_DIR}"

if [[ "${EVE_SKIP_RUNTIME_SYNC:-0}" != "1" ]]; then
  echo "Syncing Eve's local runtime..."
  "${PYTHON_BIN}" "${ROOT_DIR}/eve.py" daemon install >/dev/null
else
  echo "Skipping runtime sync (EVE_SKIP_RUNTIME_SYNC=1)."
fi

echo "Building the canonical Eve.app..."
"${ROOT_DIR}/script/build_eve_chat_app.sh" build

mkdir -p "${ARCHIVE_ROOT}"

for app_name in "${RETIRED_APP_NAMES[@]}"; do
  source_path="${APP_DIR}/${app_name}.app"
  if [[ ! -d "${source_path}" ]]; then
    continue
  fi
  pkill -x "${app_name}" >/dev/null 2>&1 || true
  destination="${ARCHIVE_ROOT}/${app_name}.app"
  if [[ -e "${destination}" ]]; then
    destination="${ARCHIVE_ROOT}/${app_name}-$(date +%s).app"
  fi
  mv "${source_path}" "${destination}"
  echo "Retired ${app_name}.app"
done

if [[ -f "${MENU_AGENT_PLIST}" ]]; then
  launchctl bootout "gui/$(id -u)" "${MENU_AGENT_PLIST}" >/dev/null 2>&1 || true
  launchctl disable "gui/$(id -u)/${MENU_AGENT_LABEL}" >/dev/null 2>&1 || true
  mv "${MENU_AGENT_PLIST}" "${ARCHIVE_ROOT}/${MENU_AGENT_LABEL}.plist"
  echo "Retired the separate Eve menu login item."
fi

echo
echo "Installed:"
echo "  ${APP_DIR}/Eve.app"
echo
echo "Kept separate and unchanged:"
[[ -d "${APP_DIR}/Eve Control.app" ]] && echo "  ${APP_DIR}/Eve Control.app (Eve Home)"
echo
echo "Previous duplicate Eve apps were preserved under:"
echo "  ${ARCHIVE_ROOT}"
echo
echo "Launch Eve with:"
echo "  open \"${APP_DIR}/Eve.app\""
