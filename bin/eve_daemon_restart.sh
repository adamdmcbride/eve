#!/bin/bash
# Restart Eve's daemon by the book (Rearchitecture Program task 0.2).
#
#   1. Post a board message (bin/codex_coord.py message --from <session> --to all).
#   2. Wait (<= 60 s) until .eve/daemon_activity.json reports status == "idle"
#      between cycles; if the file has no "status" key, wait until its mtime is
#      at least 3 s old.
#   3. Read the owner pid from <runtime dir>/.eve-daemon-owner.json and kill only
#      that pid: TERM first, KILL after 15 s. Never pkill by pattern.
#   4. Start  EVE_STARTED_BY=<session> nohup /usr/bin/python3 eve.py daemon run
#      from the checkout, preserving EVE_TRACE_USAGE when it is set.
#   5. Wait (<= $DAEMON_SUCCESSOR_WATCH s, default 120) for daemon_activity.json
#      to carry the new pid or a newer last_heartbeat_at; exit non-zero otherwise.
#   6. Refuse to run while .eve/daemon_restart_request.json is younger than
#      10 minutes (a self-change handover is in progress).
#
# Environment:
#   EVE_SESSION             board session name (default: eve_daemon_restart)
#   EVE_SOURCE_DIR          the checkout (default: parent of this script's dir)
#   EVE_RUNTIME_DIR         owner-file dir (default: ~/.eve_runtime, same as eve_platform.runtime_dir)
#   EVE_PYTHON              interpreter for the daemon (default: /usr/bin/python3)
#   DAEMON_LOG              successor stdout/stderr (default: /tmp/eve_daemon.log)
#   DAEMON_SUCCESSOR_WATCH  seconds to wait for the successor (default: 120)
#   DAEMON_IDLE_WAIT        seconds to wait for idle (default: 60)
#   EVE_TRACE_USAGE         passed through to the successor when set
#   DRY_RUN=1               print every decision, touch nothing, never wait.
#
# Exit codes: 0 ok; 2 precondition; 3 refused (handover in progress);
#             4 never idle; 5 old daemon would not die; 6 successor did not come alive.

set -u
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EVE_SESSION="${EVE_SESSION:-eve_daemon_restart}"
EVE_SOURCE_DIR="${EVE_SOURCE_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
EVE_RUNTIME_DIR="${EVE_RUNTIME_DIR:-$HOME/.eve_runtime}"
EVE_PYTHON="${EVE_PYTHON:-/usr/bin/python3}"
DAEMON_LOG="${DAEMON_LOG:-/tmp/eve_daemon.log}"
DAEMON_SUCCESSOR_WATCH="${DAEMON_SUCCESSOR_WATCH:-120}"
DAEMON_IDLE_WAIT="${DAEMON_IDLE_WAIT:-60}"
DRY_RUN="${DRY_RUN:-0}"

ACTIVITY_PATH="$EVE_SOURCE_DIR/.eve/daemon_activity.json"
RESTART_REQUEST_PATH="$EVE_SOURCE_DIR/.eve/daemon_restart_request.json"
OWNER_PATH="$EVE_RUNTIME_DIR/.eve-daemon-owner.json"
COORD_SCRIPT="$EVE_SOURCE_DIR/bin/codex_coord.py"
HANDOVER_FRESH_SECONDS=600
IDLE_MTIME_SECONDS=3
TERM_GRACE_SECONDS=15

# ---------------------------------------------------------------- helpers ---

log() { printf '[eve_daemon_restart] %s\n' "$*"; }
die() { log "ERROR: $2"; exit "$1"; }
is_dry() { [ "$DRY_RUN" = "1" ]; }
dry() { log "DRY_RUN: $*"; }

# json_field FILE KEY -> prints the value (empty string for null).
# exit 1 when the key is absent, 2 when the file is unreadable or not JSON.
json_field() {
    "$EVE_PYTHON" - "$1" "$2" <<'PY'
import json, sys
path, key = sys.argv[1], sys.argv[2]
try:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
except (OSError, ValueError):
    sys.exit(2)
if not isinstance(data, dict) or key not in data:
    sys.exit(1)
value = data[key]
print("" if value is None else value)
PY
}

file_age_seconds() {
    "$EVE_PYTHON" -c 'import os, sys, time; print(int(time.time() - os.path.getmtime(sys.argv[1])))' "$1"
}

pid_alive() { kill -0 "$1" 2>/dev/null; }

pid_command() { ps -p "$1" -o command= 2>/dev/null || true; }

