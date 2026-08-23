#!/bin/zsh

set -euo pipefail

HOME_DIR="${HOME}"
RUNTIME_DIR="${HOME_DIR}/.eve_runtime"
PYTHON_BIN="/Library/Developer/CommandLineTools/usr/bin/python3"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="$(command -v python3)"
fi

EVE_PY="${RUNTIME_DIR}/eve.py"
DESKTOP_APP="${HOME_DIR}/Applications/Eve.app"
EVE_CONTROL_APP_PROCESS="Eve Control"
LAUNCH_AGENT_DIR="${HOME_DIR}/Library/LaunchAgents"
HOST="127.0.0.1"
PORT="8787"
BASE_URL="http://${HOST}:${PORT}"
API_URL="${BASE_URL}/api/status"
LOG_DIR="${RUNTIME_DIR}/.eve/logs"
WEB_OUT="${LOG_DIR}/web.out.log"
WEB_ERR="${LOG_DIR}/web.err.log"
API_VERSION="5"

mkdir -p "${LOG_DIR}"

MODEL_TOPOLOGY_HELPER="${RUNTIME_DIR}/eve_model_topology.py"
PROFILE_HELPER="${RUNTIME_DIR}/eve_profile.py"
if [[ -r "${PROFILE_HELPER}" ]]; then
  EVE_SERVICE_NAMESPACE="$("${PYTHON_BIN}" "${PROFILE_HELPER}" namespace 2>/dev/null || true)"
fi
EVE_SERVICE_NAMESPACE="${EVE_SERVICE_NAMESPACE:-local.eve}"
service_label() {
  local suffix="${1:-}"
  if [[ -z "${suffix}" ]]; then
    echo "${EVE_SERVICE_NAMESPACE}"
  elif [[ "${suffix}" == .* || "${suffix}" == -* ]]; then
    echo "${EVE_SERVICE_NAMESPACE}${suffix}"
  else
    echo "${EVE_SERVICE_NAMESPACE}-${suffix}"
  fi
}

load_model_topology_contract() {
  if [[ ! -r "${MODEL_TOPOLOGY_HELPER}" ]]; then
    return 1
  fi
  local contract
  contract="$("${PYTHON_BIN}" "${MODEL_TOPOLOGY_HELPER}" shell 2>/dev/null)" || return 1
  eval "${contract}"
  [[ "${EVE_MODEL_TOPOLOGY_VALID:-0}" == "1" ]]
}

if ! load_model_topology_contract; then
  EVE_MODEL_TOPOLOGY_MODE="five_endpoint"
  MODEL_LANE_ACTIVE_LABELS=(
    "$(service_label llama-cpp)"
    "$(service_label llama-cpp-deep)"
    "$(service_label llama-cpp-observer)"
    "$(service_label llama-cpp-planner)"
    "$(service_label llama-cpp-relationship)"
  )
  MODEL_LANE_INACTIVE_LABELS=()
  MODEL_LANE_ALL_LABELS=("${MODEL_LANE_ACTIVE_LABELS[@]}")
  EVE_ACTIVE_MODEL_PROFILES=(fast deep observer planner relationship)
  EVE_ACTIVE_MODEL_URLS=(
    "http://127.0.0.1:8080"
    "http://127.0.0.1:8081"
    "http://127.0.0.1:8082"
    "http://127.0.0.1:8083"
    "http://127.0.0.1:8084"
  )
  EVE_ALL_MODEL_PORTS=(8080 8081 8082 8083 8084)
fi
MODEL_LANE_LABELS=("${MODEL_LANE_ALL_LABELS[@]}")
AUX_SERVICE_LABELS=(
  "$(service_label system-observer)"
  "$(service_label lived-note)"
  "$(service_label .chat-backend)"
  "$(service_label menu)"
  "$(service_label .control.core)"
  "$(service_label .control.runtime)"
  "ai.openclaw.eve-repair"
)
EVE_MODEL_PORTS=("${EVE_ALL_MODEL_PORTS[@]}")
OPENCLAW_PORTS=(19011)
EVE_OPENCLAW_PROCESS_PATTERN='eve\.py openclaw|OPENCLAW_GATEWAY_PORT=19011|OPENCLAW_PROFILE=eve-repair|\.openclaw-eve-repair|--profile[ =]eve-repair|--port[ =]19011'
EVE_CONTROL_PORTS=(8765 11481)

