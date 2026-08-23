#!/bin/zsh
# Eve continuity guardian. This runs as an operator-owned LaunchAgent, outside
# Eve's cognitive loop and governance path, so a broken Eve process cannot mark
# itself healthy or silence the check. The repo copy is source controlled; the
# live agent executes ~/.eve_runtime/bin/eve_deadman.sh.

set -u

ALERT_TO="${EVE_DEADMAN_ALERT_TO:-}"
IMSG="/opt/homebrew/bin/imsg"
RUNTIME_APP="${HOME}/.eve_runtime/.eve"
COOLDOWN_FILE="${RUNTIME_APP}/deadman_last_alert.json"
POWER_STATE_FILE="${RUNTIME_APP}/operator_power_state.json"
COOLDOWN_SECONDS=$((6 * 3600))

PRESENCE="${RUNTIME_APP}/presence_pulses.jsonl"
DAEMON_STATE="${RUNTIME_APP}/state.json"
DAEMON_ACTIVITY="${RUNTIME_APP}/daemon_activity.json"
GATEWAY_SQLITE="${HOME}/.openclaw-eve-repair/state/openclaw.sqlite"
SNAPSHOT="${RUNTIME_APP}/system_snapshot.json"
DREAMS="${EVE_DEADMAN_DREAMS_PATH:-${HOME}/.eve_runtime/openclaw/DREAMS.md}"
DOMAIN="gui/$(id -u)"
TOPOLOGY_HELPER="${HOME}/.eve_runtime/eve_model_topology.py"
PROFILE_HELPER="${HOME}/.eve_runtime/eve_profile.py"
TOPOLOGY_CONFIG="${RUNTIME_APP}/config.json"
if [[ -r "$PROFILE_HELPER" ]]; then
  EVE_DAEMON_LABEL=$(/usr/bin/python3 "$PROFILE_HELPER" label 2>/dev/null || true)
fi
EVE_DAEMON_LABEL="${EVE_DAEMON_LABEL:-local.eve}"
CHECK_ONLY=0
if [[ "${1:-}" == "--check-only" ]]; then
  CHECK_ONLY=1
fi

model_topology_mode="five_endpoint"
active_model_urls=(
  "http://127.0.0.1:8080"
  "http://127.0.0.1:8081"
  "http://127.0.0.1:8082"
  "http://127.0.0.1:8083"
  "http://127.0.0.1:8084"
)
if [[ -r "$TOPOLOGY_HELPER" && -r "$TOPOLOGY_CONFIG" ]]; then
  topology_mode_output=$(/usr/bin/python3 "$TOPOLOGY_HELPER" mode --config "$TOPOLOGY_CONFIG" 2>/dev/null || true)
  topology_urls_output=$(/usr/bin/python3 "$TOPOLOGY_HELPER" active-urls --config "$TOPOLOGY_CONFIG" 2>/dev/null || true)
  if [[ -n "$topology_mode_output" && -n "$topology_urls_output" ]]; then
    model_topology_mode="$topology_mode_output"
    active_model_urls=("${(@f)topology_urls_output}")
  fi
fi

now=$(date +%s)
problems=()
warns=()

age_of() {
  local file="$1"
  if [[ ! -e "$file" ]]; then
    echo 999999999
    return
  fi
  echo $((now - $(stat -f %m "$file")))
}

json_timestamp_epoch() {
  local file="$1"
  local field="$2"
  /usr/bin/python3 - "$file" "$field" <<'PY' 2>/dev/null || echo 0
import datetime
import json
import sys

try:
    value = json.load(open(sys.argv[1], encoding="utf-8")).get(sys.argv[2])
    if not value:
        print(0)
    else:
        text = str(value).replace("Z", "+00:00")
        print(int(datetime.datetime.fromisoformat(text).timestamp()))
except Exception:
    print(0)
PY
}

operator_power_state=$(/usr/bin/python3 - "$POWER_STATE_FILE" <<'PY' 2>/dev/null || echo on
import json
import sys

try:
    print(json.load(open(sys.argv[1], encoding="utf-8")).get("state") or "on")
except Exception:
    print("on")
PY
)

# An explicit `eve.py daemon stop` is an intentional offline state. A crash,
# launchd disable, stale loop, or missing marker while power is expected on is
# not. The guardian remains loaded in either case.
if [[ "$operator_power_state" == "off" ]]; then
  [[ "$CHECK_ONLY" == "1" ]] && echo "EVE OFF: operator power state is off"
  exit 0
fi

disabled_output=$(launchctl print-disabled "$DOMAIN" 2>/dev/null || true)
if echo "$disabled_output" | grep -Fq "\"${EVE_DAEMON_LABEL}\" => disabled"; then
  problems+=("daemon service disabled while operator power state is on")
fi

