---
name: eve_system_sensing
description: Sense Eve's live body state through bounded status, routine, model, memory, and OpenClaw checks without changing system state.
---

# Eve System Sensing

Use this skill when Eve needs to understand what is happening in her local body before deciding or replying.

## Boundaries

- Read-only by default.
- Do not install, update, delete, send messages, change models, change auth, or alter provider settings.
- If a check reports an old recovered failure, treat it as history unless the current status is degraded.

## Checks

```bash
python3 $HOME/.eve_runtime/eve.py openclaw status
python3 $HOME/.eve_runtime/eve.py openclaw action --intent "check OpenClaw body health" --full
python3 $HOME/.eve_runtime/eve.py openclaw routines --record-skips --full
python3 $HOME/.eve_runtime/eve.py capabilities map --status --runtime --full --query openclaw_action_router
python3 $HOME/.eve_runtime/eve.py infra metrics --timeout 2
```

## Output Contract

Answer with:

- current body state
- what changed, if anything
- why it matters
- one bounded next step

Do not let system status hijack a human conversation unless the status is actually relevant or degraded.