launch_domain() {
  echo "gui/$(id -u)"
}

launch_target() {
  echo "$(launch_domain)/${1}"
}

agent_plist() {
  echo "${LAUNCH_AGENT_DIR}/${1}.plist"
}

disable_agent() {
  local label="${1}"
  local plist
  plist="$(agent_plist "${label}")"
  if [[ -f "${plist}" ]]; then
    launchctl bootout "$(launch_domain)" "${plist}" >/dev/null 2>&1 || true
  fi
  launchctl disable "$(launch_target "${label}")" >/dev/null 2>&1 || true
}

enable_agent() {
  local label="${1}"
  local plist
  plist="$(agent_plist "${label}")"
  if [[ ! -f "${plist}" ]]; then
    return 0
  fi
  launchctl enable "$(launch_target "${label}")" >/dev/null 2>&1 || true
  launchctl bootstrap "$(launch_domain)" "${plist}" >/dev/null 2>&1 || \
    launchctl kickstart -k "$(launch_target "${label}")" >/dev/null 2>&1 || true
}

stop_eve_model_ports() {
  local port pids
  for port in "${EVE_MODEL_PORTS[@]}"; do
    pids="$(lsof -ti "tcp:${port}" -sTCP:LISTEN 2>/dev/null || true)"
    if [[ -n "${pids}" ]]; then
      echo "${pids}" | xargs kill >/dev/null 2>&1 || true
    fi
  done
}

stop_eve_temp_model_servers() {
  local port pids pid
  for port in {18180..18199}; do
    pids="$(lsof -ti "tcp:${port}" -sTCP:LISTEN 2>/dev/null || true)"
    if [[ -n "${pids}" ]]; then
      echo "${pids}" | xargs kill >/dev/null 2>&1 || true
    fi
  done

  for pid in "${(@f)$(pgrep -f 'EVE_MODEL_HOST_OVERRIDES|\.eve/model_temp_servers|eve-[a-z-]*candidate' 2>/dev/null || true)}"; do
    if [[ -n "${pid}" && "${pid}" != "$$" ]]; then
      kill "${pid}" >/dev/null 2>&1 || true
    fi
  done
}

stop_openclaw_ports() {
  local port pids
  for port in "${OPENCLAW_PORTS[@]}"; do
    pids="$(lsof -ti "tcp:${port}" -sTCP:LISTEN 2>/dev/null || true)"
    if [[ -n "${pids}" ]]; then
      echo "${pids}" | xargs kill >/dev/null 2>&1 || true
    fi
  done
}

stop_openclaw_processes() {
  local pid
  for pid in "${(@f)$(pgrep -f "${EVE_OPENCLAW_PROCESS_PATTERN}" 2>/dev/null || true)}"; do
    if [[ -n "${pid}" && "${pid}" != "$$" ]]; then
      kill "${pid}" >/dev/null 2>&1 || true
    fi
  done
}

stop_eve_control_app() {
  if pgrep -x "${EVE_CONTROL_APP_PROCESS}" >/dev/null 2>&1; then
    pkill -x "${EVE_CONTROL_APP_PROCESS}" >/dev/null 2>&1 || true
    for _ in {1..20}; do
      if ! pgrep -x "${EVE_CONTROL_APP_PROCESS}" >/dev/null 2>&1; then
        return 0
      fi
      sleep 0.25
    done
    pkill -9 -x "${EVE_CONTROL_APP_PROCESS}" >/dev/null 2>&1 || true
  fi
}

stop_eve_control_ports() {
  local port pids
  for port in "${EVE_CONTROL_PORTS[@]}"; do
    pids="$(lsof -ti "tcp:${port}" -sTCP:LISTEN 2>/dev/null || true)"
    if [[ -n "${pids}" ]]; then
      echo "${pids}" | xargs kill >/dev/null 2>&1 || true
    fi
  done
}

