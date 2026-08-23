#!/bin/zsh
set -euo pipefail

ROOT="${EVE_PROJECT_ROOT:-${0:A:h:h}}"
PROFILE="${OPENCLAW_EVE_PROFILE:-eve-repair}"
WORKSPACE="${OPENCLAW_EVE_WORKSPACE:-$HOME/.eve_runtime/openclaw}"
PORT="${OPENCLAW_EVE_PORT:-19011}"
STATE_DIR="${OPENCLAW_EVE_STATE_DIR:-$HOME/.openclaw-$PROFILE}"
CONFIG_TEMPLATE="$ROOT/openclaw/config/eve-openclaw.base.json"
SYNC_SCRIPT="$ROOT/bin/eve_openclaw_sync.py"
WEBHOOK_SECRET_FILE="$STATE_DIR/eve-repair-webhook.secret"
INSTALL_DAEMON="${1:-}"
CODEX_APP_RESOURCES="/Applications/Codex.app/Contents/Resources"

if [[ -x "/opt/homebrew/opt/node/bin/node" ]]; then
  export PATH="/opt/homebrew/opt/node/bin:$PATH"
fi

if [[ -x "$CODEX_APP_RESOURCES/codex" ]]; then
  export PATH="$PATH:$CODEX_APP_RESOURCES"
fi

mkdir -p "$WORKSPACE" "$STATE_DIR"

if ! command -v openclaw >/dev/null 2>&1; then
  echo "OpenClaw is not installed. Install it first with: npm install -g openclaw@latest" >&2
  exit 1
fi

if [[ ! -f "$CONFIG_TEMPLATE" ]]; then
  echo "Missing config template at $CONFIG_TEMPLATE" >&2
  exit 1
fi

if [[ -f "$STATE_DIR/openclaw.json" ]]; then
  if ! openclaw --profile "$PROFILE" config validate >/dev/null 2>&1; then
    mv "$STATE_DIR/openclaw.json" "$STATE_DIR/openclaw.json.preinstall-broken.$(date +%s).bak"
  fi
fi

openclaw --profile "$PROFILE" onboard \
  --non-interactive \
  --accept-risk \
  --mode local \
  --auth-choice skip \
  --workspace "$WORKSPACE" \
  --gateway-port "$PORT" \
  --skip-channels \
  --skip-search \
  --skip-skills \
  --skip-ui \
  --skip-health \
  --skip-daemon >/dev/null
CONFIG_PATH="$(openclaw --profile "$PROFILE" config file | tail -n 1 | tr -d '\r')"
export EVE_OPENCLAW_SECRET_FILE="$WEBHOOK_SECRET_FILE"
export EVE_OPENCLAW_TEMPLATE="$CONFIG_TEMPLATE"
export EVE_OPENCLAW_CONFIG="$CONFIG_PATH"
export EVE_OPENCLAW_WORKSPACE="$WORKSPACE"
export EVE_OPENCLAW_PORT="$PORT"
export EVE_PROJECT_ROOT="$ROOT"

python3 - <<'PY'
import secrets
import os
from pathlib import Path

secret_path = Path(os.environ["EVE_OPENCLAW_SECRET_FILE"])
secret_path.parent.mkdir(parents=True, exist_ok=True)
if not secret_path.exists():
    secret_path.write_text(secrets.token_urlsafe(32) + "\n", encoding="utf-8")
PY

python3 - <<'PY'
import json
import os
import sys
from pathlib import Path

template_path = Path(os.environ["EVE_OPENCLAW_TEMPLATE"]).expanduser()
config_path = Path(os.environ["EVE_OPENCLAW_CONFIG"]).expanduser()
workspace = os.environ["EVE_OPENCLAW_WORKSPACE"]
port = int(os.environ["EVE_OPENCLAW_PORT"])
secret_file = os.environ["EVE_OPENCLAW_SECRET_FILE"]
secret_value = Path(secret_file).read_text(encoding="utf-8").strip()
runtime_root = str((Path.home() / ".eve_runtime").resolve())

def deep_merge(base, overlay):
    if isinstance(base, dict) and isinstance(overlay, dict):
        result = dict(base)
        for key, value in overlay.items():
            if key in result:
                result[key] = deep_merge(result[key], value)
            else:
                result[key] = value
        return result
    return overlay

base = {}
if config_path.exists():
    try:
        base = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        base = {}
if isinstance(base.get("agents"), dict) and isinstance(base["agents"].get("defaults"), dict):
    defaults = dict(base["agents"]["defaults"])
    defaults.pop("tools", None)
    base["agents"]["defaults"] = defaults

template = json.loads(template_path.read_text(encoding="utf-8"))

def replace_placeholders(value):
    if value == "__EVE_GATEWAY_PORT__":
        return port
    if value == "__EVE_WORKSPACE__":
        return workspace
    if value == "__EVE_WEBHOOK_SECRET_FILE__":
        return secret_file
    if value == "__EVE_WEBHOOK_SECRET__":
        return secret_value
    if isinstance(value, str):
        return value.replace("__EVE_RUNTIME_ROOT__", runtime_root)
    if isinstance(value, list):
        return [replace_placeholders(item) for item in value]
    if isinstance(value, dict):
        return {key: replace_placeholders(item) for key, item in value.items()}
    return value

merged = deep_merge(base, replace_placeholders(template))
if isinstance(merged.get("agents"), dict) and isinstance(merged["agents"].get("defaults"), dict):
    merged["agents"]["defaults"].pop("tools", None)
plugin_entries = merged.setdefault("plugins", {}).setdefault("entries", {})
if isinstance(plugin_entries, dict):
    # The older external `codex` plugin is not installed or part of Eve's
    # admitted organ boundary. Codex stays a separate typed operator bridge.
    plugin_entries.pop("codex", None)
defaults = merged.setdefault("agents", {}).setdefault("defaults", {})
defaults["model"] = {
    "primary": "llamacpp-deep/eve-deep",
    "fallbacks": [],
}
defaults["models"] = {}
merged["models"] = {"mode": "replace", "providers": {}}
project_root = Path(os.environ["EVE_PROJECT_ROOT"])
sys.path.insert(0, str(project_root / "bin"))
import eve_openclaw_topology_sync

runtime_eve_config = Path.home() / ".eve_runtime" / ".eve" / "config.json"
source_eve_config = project_root / ".eve" / "config.json"
eve_config_path = runtime_eve_config if runtime_eve_config.is_file() else source_eve_config
try:
    eve_config = json.loads(eve_config_path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    eve_config = {}
merged, _topology_report = eve_openclaw_topology_sync.reconcile_openclaw_topology_config(
    eve_config, merged
)
config_path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
PY

python3 "$SYNC_SCRIPT" --workspace "$WORKSPACE" >/dev/null
openclaw --profile "$PROFILE" config validate >/dev/null

if [[ "$INSTALL_DAEMON" == "--install-daemon" ]]; then
  openclaw --profile "$PROFILE" gateway install >/dev/null
  openclaw --profile "$PROFILE" gateway start >/dev/null
fi

cat <<EOF
OpenClaw sidecar installed for Eve.

Profile: $PROFILE
Workspace: $WORKSPACE
Config: $CONFIG_PATH
Gateway port: $PORT
Webhook secret file: $WEBHOOK_SECRET_FILE

Next:
  python3 $ROOT/bin/eve_openclaw_repair.py

Optional daemon install:
  $0 --install-daemon
EOF
