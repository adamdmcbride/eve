#!/bin/zsh

set -euo pipefail

PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PATH

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required to install llama.cpp on this machine." >&2
  exit 1
fi

brew install llama.cpp
llama-server --version
