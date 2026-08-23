#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${0}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="/Library/Developer/CommandLineTools/usr/bin/python3"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="$(command -v python3)"
fi

EVE_PY="${ROOT_DIR}/eve.py"

if [[ ! -f "${EVE_PY}" ]]; then
  echo "Could not find eve.py at ${EVE_PY}" >&2
  exit 1
fi

exec "${PYTHON_BIN}" "${EVE_PY}" claude "$@"