# Successor check: activity shows the new pid, or a heartbeat newer than the baseline.
# ISO-8601 UTC strings from utc_now() compare correctly as plain strings.
successor_visible() {
    local new_pid="$1" baseline="$2" pid beat
    pid="$(json_field "$ACTIVITY_PATH" pid 2>/dev/null || true)"
    beat="$(json_field "$ACTIVITY_PATH" last_heartbeat_at 2>/dev/null || true)"
    if [ -n "$pid" ] && [ "$pid" = "$new_pid" ]; then
        return 0
    fi
    if [ -n "$beat" ] && [ "$beat" \> "$baseline" ]; then
        return 0
    fi
    return 1
}

# ---------------------------------------------------------- preconditions ---

log "session=$EVE_SESSION checkout=$EVE_SOURCE_DIR runtime_dir=$EVE_RUNTIME_DIR dry_run=$DRY_RUN"

[ -d "$EVE_SOURCE_DIR" ] || die 2 "checkout not found: $EVE_SOURCE_DIR"
if [ ! -f "$EVE_SOURCE_DIR/eve.py" ]; then
    if is_dry; then
        dry "eve.py is missing from $EVE_SOURCE_DIR (a real run would stop here)"
    else
        die 2 "eve.py not found in $EVE_SOURCE_DIR"
    fi
fi

# (6) A self-change handover in progress owns the restart; do not race it.
if [ -f "$RESTART_REQUEST_PATH" ]; then
    request_age="$(file_age_seconds "$RESTART_REQUEST_PATH")"
    if [ "$request_age" -lt "$HANDOVER_FRESH_SECONDS" ]; then
        die 3 "refusing to restart: $RESTART_REQUEST_PATH is ${request_age}s old (< ${HANDOVER_FRESH_SECONDS}s); a self-change handover is in progress"
    fi
    log "stale restart request (${request_age}s old) at $RESTART_REQUEST_PATH; ignoring it"
fi

# ---------------------------------------------------------- (1) board post ---

board_body="Restarting Eve's daemon from $EVE_SOURCE_DIR; successor will carry EVE_STARTED_BY=$EVE_SESSION."
if is_dry; then
    dry "would run: python3 $COORD_SCRIPT message --from $EVE_SESSION --to all --body \"$board_body\""
else
    [ -f "$COORD_SCRIPT" ] || die 2 "board script not found: $COORD_SCRIPT"
    (cd "$EVE_SOURCE_DIR" && python3 "$COORD_SCRIPT" message --from "$EVE_SESSION" --to all --body "$board_body") \
        || die 2 "board message failed"
fi

# ------------------------------------------------------- (2) wait for idle ---

# Returns 0 when the daemon is idle between cycles (or has no activity file at all).
activity_idle() {
    local status
    if [ ! -f "$ACTIVITY_PATH" ]; then
        return 0
    fi
    status="$(json_field "$ACTIVITY_PATH" status)"
    case $? in
        0)
            [ "$status" = "idle" ]
            ;;
        1)
            [ "$(file_age_seconds "$ACTIVITY_PATH")" -ge "$IDLE_MTIME_SECONDS" ]
            ;;
        *)
            # Unreadable or mid-write: treat as busy and let the loop retry.
            return 1
            ;;
    esac
}

describe_activity() {
    local status
    if [ ! -f "$ACTIVITY_PATH" ]; then
        echo "no activity file at $ACTIVITY_PATH (nothing to wait for)"
        return
    fi
    status="$(json_field "$ACTIVITY_PATH" status)"
    case $? in
        0) echo "status=$status (need idle) pid=$(json_field "$ACTIVITY_PATH" pid 2>/dev/null || true) last_heartbeat_at=$(json_field "$ACTIVITY_PATH" last_heartbeat_at 2>/dev/null || true)" ;;
        1) echo "no status key; mtime age $(file_age_seconds "$ACTIVITY_PATH")s (need >= ${IDLE_MTIME_SECONDS}s)" ;;
        *) echo "activity file unreadable" ;;
    esac
}

if is_dry; then
    if activity_idle; then
        dry "daemon is idle now: $(describe_activity)"
    else
        dry "daemon is not idle: $(describe_activity); a real run would wait up to ${DAEMON_IDLE_WAIT}s"
    fi
else
    waited=0
    until activity_idle; do
        if [ "$waited" -ge "$DAEMON_IDLE_WAIT" ]; then
            die 4 "daemon did not go idle within ${DAEMON_IDLE_WAIT}s: $(describe_activity)"
        fi
        sleep 1
        waited=$((waited + 1))
    done
    log "daemon idle after ${waited}s: $(describe_activity)"
fi

# ---------------------------------------------------- (3) stop the owner ---

