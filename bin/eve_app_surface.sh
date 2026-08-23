#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_ROOT="${EVE_APP_RUNTIME_ROOT:-${HOME}/.eve_runtime/eve-app}"
STATIC_ROOT="${EVE_APP_STATIC_ROOT:-${PROJECT_ROOT}/web/eve_app}"
SERVER_SCRIPT="${PROJECT_ROOT}/bin/eve_app_server.py"
BACKEND_LAUNCHER="${PROJECT_ROOT}/bin/eve_chat_backend_server.sh"
HOST="${EVE_APP_HOST:-127.0.0.1}"
PORT="${EVE_APP_PORT:-3000}"
BACKEND="${EVE_APP_BACKEND:-http://127.0.0.1:8797}"
PID_PATH="${RUNTIME_ROOT}/eve-app.pid"
LOG_PATH="${RUNTIME_ROOT}/eve-app.log"
BACKEND_LOG_PATH="${RUNTIME_ROOT}/eve-backend.log"

PYTHON_BIN="${EVE_APP_PYTHON:-/usr/bin/python3}"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="$(command -v python3)"
fi

mkdir -p "${RUNTIME_ROOT}"

stop_process_tree() {
  local pid="$1"
  local child
  if command -v pgrep >/dev/null 2>&1; then
    for child in $(pgrep -P "${pid}" 2>/dev/null || true); do
      stop_process_tree "${child}"
    done
  fi
  kill "${pid}" 2>/dev/null || true
  for _ in $(seq 1 20); do
    if ! kill -0 "${pid}" 2>/dev/null; then
      return 0
    fi
    sleep 0.2
  done
  kill -9 "${pid}" 2>/dev/null || true
}

listener_pid() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -tiTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null | head -n 1 || true
  fi
}

backend_ready() {
  curl -fsS --max-time 2 "${BACKEND}/v1/models" >/dev/null 2>&1
}

surface_ready() {
  local payload
  payload="$(curl -fsS --max-time 2 "http://${HOST}:${PORT}/health" 2>/dev/null || true)"
  [[ "${payload}" == *'"surface": "eve-app"'* || "${payload}" == *'"surface":"eve-app"'* ]]
}

if surface_ready; then
  echo "Eve is ready at http://${HOST}:${PORT}"
  exit 0
fi

if [[ -f "${PID_PATH}" ]]; then
  old_pid="$(cat "${PID_PATH}" 2>/dev/null || true)"
  if [[ -n "${old_pid}" ]] && kill -0 "${old_pid}" 2>/dev/null; then
    stop_process_tree "${old_pid}"
  fi
  rm -f "${PID_PATH}"
fi

existing_listener="$(listener_pid)"
if [[ -n "${existing_listener}" ]] && kill -0 "${existing_listener}" 2>/dev/null; then
  existing_command="$(ps -p "${existing_listener}" -o command= 2>/dev/null || true)"
  case "${existing_command}" in
    *eve_app_server.py*|*eve_chat_local_serve.py*|*open-webui*)
      stop_process_tree "${existing_listener}"
      ;;
    *)
      echo "Port ${PORT} is already owned by an unrelated process: ${existing_command}" >&2
      exit 1
      ;;
  esac
fi

if ! backend_ready; then
  if [[ ! -x "${BACKEND_LAUNCHER}" ]]; then
    echo "Eve's local backend is offline and ${BACKEND_LAUNCHER} is unavailable." >&2
    exit 1
  fi
  nohup "${BACKEND_LAUNCHER}" >"${BACKEND_LOG_PATH}" 2>&1 &
  for _ in $(seq 1 80); do
    if backend_ready; then
      break
    fi
    sleep 0.25
  done
  if ! backend_ready; then
    echo "Eve's local backend did not become ready. Log: ${BACKEND_LOG_PATH}" >&2
    tail -40 "${BACKEND_LOG_PATH}" >&2 || true
    exit 1
  fi
fi

if [[ ! -f "${SERVER_SCRIPT}" || ! -f "${STATIC_ROOT}/index.html" ]]; then
  echo "Eve app assets are missing. server=${SERVER_SCRIPT} static=${STATIC_ROOT}" >&2
  exit 1
fi

nohup "${PYTHON_BIN}" "${SERVER_SCRIPT}" \
  --host "${HOST}" \
  --port "${PORT}" \
  --backend "${BACKEND}" \
  --static-root "${STATIC_ROOT}" \
  >"${LOG_PATH}" 2>&1 &
echo "$!" >"${PID_PATH}"

for _ in $(seq 1 80); do
  if surface_ready; then
    echo "Eve is ready at http://${HOST}:${PORT}"
    echo "Backend: ${BACKEND} (local only)"
    echo "PID: $(cat "${PID_PATH}")"
    echo "Log: ${LOG_PATH}"
    exit 0
  fi
  if ! kill -0 "$(cat "${PID_PATH}")" 2>/dev/null; then
    echo "Eve's app surface exited before becoming ready. Log follows:" >&2
    tail -60 "${LOG_PATH}" >&2 || true
    exit 1
  fi
  sleep 0.25
done

echo "Timed out waiting for Eve's app surface. Log follows:" >&2
tail -60 "${LOG_PATH}" >&2 || true
exit 1
