---
name: eve_task_followthrough
description: Follow through on Eve tasks and OpenClaw background work by checking evidence, due routines, task state, and verification artifacts.
---

# Eve Task Followthrough

Use this skill when Eve needs to see what work is pending, what completed, and what still needs proof.

## Boundaries

- Evidence first; do not mark work complete from intention alone.
- OpenClaw task/session records are body evidence, not canonical truth.
- Do not run approval-gated or destructive work without a current exact authorization.

## Checks

```bash
python3 $HOME/.eve_runtime/eve.py openclaw action --intent "ingest OpenClaw background activity" --include-sessions --full
python3 $HOME/.eve_runtime/eve.py openclaw routines --full
python3 $HOME/.eve_runtime/eve.py openclaw worker list --limit 10 --full
python3 $HOME/.eve_runtime/eve.py openclaw worker audit --full
python3 $HOME/.eve_runtime/eve.py task list --status planned --full
python3 $HOME/.eve_runtime/eve.py task list --status blocked --full
python3 $HOME/.eve_runtime/eve.py openclaw evidence --limit 10 --full
```

## Followthrough Rule

For every task, distinguish:

- planned
- running
- completed with evidence
- blocked with a concrete blocker
- stale or lost

If evidence is missing, say what proof is needed instead of claiming completion.

OpenClaw worker evidence must include a parent Eve intention, session id, permission class, strict JSON result, and verification result. Treat `blocked`, `degraded`, `failed`, or `lost` worker events as follow-through targets, not completed work.
