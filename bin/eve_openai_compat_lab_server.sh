#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for candidate in \
  "${SCRIPT_DIR}/eve_chat_backend_server.sh" \
  "${SCRIPT_DIR}/bin/eve_chat_backend_server.sh"; do
  if [ -x "${candidate}" ]; then
    exec "${candidate}" "$@"
  fi
done

echo "Missing Eve Chat backend launcher." >&2
exit 127
