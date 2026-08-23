---
name: eve_control_home
description: Talk to Eve Control and Eve Home through the local runtime-core API for bounded home snapshots and verified device control.
---

# Eve Control / Eve Home

Use this skill when the user asks Eve to inspect Eve Control, read the current Eve Home state, or control a known home device through the local Eve Control runtime.

This skill lives in Eve/OpenClaw, not Codex. Codex may implement or audit the bridge, but Eve's operational path is the local runtime-core API plus the Eve-owned bridge command below.

`Eve Control.app` is the consumer-facing app. Eve must not require that app to be open, focused, clicked, or automated before controlling devices. Eve controls devices through headless runtime-core.

## Local Bridge

Primary command:

```bash
python3 $HOME/.eve_runtime/bin/eve_control_bridge.py status --json
python3 $HOME/.eve_runtime/bin/eve_control_bridge.py home status --json
python3 $HOME/.eve_runtime/bin/eve_control_bridge.py home start --json
python3 $HOME/.eve_runtime/bin/eve_control_bridge.py home stop --json
python3 $HOME/.eve_runtime/bin/eve_control_bridge.py snapshot --controllable-only --json
python3 $HOME/.eve_runtime/bin/eve_control_bridge.py control --entity-id light.kitchen --service turn_on --dry-run --json
```

The bridge talks to the Eve Control runtime-core service at `http://127.0.0.1:8765` by default. If that default local runtime is down, the bridge may start it headlessly through `${EVE_HOME_ROOT:-$HOME/Documents/EveHomeNative}/bin/run_eve_core.sh start`; this does not open the consumer app. Override with `EVE_CONTROL_RUNTIME_URL` or `--runtime-url` when the user names another paired Eve Hub.

The bridge can also manage the default local Eve Home backend through `${EVE_HOME_ROOT:-$HOME/Documents/EveHomeNative}/bin/run_eve.sh`. Snapshot and real control commands may auto-start that backend when it is local and down. Dry-runs do not need Eve Home to be reachable.

Runtime-core then talks to Eve Home/Home Assistant locally through the trusted-network route and exposes:

- `GET /v1/home/snapshot`
- `POST /v1/home/control`

## Control Rule

Control requires a concrete local target and an allowlisted service.

Eve may run a dry-run when the target appears unambiguous. Eve may send the real command only when the user's request clearly asks for that exact action, or when an active trusted operator directive covers the exact bounded action.

Allowed service classes are intentionally boring and device-shaped: lights, switches, fans, media players, covers, locks, buttons, selects, numbers, scenes, scripts, automations, and climate controls. The runtime rejects services outside its allowlist.

## Operating Pattern

1. Check the bridge:
   - `python3 $HOME/.eve_runtime/bin/eve_control_bridge.py status --json`
2. Check Eve Home if state reads fail:
   - `python3 $HOME/.eve_runtime/bin/eve_control_bridge.py home status --json`
3. Start Eve Home if the default local backend is down:
   - `python3 $HOME/.eve_runtime/bin/eve_control_bridge.py home start --json`
4. Read controllable state:
   - `python3 $HOME/.eve_runtime/bin/eve_control_bridge.py snapshot --controllable-only --json`
5. Match the user's wording to one specific `entityId`, `domain`, and `service`.
6. If uncertain, stop and ask which device or room the user means.
7. If the action is exact, dry-run first:
   - `python3 $HOME/.eve_runtime/bin/eve_control_bridge.py control --entity-id <entity_id> --service <service> --dry-run --json`
8. Send only the exact action:
   - `python3 $HOME/.eve_runtime/bin/eve_control_bridge.py control --entity-id <entity_id> --service <service> --json`
9. Re-read the snapshot or relevant entity state before claiming the command worked.

## Boundaries

- Do not use Codex as the runtime control path.
- Do not open or automate `Eve Control.app` as a prerequisite for device control.
- Do not bypass Eve Control runtime-core to mutate devices directly unless the user explicitly asks for a lower-level diagnostic.
- Do not use provider clouds, external sends, credentials, purchases, security-sensitive settings, or destructive operations through this skill.
- Do not control locks, alarms, cameras, sirens, microphones, speakers, or security modes unless the user's exact target and action are explicit and the runtime route is verified.
- Do not infer rich Eufy/Tuya capabilities from discovery alone. Discovery evidence can identify a device; control requires a verified route.
- Do not claim completion from a dry-run. A dry-run proves only that the command shape is accepted.

## Good Answer Shape

```text
I found the local Eve Home route and dry-ran light.kitchen turn_on successfully. I sent the command, then re-read state and Home Assistant now reports light.kitchen as on.
```

If blocked:

```text
I can see the bridge, but kitchen_ceiling and kitchen_lamp both match. Which exact one should I control?
```
