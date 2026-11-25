#!/bin/bash
# Eve guardian (alert-only until Eve leaves ~/Documents): launchd cannot read ~/Documents on this Mac,
# so this watch can only see whether the daemon process exists and raise the alarm. It lives in
# ~/.eve_runtime so launchd can execute it. Restart from source happens in a terminal or by Eve herself.
set -u
LOG="${HOME}/.eve_runtime/.eve/guardian.log"; ALERT="${HOME}/.eve_runtime/.eve/guardian_alert.json"
mkdir -p "$(dirname "$LOG")"
log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$LOG"; }
running=$(pgrep -f "eve.py daemon run" | head -1 || true)
lanes_down=""
for port in 8080 8081 8082; do /usr/bin/curl -s -m 3 "http://127.0.0.1:${port}/health" >/dev/null 2>&1 || lanes_down="${lanes_down} ${port}"; done
if [ -n "$running" ] && [ -z "$lanes_down" ]; then rm -f "$ALERT"; exit 0; fi
msg="daemon: ${running:-DOWN}; lanes down:${lanes_down:- none}"
log "$msg"
last_alert=0; [ -f "$ALERT" ] && last_alert=$(stat -f %m "$ALERT")
if [ $(( $(date -u +%s) - last_alert )) -ge 3600 ]; then
  printf '{"at":"%s","daemon":"%s","lanes_down":"%s"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${running:-DOWN}" "${lanes_down# }" > "$ALERT"
  /usr/bin/osascript -e "display notification \"${msg}\" with title \"Eve guardian\" subtitle \"Eve needs a restart from a terminal\"" 2>/dev/null || true
fi
exit 0