stop_background_agents() {
  local label
  for label in "${AUX_SERVICE_LABELS[@]}" "${MODEL_LANE_LABELS[@]}"; do
    disable_agent "${label}"
  done
  stop_eve_control_app
  stop_eve_model_ports
  stop_eve_temp_model_servers
  stop_openclaw_ports
  stop_openclaw_processes
  stop_eve_control_ports
}

start_background_agents() {
  local label
  for label in "${MODEL_LANE_INACTIVE_LABELS[@]}"; do
    disable_agent "${label}"
  done
  for label in "${AUX_SERVICE_LABELS[@]}" "${MODEL_LANE_ACTIVE_LABELS[@]}"; do
    enable_agent "${label}"
  done
}

wait_for_port() {
  local name="${1}"
  local port="${2}"
  local timeout_seconds="${3}"
  local elapsed=0
  while [[ "${elapsed}" -lt "${timeout_seconds}" ]]; do
    if lsof -ti "tcp:${port}" -sTCP:LISTEN >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  echo "${name} did not start listening on port ${port} within ${timeout_seconds}s." >&2
  return 1
}

wait_for_http() {
  local name="${1}"
  local url="${2}"
  local timeout_seconds="${3}"
  local elapsed=0
  while [[ "${elapsed}" -lt "${timeout_seconds}" ]]; do
    if curl -sf --max-time 2 "${url}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  echo "${name} did not become ready at ${url} within ${timeout_seconds}s." >&2
  return 1
}