daemon_output=$(launchctl print "${DOMAIN}/${EVE_DAEMON_LABEL}" 2>/dev/null || true)
if ! echo "$daemon_output" | grep -q 'state = running'; then
  problems+=("daemon process not running")
fi

last_loop=$(json_timestamp_epoch "$DAEMON_STATE" "last_loop_at")
activity_live=$(/usr/bin/python3 - "$DAEMON_ACTIVITY" "$DAEMON_STATE" "$now" <<'PY' 2>/dev/null || echo no
import datetime
import json
import sys

try:
    activity = json.load(open(sys.argv[1], encoding="utf-8"))
    state = json.load(open(sys.argv[2], encoding="utf-8"))
    now = int(sys.argv[3])
    heartbeat = datetime.datetime.fromisoformat(str(activity.get("last_heartbeat_at") or "").replace("Z", "+00:00"))
    started = datetime.datetime.fromisoformat(str(activity.get("cycle_started_at") or "").replace("Z", "+00:00"))
    heartbeat_age = now - int(heartbeat.timestamp())
    cycle_age = now - int(started.timestamp())
    max_cycle = max(180, min(int(activity.get("max_active_cycle_seconds") or 900), 3600))
    expected_pid = int(state.get("daemon_process_id") or 0)
    activity_pid = int(activity.get("pid") or 0)
    ok = (
        activity.get("status") == "active"
        and heartbeat_age <= 60
        and cycle_age <= max_cycle
        and (not expected_pid or activity_pid == expected_pid)
    )
    print("yes" if ok else "no")
except Exception:
    print("no")
PY
)
if [[ "$last_loop" -le 0 ]]; then
  problems+=("daemon loop timestamp missing")
elif [[ $((now - last_loop)) -gt 300 && "$activity_live" != "yes" ]]; then
  problems+=("daemon loop stale $(((now - last_loop) / 60))m")
fi

age=$(age_of "$PRESENCE")
[[ "$age" -gt $((3 * 3600)) ]] && problems+=("presence pulses stale $((age / 3600))h")

age=$(age_of "$GATEWAY_SQLITE")
[[ "$age" -gt $((2 * 3600)) ]] && problems+=("gateway sqlite stale $((age / 3600))h")

down=0
for model_url in "${active_model_urls[@]}"; do
  code=$(curl -s -m 3 -o /dev/null -w '%{http_code}' "${model_url}/v1/models" 2>/dev/null)
  [[ "$code" != "200" ]] && down=$((down + 1))
done
expected_model_substrates=${#active_model_urls[@]}
if [[ "$down" -ge "$expected_model_substrates" ]]; then
  problems+=("all ${expected_model_substrates} active model substrates down under ${model_topology_mode}")
elif [[ "$down" -ge 1 ]]; then
  warns+=("${down}/${expected_model_substrates} active model substrate(s) down under ${model_topology_mode}")
fi

age=$(age_of "$SNAPSHOT")
[[ "$age" -gt $((15 * 60)) ]] && warns+=("system observer snapshot stale $((age / 60))m")

age=$(age_of "$DREAMS")
[[ "$age" -gt $((30 * 3600)) ]] && warns+=("no dream in $((age / 3600))h")

if [[ ${#problems[@]} -eq 0 && ${#warns[@]} -eq 0 ]]; then
  [[ "$CHECK_ONLY" == "1" ]] && echo "EVE OK: topology=${model_topology_mode} active_model_substrates=${expected_model_substrates}"
  exit 0
fi

level="WARN"
[[ ${#problems[@]} -gt 0 ]] && level="CRITICAL"
msg="EVE ${level}: ${problems[*]} ${warns[*]}"

if [[ "$CHECK_ONLY" == "1" ]]; then
  echo "topology=${model_topology_mode} active_model_substrates=${expected_model_substrates} ${msg}"
  [[ "$level" == "CRITICAL" ]] && exit 1
  exit 0
fi

if [[ -f "$COOLDOWN_FILE" ]]; then
  last=$(/usr/bin/python3 -c "import json;print(json.load(open('$COOLDOWN_FILE')).get('ts',0))" 2>/dev/null || echo 0)
  [[ $((now - last)) -lt "$COOLDOWN_SECONDS" ]] && exit 0
fi

/usr/bin/osascript -e "display notification \"${msg}\" with title \"Eve continuity guardian\"" 2>/dev/null || true
if [[ "$level" == "CRITICAL" && -x "$IMSG" && -n "$ALERT_TO" ]]; then
  "$IMSG" send --to "$ALERT_TO" --text "$msg" --service imessage 2>/dev/null || true
fi
mkdir -p "$RUNTIME_APP"
/usr/bin/python3 - "$COOLDOWN_FILE" "$now" "$msg" <<'PY'
import json
import sys

with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump({"ts": int(sys.argv[2]), "msg": sys.argv[3]}, handle)
    handle.write("\n")
PY
exit 0
