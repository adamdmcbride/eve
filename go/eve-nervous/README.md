# Eve Nervous System Worker

This is Eve's first small Go runtime component. It is intentionally narrow:

- writes `nervous.heartbeat` events into Eve's SQLite event spine
- enqueues safe `tool.job.requested` records
- claims one pending tool job and records `tool.job.completed` / `tool.job.failed`
- writes an explicit `action.result.recorded` event for downstream Python, UI, or future workers
- accepts feature-only auditory, visual, and proprioceptive observations from admitted local adapters
- runs a bounded supervised loop with duration, max-job, heartbeat, interval, and idle-backoff limits

It uses the same `.lock` file convention as `eve_db.py` before SQLite writes, so it can coexist with the Python daemon.

Run from the repo root through Eve's normal CLI:

```sh
python3 eve.py infra nervous heartbeat
python3 eve.py infra nervous enqueue --tool echo --message "hello"
python3 eve.py infra nervous once
python3 eve.py infra nervous run --duration 30 --max-jobs 10
python3 eve.py infra events --stream action
```

The worker can also be run directly:

```sh
go run ./go/eve-nervous --db .eve/operational_state.sqlite3 once
go run ./go/eve-nervous --db .eve/operational_state.sqlite3 run --duration 30s --max-jobs 10
```

## Sensory adapter boundary

The `sense` command is a hardware-adapter bridge, not a camera or microphone
recorder. It only accepts a fixed feature schema after Eve has created an
explicit, time-bounded sensory session. The high-entropy session token must be
passed through an environment variable or a local token file so it does not
appear in the process list. A token file must be a regular file with mode
`0600` (or stricter).

```sh
export EVE_SENSORY_SESSION_TOKEN='<token returned by the local session API>'
go run ./go/eve-nervous --db .eve/operational_state.sqlite3 sense \
  --session sensory-... \
  --modality proprioceptive \
  --features-json '{"contact_count":1,"force_percent":22,"actuator_state":"idle"}'
```

Auditory and visual events additionally require `--permission`, which asserts
that the device adapter currently holds OS permission. Unknown features and raw
audio, pixels, transcripts, OCR, screen content, or key values are rejected.
The built-in Eve app can provide microphone, camera, and aggregate interaction
features. Physical touch, position, or actuator feedback still requires an
actual hardware adapter to call this bridge.

Daemon supervision is owned by Python. When `nervous_system_enabled=true`, `run_daemon_cycle` invokes this worker periodically with the configured duration, max-job, interval, heartbeat, and idle-backoff limits.
