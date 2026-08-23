#!/bin/zsh

set -u

PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PATH

OLLAMA_URL="http://127.0.0.1:11434"
SCRIPT_DIR="${0:A:h}"
SOURCE_CONFIG_PATH="${SCRIPT_DIR:h}/.eve/config.json"
RUNTIME_CONFIG_PATH="${HOME}/.eve_runtime/.eve/config.json"
CONFIG_PATH="${EVE_CONFIG_PATH:-${RUNTIME_CONFIG_PATH}}"
if [[ ! -r "${CONFIG_PATH}" ]]; then
  CONFIG_PATH="${SOURCE_CONFIG_PATH}"
fi
export EVE_CONFIG_PATH="${CONFIG_PATH}"

load_models() {
  python3 - <<'PY'
import json
import os
from pathlib import Path

config_path = Path(os.environ["EVE_CONFIG_PATH"])
default = ["eve-fast", "eve-deep"]
if not config_path.exists():
    print("\n".join(default))
    raise SystemExit(0)

try:
    payload = json.loads(config_path.read_text())
except json.JSONDecodeError:
    print("\n".join(default))
    raise SystemExit(0)

names = []
def normalize_backend(value):
    text = " ".join(str(value or "").lower().replace("-", "_").split())
    if text in {"llama.cpp", "llama cpp", "llama_server", "llama"}:
        text = "llama_cpp"
    return text if text in {"ollama", "llama_cpp"} else "ollama"

def backend_for_model(name):
    text = " ".join(str(name or "").split()).strip()
    if not text:
        return "ollama"
    fast_model = " ".join(str(payload.get("fast_model") or "").split()).strip()
    deep_model = " ".join(str(payload.get("deep_model") or "").split()).strip()
    fast_backend = normalize_backend(payload.get("fast_model_backend")) if str(payload.get("fast_model_backend") or "").strip() else ""
    deep_backend = normalize_backend(payload.get("deep_model_backend")) if str(payload.get("deep_model_backend") or "").strip() else ""
    if fast_backend and text == fast_model:
        return fast_backend
    if deep_backend and text == deep_model:
        return deep_backend
    return normalize_backend(payload.get("model_backend"))

for key, value in payload.items():
    if key == "model" or key.endswith("_model"):
        text = " ".join(str(value or "").split()).strip()
        if text and backend_for_model(text) == "ollama" and text not in names:
            names.append(text)
for item in payload.get("resident_models") or []:
    text = " ".join(str(item or "").split()).strip()
    if text and backend_for_model(text) == "ollama" and text not in names:
        names.append(text)
print("\n".join(names))
PY
}

timestamp() {
  date +"%Y-%m-%dT%H:%M:%S%z"
}

echo "[$(timestamp)] ensure_eve_models_warm starting"

MODELS=("${(@f)$(load_models)}")
FILTERED_MODELS=()
for model in "${MODELS[@]}"; do
  if [[ -n "${model}" ]]; then
    FILTERED_MODELS+=("${model}")
  fi
done
MODELS=("${FILTERED_MODELS[@]}")
if [[ "${#MODELS[@]}" -eq 0 ]]; then
  launchctl unsetenv OLLAMA_KEEP_ALIVE || true
  launchctl unsetenv OLLAMA_MAX_LOADED_MODELS || true
  echo "[$(timestamp)] no Ollama-backed models configured; skipping warm pass"
  exit 0
fi

MODEL_CAP=${#MODELS[@]}
if [[ "${MODEL_CAP}" -lt 3 ]]; then
  MODEL_CAP=3
fi

# Persist a session-wide default so future model loads inherit infinite keep-alive.
launchctl setenv OLLAMA_KEEP_ALIVE -1 || true
launchctl setenv OLLAMA_MAX_LOADED_MODELS "${MODEL_CAP}" || true

if ! pgrep -f "ollama serve" >/dev/null 2>&1; then
  echo "[$(timestamp)] Ollama not running, launching headless server"
  if [[ -x "/Applications/Ollama.app/Contents/Resources/ollama" ]]; then
    nohup /Applications/Ollama.app/Contents/Resources/ollama serve >/tmp/eve_ollama_warm.log 2>&1 &
  elif command -v ollama >/dev/null 2>&1; then
    nohup "$(command -v ollama)" serve >/tmp/eve_ollama_warm.log 2>&1 &
  else
    echo "[$(timestamp)] Ollama binary not found" >&2
  fi
fi

ready=0
for _ in {1..60}; do
  if curl -sf "${OLLAMA_URL}/api/tags" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done

if [[ "${ready}" -ne 1 ]]; then
  echo "[$(timestamp)] Ollama API did not become ready in time"
  exit 0
fi

for model in "${MODELS[@]}"; do
  payload=$(printf '{"model":"%s","keep_alive":-1}' "${model}")
  if curl -sf -H "Content-Type: application/json" "${OLLAMA_URL}/api/generate" -d "${payload}" >/dev/null 2>&1; then
    echo "[$(timestamp)] pinned ${model}"
  else
    echo "[$(timestamp)] failed to pin ${model}" >&2
  fi
done

echo "[$(timestamp)] ensure_eve_models_warm finished"
