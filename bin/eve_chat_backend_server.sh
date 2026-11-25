#!/usr/bin/env bash
set -euo pipefail

# Request-local, content-free tracing; descendants reuse the selected context.
export EVE_REQUEST_TRACING="${EVE_REQUEST_TRACING:-1}"

# One root of truth (2026-09-17): the chat backend runs the same source tree the daemon runs, so
# Eve's replies and her daemon never disagree about her code. The runtime mirror is the fallback.
SOURCE_DIR="${EVE_SOURCE_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
if [ -f "${SOURCE_DIR}/eve.py" ]; then
  RUNTIME_DIR="${SOURCE_DIR}"
else
  RUNTIME_DIR="${EVE_RUNTIME_DIR:-${HOME}/.eve_runtime}"
fi
HOST="${EVE_CHAT_BACKEND_HOST:-${EVE_OPENAI_COMPAT_HOST:-127.0.0.1}}"
PORT="${EVE_CHAT_BACKEND_PORT:-${EVE_OPENAI_COMPAT_PORT:-8797}}"
PROJECT_PYTHON="${EVE_PROJECT_PYTHON:-}"

if [ ! -f "${RUNTIME_DIR}/eve.py" ]; then
  echo "Missing Eve code at ${RUNTIME_DIR}/eve.py" >&2
  exit 1
fi

if [ -n "${PROJECT_PYTHON}" ] && [ -x "${PROJECT_PYTHON}" ]; then
  PYTHON_BIN="${PROJECT_PYTHON}"
else
  PYTHON_BIN="/usr/bin/python3"
fi

cd "${RUNTIME_DIR}"
exec "${PYTHON_BIN}" "${RUNTIME_DIR}/eve.py" app --host "${HOST}" --port "${PORT}"
