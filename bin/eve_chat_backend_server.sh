#!/usr/bin/env bash
set -euo pipefail

RUNTIME_DIR="${EVE_RUNTIME_DIR:-${HOME}/.eve_runtime}"
HOST="${EVE_CHAT_BACKEND_HOST:-${EVE_OPENAI_COMPAT_HOST:-127.0.0.1}}"
PORT="${EVE_CHAT_BACKEND_PORT:-${EVE_OPENAI_COMPAT_PORT:-8797}}"
PROJECT_PYTHON="${EVE_PROJECT_PYTHON:-}"

if [ ! -f "${RUNTIME_DIR}/eve.py" ]; then
  echo "Missing Eve runtime mirror at ${RUNTIME_DIR}/eve.py" >&2
  exit 1
fi

if [ -n "${PROJECT_PYTHON}" ] && [ -x "${PROJECT_PYTHON}" ]; then
  PYTHON_BIN="${PROJECT_PYTHON}"
else
  PYTHON_BIN="/usr/bin/python3"
fi

cd "${RUNTIME_DIR}"
exec "${PYTHON_BIN}" "${RUNTIME_DIR}/eve.py" app --host "${HOST}" --port "${PORT}"
