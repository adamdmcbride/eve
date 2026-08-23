#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_RUNTIME_ROOT="${HOME}/.eve_runtime/.eve/eve-chat-ui"
LEGACY_RUNTIME_ROOT="${HOME}/.eve_runtime/.eve/openwebui"
RUNTIME_ROOT="${EVE_CHAT_UI_RUNTIME_ROOT:-${EVE_OPENWEBUI_RUNTIME_ROOT:-${DEFAULT_RUNTIME_ROOT}}}"
DATA_DIR_VALUE="${EVE_CHAT_UI_DATA_DIR:-${EVE_OPENWEBUI_DATA_DIR:-${RUNTIME_ROOT}/data}}"
UV_CACHE_DIR_VALUE="${EVE_CHAT_UI_UV_CACHE_DIR:-${EVE_OPENWEBUI_UV_CACHE_DIR:-${RUNTIME_ROOT}/uv-cache}}"
LOG_PATH="${EVE_CHAT_UI_LOG:-${EVE_OPENWEBUI_LOG:-${RUNTIME_ROOT}/eve-chat-ui.log}}"
PID_PATH="${EVE_CHAT_UI_PID:-${EVE_OPENWEBUI_PID:-${RUNTIME_ROOT}/eve-chat-ui.pid}}"
SECRET_KEY_PATH="${EVE_CHAT_UI_SECRET_KEY_FILE:-${EVE_OPENWEBUI_SECRET_KEY_FILE:-${RUNTIME_ROOT}/webui_secret_key}}"
WEBUI_HOST="${EVE_CHAT_UI_HOST:-${EVE_OPENWEBUI_HOST:-127.0.0.1}}"
WEBUI_PORT="${EVE_CHAT_UI_PORT:-${EVE_OPENWEBUI_PORT:-3000}}"
WEBUI_AUTH_VALUE="${WEBUI_AUTH:-false}"
EVE_WEBUI_BRAND_NAME="${EVE_WEBUI_BRAND_NAME:-Eve}"
EVE_WEBUI_BRAND_SLUG="${EVE_WEBUI_BRAND_SLUG:-eve}"
EVE_CHAT_UI_BRAND_MODE="${EVE_CHAT_UI_BRAND_MODE:-${EVE_OPENWEBUI_BRAND_MODE:-small-scale-local}}"
EVE_HOST_BASE_URL="${EVE_HOST_BASE_URL:-http://127.0.0.1:8797}"
EVE_CHAT_BACKEND_BASE_URL="${EVE_CHAT_BACKEND_BASE_URL:-${EVE_COMPAT_BASE_URL:-${EVE_OPENAI_BASE_URL:-${EVE_HOST_BASE_URL}/v1}}}"
EVE_CHAT_BACKEND_KEY="${EVE_CHAT_BACKEND_API_KEY:-${EVE_COMPAT_API_KEY:-${EVE_OPENAI_API_KEY:-eve-local}}}"
EVE_CHAT_UI_MODEL="${EVE_CHAT_UI_MODEL:-${EVE_OPENWEBUI_MODEL:-eve}}"
EVE_CHAT_UI_PACKAGE="${EVE_CHAT_UI_PACKAGE:-${EVE_OPENWEBUI_PACKAGE:-open-webui==0.9.2}}"
EVE_CHAT_UI_PYTHON="${EVE_CHAT_UI_PYTHON:-${EVE_OPENWEBUI_PYTHON:-3.11}}"
LOCAL_SERVER="${PROJECT_ROOT}/bin/eve_chat_local_serve.py"

if ! command -v uvx >/dev/null 2>&1; then
  echo "uvx is required for Eve Chat's local UI. Install uv first." >&2
  exit 1
fi

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
    lsof -tiTCP:"${WEBUI_PORT}" -sTCP:LISTEN 2>/dev/null | head -n 1 || true
  fi
}

if command -v curl >/dev/null 2>&1; then
  if ! curl -fsS "${EVE_CHAT_BACKEND_BASE_URL}/models" >/dev/null; then
    echo "Eve Chat backend did not answer at ${EVE_CHAT_BACKEND_BASE_URL}/models." >&2
    echo "Start Eve's local chat backend first, for example: bin/eve_chat_backend_server.sh" >&2
    exit 1
  fi
fi

mkdir -p "${RUNTIME_ROOT}" "${DATA_DIR_VALUE}" "${UV_CACHE_DIR_VALUE}"
if [ "${RUNTIME_ROOT}" != "${LEGACY_RUNTIME_ROOT}" ] && [ ! -e "${DATA_DIR_VALUE}/webui.db" ] && [ -d "${LEGACY_RUNTIME_ROOT}/data" ]; then
  cp -R "${LEGACY_RUNTIME_ROOT}/data/." "${DATA_DIR_VALUE}/" 2>/dev/null || true
fi
if [ "${RUNTIME_ROOT}" != "${LEGACY_RUNTIME_ROOT}" ] && [ ! -f "${SECRET_KEY_PATH}" ] && [ -f "${LEGACY_RUNTIME_ROOT}/webui_secret_key" ]; then
  cp "${LEGACY_RUNTIME_ROOT}/webui_secret_key" "${SECRET_KEY_PATH}" 2>/dev/null || true
fi
secret_len=0
if [ -f "${SECRET_KEY_PATH}" ]; then
  secret_len="$(wc -c < "${SECRET_KEY_PATH}" | tr -d ' ')"
