---
name: eve-evidence-ingest
description: "Record OpenClaw lifecycle and command hook events into Eve's body-bus evidence bridge"
homepage: https://docs.openclaw.ai/automation/hooks
metadata:
  {
    "openclaw":
      {
        "emoji": "E",
        "events": ["gateway:startup", "command"],
        "requires": { "config": ["workspace.dir"] },
      },
  }
---

# Eve Evidence Ingest Hook

This workspace hook records OpenClaw lifecycle and command events into Eve's evidence bridge.

It is intentionally evidence-only:

- It does not send messages.
- It does not install plugins, MCP servers, ACP agents, or sub-agents.
- It does not grant OpenClaw canonical memory authority.
- It delegates sanitization and evidence writing to `python3 eve.py openclaw evidence`.
- It ignores Eve-originated evidence-ingest events and debounces duplicate callbacks in `.eve/openclaw_hook_ingest_state.json`.
- It treats `command` as OpenClaw internal command hooks such as `/new` and `/reset`, not ordinary `openclaw status` or `openclaw hooks list` CLI calls.