wait_for_power_on_services() {
  local index profile url
  wait_for_http "Eve monitor API" "${API_URL}" 20
  wait_for_http "Eve Chat backend" "http://127.0.0.1:8797/v1/models" 45
  wait_for_port "OpenClaw gateway" 19011 45
  wait_for_http "Eve Control core" "http://127.0.0.1:8765/v1/health" 45
  for ((index = 1; index <= ${#EVE_ACTIVE_MODEL_URLS[@]}; index++)); do
    profile="${EVE_ACTIVE_MODEL_PROFILES[index]}"
    url="${EVE_ACTIVE_MODEL_URLS[index]}"
    wait_for_http "${profile} model substrate" "${url}/v1/models" 180
  done
}

ensure_runtime() {
  if [[ ! -f "${EVE_PY}" ]]; then
    echo "Eve runtime not found at ${EVE_PY}" >&2
    exit 1
  fi
}

daemon_start() {
  ensure_runtime
  "${PYTHON_BIN}" "${EVE_PY}" daemon start >/dev/null 2>&1 || \
    "${PYTHON_BIN}" "${EVE_PY}" daemon install >/dev/null 2>&1 || true
}

daemon_start_required() {
  ensure_runtime
  "${PYTHON_BIN}" "${EVE_PY}" daemon start >/dev/null 2>&1 || \
    "${PYTHON_BIN}" "${EVE_PY}" daemon install >/dev/null 2>&1
}

daemon_stop() {
  ensure_runtime
  "${PYTHON_BIN}" "${EVE_PY}" daemon stop >/dev/null 2>&1 || true
}

power_on() {
  daemon_start_required
  start_background_agents
  ensure_web
  wait_for_power_on_services
}

power_off() {
  daemon_stop
  stop_background_agents
  stop_web
}

web_up() {
  curl -sf "${API_URL}" >/dev/null 2>&1
}

web_compatible() {
  curl -sf "${API_URL}" 2>/dev/null | grep -q "\"api_version\": ${API_VERSION}"
}

stop_web() {
  local pids
  pids="$(lsof -ti "tcp:${PORT}" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "${pids}" ]]; then
    echo "${pids}" | xargs kill >/dev/null 2>&1 || true
    for _ in {1..20}; do
      if ! lsof -ti "tcp:${PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
        break
      fi
      sleep 0.25
    done
  fi

  if lsof -ti "tcp:${PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
    lsof -ti "tcp:${PORT}" -sTCP:LISTEN | xargs kill -9 >/dev/null 2>&1 || true
    sleep 0.25
  fi
}

ensure_web() {
  ensure_runtime
  if web_up && web_compatible; then
    return 0
  fi

  if web_up && ! web_compatible; then
    stop_web
  fi

  EVE_HELPER_RUNTIME_DIR="${RUNTIME_DIR}" \
  EVE_HELPER_PYTHON="${PYTHON_BIN}" \
  EVE_HELPER_SCRIPT="${EVE_PY}" \
  EVE_HELPER_HOST="${HOST}" \
  EVE_HELPER_PORT="${PORT}" \
  EVE_HELPER_WEB_OUT="${WEB_OUT}" \
  EVE_HELPER_WEB_ERR="${WEB_ERR}" \
    "${PYTHON_BIN}" - <<'PY'
import os
import subprocess

cmd = [
    os.environ["EVE_HELPER_PYTHON"],
    os.environ["EVE_HELPER_SCRIPT"],
    "app",
    "--host",
    os.environ["EVE_HELPER_HOST"],
    "--port",
    os.environ["EVE_HELPER_PORT"],
]

with open(os.devnull, "rb") as devnull, open(os.environ["EVE_HELPER_WEB_OUT"], "ab") as stdout_handle, open(
    os.environ["EVE_HELPER_WEB_ERR"], "ab"
) as stderr_handle:
    subprocess.Popen(
        cmd,
        cwd=os.environ["EVE_HELPER_RUNTIME_DIR"],
        stdin=devnull,
        stdout=stdout_handle,
        stderr=stderr_handle,
        start_new_session=True,
        close_fds=True,
    )
PY

  for _ in {1..50}; do
    if web_up && web_compatible; then
      return 0
    fi
    sleep 0.2
  done

  echo "Eve web app did not start in time." >&2
  exit 1
}

open_eve() {
  ensure_web

  if [[ -d "${DESKTOP_APP}" ]]; then
    open "${DESKTOP_APP}"
    return 0
  fi

  open "${BASE_URL}/"
}

run_reflection() {
  ensure_runtime
  "${PYTHON_BIN}" "${EVE_PY}" reflect --days 30 >/dev/null
}

draft_proposal() {
  ensure_runtime
  "${PYTHON_BIN}" "${EVE_PY}" proposal suggest >/dev/null
}

think_now() {
  ensure_runtime
  "${PYTHON_BIN}" "${EVE_PY}" think >/dev/null
}

status_json() {
  ensure_runtime
  if web_up; then
    curl -sf "${BASE_URL}/api/status"
    exit 0
  fi

  if [[ -f "${RUNTIME_DIR}/.eve/state.json" ]]; then
    cat "${RUNTIME_DIR}/.eve/state.json"
  else
    echo "{}"
  fi
}

open_logs() {
  ensure_runtime
  open -a TextEdit "${WEB_OUT}" "${WEB_ERR}" "${RUNTIME_DIR}/.eve/logs/daemon.err.log" "${RUNTIME_DIR}/.eve/logs/daemon.out.log"
}

show_usage() {
  cat <<'EOF'
Usage: eve_control.sh <command>

Commands:
  open            Start the local interface if needed, then open Eve
  inbox           Alias for open
  reflect         Run a reflection now
  think           Generate one thought now
  proposal        Draft a proposal now
  power-on        Enable Eve background services and start the monitor API
  power-off       Stop Eve and keep background services off across login
  daemon-start    Start Eve daemon
  daemon-stop     Stop Eve daemon
  web-restart     Restart Eve web server
  logs            Open Eve logs
  status-json     Print status JSON
EOF
}

case "${1:-open}" in
  open)
    open_eve
    ;;
  inbox)
    open_eve
    ;;
  reflect)
    run_reflection
    ;;
  think)
    think_now
    ;;
  proposal)
    draft_proposal
    ;;
  power-on)
    power_on
    ;;
  power-off)
    power_off
    ;;
  daemon-start)
    daemon_start
    ;;
  daemon-stop)
    daemon_stop
    ;;
  web-restart)
    stop_web
    ensure_web
    ;;
  logs)
    open_logs
    ;;
  status-json)
    status_json
    ;;
  *)
    show_usage
    exit 1
    ;;
esac
