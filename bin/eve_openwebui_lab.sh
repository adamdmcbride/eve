#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for candidate in \
  "${SCRIPT_DIR}/eve_chat_surface_lab.sh" \
  "${SCRIPT_DIR}/bin/eve_chat_surface_lab.sh"; do
  if [ -x "${candidate}" ]; then
    exec "${candidate}" "$@"
  fi
done

echo "Missing Eve Chat local UI launcher." >&2
exit 127