fi
if [ "${secret_len}" -lt 32 ]; then
  python3 - "${SECRET_KEY_PATH}" <<'PY'
from pathlib import Path
import secrets
import sys

Path(sys.argv[1]).write_text(secrets.token_urlsafe(48), encoding="utf-8")
PY
fi
WEBUI_SECRET_KEY_VALUE="$(cat "${SECRET_KEY_PATH}")"

if [ -f "${PID_PATH}" ]; then
  old_pid="$(cat "${PID_PATH}" 2>/dev/null || true)"
  if [ -n "${old_pid}" ] && kill -0 "${old_pid}" 2>/dev/null; then
    stop_process_tree "${old_pid}"
  fi
  rm -f "${PID_PATH}"
fi

existing_listener="$(listener_pid)"
if [ -n "${existing_listener}" ] && kill -0 "${existing_listener}" 2>/dev/null; then
  stop_process_tree "${existing_listener}"
fi

# The adopted upstream UI requires OPENAI_API_* env variable names for its local
# chat-completions provider slot. They point to Eve's local backend only.
(
  cd "${RUNTIME_ROOT}"
  nohup env \
    DATA_DIR="${DATA_DIR_VALUE}" \
    UV_CACHE_DIR="${UV_CACHE_DIR_VALUE}" \
    WEBUI_SECRET_KEY="${WEBUI_SECRET_KEY_VALUE}" \
    WEBUI_AUTH="${WEBUI_AUTH_VALUE}" \
    WEBUI_NAME="${EVE_WEBUI_BRAND_NAME}" \
    CORS_ALLOW_ORIGIN="http://${WEBUI_HOST}:${WEBUI_PORT}" \
    CUSTOM_NAME="" \
    ENABLE_PERSISTENT_CONFIG=false \
    EVE_WEBUI_BRAND_NAME="${EVE_WEBUI_BRAND_NAME}" \
    EVE_WEBUI_BRAND_SLUG="${EVE_WEBUI_BRAND_SLUG}" \
    EVE_CHAT_UI_BRAND_MODE="${EVE_CHAT_UI_BRAND_MODE}" \
    ENABLE_OPENAI_API=true \
    ENABLE_OLLAMA_API=false \
    ENABLE_COMMUNITY_SHARING=false \
    ENABLE_VERSION_UPDATE_CHECK=false \
    ENABLE_EVALUATION_ARENA_MODELS=false \
    UVICORN_WORKERS=1 \
    OPENAI_API_BASE_URL="${EVE_CHAT_BACKEND_BASE_URL}" \
    OPENAI_API_BASE_URLS="${EVE_CHAT_BACKEND_BASE_URL}" \
    OPENAI_API_KEY="${EVE_CHAT_BACKEND_KEY}" \
    OPENAI_API_KEYS="${EVE_CHAT_BACKEND_KEY}" \
    DEFAULT_MODELS="${EVE_CHAT_UI_MODEL}" \
    uvx --python "${EVE_CHAT_UI_PYTHON}" --from "${EVE_CHAT_UI_PACKAGE}" \
      python "${LOCAL_SERVER}" \
      --host "${WEBUI_HOST}" \
      --port "${WEBUI_PORT}" \
      --brand-name "${EVE_WEBUI_BRAND_NAME}" \
      --brand-slug "${EVE_WEBUI_BRAND_SLUG}" \
      --brand-mode "${EVE_CHAT_UI_BRAND_MODE}" \
      >"${LOG_PATH}" 2>&1 &
  echo "$!" > "${PID_PATH}"
)

new_pid="$(cat "${PID_PATH}")"

if command -v curl >/dev/null 2>&1; then
  for _ in $(seq 1 120); do
    if curl -fsS "http://${WEBUI_HOST}:${WEBUI_PORT}/health" >/dev/null 2>&1; then
      live_pid="$(listener_pid)"
      if [ -n "${live_pid}" ]; then
        new_pid="${live_pid}"
        echo "${new_pid}" > "${PID_PATH}"
      fi
      echo "Eve Chat is running at http://${WEBUI_HOST}:${WEBUI_PORT}"
      echo "Backend: ${EVE_CHAT_BACKEND_BASE_URL}"
      echo "Model: ${EVE_CHAT_UI_MODEL}"
      echo "PID: ${new_pid}"
      echo "Log: ${LOG_PATH}"
      echo "Runtime: ${RUNTIME_ROOT}"
      echo "Package: ${EVE_CHAT_UI_PACKAGE}"
      echo "Presentation brand: ${EVE_WEBUI_BRAND_NAME} (${EVE_CHAT_UI_BRAND_MODE})"
      echo "Provider boundary: local Eve backend only; no hosted provider is called."
      exit 0
    fi
    if ! kill -0 "${new_pid}" 2>/dev/null; then
      live_pid="$(listener_pid)"
      if [ -n "${live_pid}" ]; then
        new_pid="${live_pid}"
        echo "${new_pid}" > "${PID_PATH}"
        sleep 1
        continue
      fi
      echo "Eve Chat exited before becoming healthy. Log follows:" >&2
      tail -80 "${LOG_PATH}" >&2 || true
      exit 1
    fi
    sleep 1
  done
  echo "Timed out waiting for Eve Chat health. Log follows:" >&2
  tail -80 "${LOG_PATH}" >&2 || true
  exit 1
fi

echo "Eve Chat started at http://${WEBUI_HOST}:${WEBUI_PORT}"
echo "PID: ${new_pid}"
echo "Log: ${LOG_PATH}"