owner_pid=""
if [ -f "$OWNER_PATH" ]; then
    owner_pid="$(json_field "$OWNER_PATH" pid 2>/dev/null || true)"
    owner_status="$(json_field "$OWNER_PATH" status 2>/dev/null || true)"
    log "owner file: pid=${owner_pid:-none} status=${owner_status:-unknown}"
else
    log "no owner file at $OWNER_PATH; nothing to stop"
fi

case "$owner_pid" in
    ''|*[!0-9]*)
        owner_pid=""
        log "no numeric owner pid; skipping the stop step"
        ;;
esac

if [ -n "$owner_pid" ]; then
    if is_dry; then
        dry "would send TERM to pid $owner_pid (only that pid), then KILL after ${TERM_GRACE_SECONDS}s if still alive"
    elif ! pid_alive "$owner_pid"; then
        log "owner pid $owner_pid is not running; nothing to stop"
    else
        owner_cmd="$(pid_command "$owner_pid")"
        case "$owner_cmd" in
            *"eve.py daemon run"*) ;;
            *) die 5 "pid $owner_pid is not an eve.py daemon run process (command: ${owner_cmd:-unknown}); refusing to kill it" ;;
        esac
        log "sending TERM to pid $owner_pid"
        kill -TERM "$owner_pid" 2>/dev/null || true
        waited=0
        while pid_alive "$owner_pid" && [ "$waited" -lt "$TERM_GRACE_SECONDS" ]; do
            sleep 1
            waited=$((waited + 1))
        done
        if pid_alive "$owner_pid"; then
            log "pid $owner_pid still alive after ${TERM_GRACE_SECONDS}s; sending KILL"
            kill -KILL "$owner_pid" 2>/dev/null || true
            waited=0
            while pid_alive "$owner_pid" && [ "$waited" -lt 5 ]; do
                sleep 1
                waited=$((waited + 1))
            done
            pid_alive "$owner_pid" && die 5 "pid $owner_pid survived KILL"
        fi
        log "pid $owner_pid stopped after ${waited}s"
    fi
fi

# ---------------------------------------------------- (4) start successor ---

# Baseline heartbeat for the successor watch. Captured only after the old owner
# is gone: cycle_activity.persist() (eve_daemon_runtime.py) refreshes
# last_heartbeat_at on every status write, including the cycle end that follows
# a TERM, so an earlier baseline could be beaten by the old daemon's last write.
baseline_heartbeat="$(json_field "$ACTIVITY_PATH" last_heartbeat_at 2>/dev/null || true)"

start_cmd="EVE_STARTED_BY=$EVE_SESSION nohup $EVE_PYTHON eve.py daemon run >> $DAEMON_LOG 2>&1 &"
if [ -n "${EVE_TRACE_USAGE:-}" ]; then
    export EVE_TRACE_USAGE
    start_cmd="EVE_TRACE_USAGE=$EVE_TRACE_USAGE $start_cmd"
fi

if is_dry; then
    dry "would run from $EVE_SOURCE_DIR: $start_cmd"
    dry "would then wait up to ${DAEMON_SUCCESSOR_WATCH}s for $ACTIVITY_PATH to show the new pid or a heartbeat newer than ${baseline_heartbeat:-<none>}"
    dry "nothing was touched"
    exit 0
fi

cd "$EVE_SOURCE_DIR" || die 2 "cannot cd to $EVE_SOURCE_DIR"
export EVE_STARTED_BY="$EVE_SESSION"
nohup "$EVE_PYTHON" eve.py daemon run >> "$DAEMON_LOG" 2>&1 < /dev/null &
new_pid=$!
log "started successor pid $new_pid: $start_cmd"

# ------------------------------------------------ (5) watch the successor ---

waited=0
while [ "$waited" -lt "$DAEMON_SUCCESSOR_WATCH" ]; do
    if successor_visible "$new_pid" "$baseline_heartbeat"; then
        log "successor alive after ${waited}s: $(describe_activity)"
        # macOS pgrep has no -c; count the matching pids instead.
        log "runners matching 'eve.py daemon run': $(pgrep -f "eve.py daemon run" 2>/dev/null | wc -l | tr -d ' ')"
        exit 0
    fi
    if ! pid_alive "$new_pid"; then
        log "successor pid $new_pid exited early; last lines of $DAEMON_LOG:"
        tail -n 20 "$DAEMON_LOG" 2>/dev/null || true
        die 6 "successor did not stay alive (a lease holder may still be running: exit 75 means the runner lease was refused)"
    fi
    sleep 3
    waited=$((waited + 3))
done

log "last lines of $DAEMON_LOG:"
tail -n 20 "$DAEMON_LOG" 2>/dev/null || true
die 6 "successor pid $new_pid did not appear in $ACTIVITY_PATH within ${DAEMON_SUCCESSOR_WATCH}s: $(describe_activity)"
