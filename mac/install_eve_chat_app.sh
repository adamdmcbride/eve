#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
exec "${ROOT_DIR}/script/build_eve_chat_app.sh" build
