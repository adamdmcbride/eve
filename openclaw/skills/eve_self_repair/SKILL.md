---
name: eve_self_repair
description: Repair Eve in bounded, verified steps using the repo's own doctor, task, maintenance, proposal, and failure surfaces.
---

# Eve Self Repair

Use this skill whenever the task is to repair, stabilize, maintain, or verify Eve.

`openclaw/AGENTS.md` is intentionally a compact dispatch card. Keep detailed repair procedure here so OpenClaw's always-injected bootstrap stays small and this skill is loaded only when repair work needs it.

## Repo Facts

- Repo root: `$HOME/.eve_runtime`
- OpenClaw workspace root: `$HOME/.eve_runtime/openclaw`
- Preferred command root: `$HOME/.eve_runtime` when `$HOME/.eve_runtime/eve.py` exists; use the source repo only as a fallback.
- Repair agent scope: `agent:eve-repair:*` sessions under `~/.openclaw-eve-repair/agents/eve-repair/sessions/`.
- Repair bootstrap: `bootstrapMaxChars=4000`, `bootstrapTotalMaxChars=12000`, `contextInjection=continuation-skip`, `toolResultMaxChars=6000`; if the session reports truncation or context overflow, treat that as a repair-wrapper/config issue.
- Long tool-heavy turns use OpenClaw's own context controls: `agents.defaults.compaction.mode=safeguard`, `agents.defaults.compaction.midTurnPrecheck.enabled=true`, `agents.defaults.contextPruning.mode=cache-ttl`, `agents.defaults.contextPruning.ttl=1m`, and `tools.loopDetection.enabled=true`. Verify these through the active `eve-repair` profile instead of attempting to recreate them in Eve code.
- Supported OpenClaw `contextLimits` keys are `memoryGetMaxChars`, `memoryGetDefaultLines`, `toolResultMaxChars`, and `postCompactionMaxChars`. Do not recommend unsupported keys such as `contextWindow`, `contextWindowLimit`, or `maxContext`.
- Runtime status snapshot:
  - `$HOME/.eve_runtime/openclaw/context/eve_status_brief.md`
  - `$HOME/.eve_runtime/openclaw/context/eve_status_brief.json`
  - `$HOME/.eve_runtime/openclaw/context/eve_status.md`
  - `$HOME/.eve_runtime/openclaw/context/eve_status.json`

## Workflow

1. Classify the repair budget and authority first. Most repairs are `operational`; use `analytical` only for repeated or unclear failures. Do not turn repair into a broad architecture pass unless the evidence requires it.
2. Refresh the snapshot first:
   ```bash
   python3 $HOME/.eve_runtime/bin/eve_openclaw_sync.py --workspace $HOME/.eve_runtime/openclaw
   ```
3. Read the latest:
   - `context/eve_status_brief.md`
   - `context/eve_status.md` only for targeted supporting excerpts
   - `MEMORY.md`
4. Confirm the issue directly in the repo with exact commands.
5. Make the smallest repair that resolves the issue.
6. Verify with one exact command.
7. Return strict JSON only: `{"status":"repaired|diagnosed|blocked","issue":"...","action":"...","verified":"...","next_step":"..."}`. No markdown, no code fences, no lead-in, no explanation outside the object.
8. Write a brief completion note to `context/last_repair.md`.

If a valid repair object arrives wrapped in prose, treat it as a contract violation and retry once in the same session with the exact JSON-only contract. The Eve wrapper normalizes both the session watcher envelope and OpenClaw 2026.7.1 CLI `payloads[].text`; a raw CLI process exit code is not sufficient success evidence.

Use `--append-memory` only when an operator asks for a compact memory note. Routine sync should not append raw status output into daily memory.

## Repair Posture

the user accepts breakage inside the named Eve project or lab scope when it produces evidence. Prefer bold diagnosis and patch attempts over timid prose when the target is bounded and verifiable. Do not use vague caution as a substitute for judgment; name the exact stop line, missing tool, rollback point, or verification blocker.

## Good Targets

- Broken maintenance or repair workflows
- Daemon / gateway / launch-agent reliability
- Task or proposal queues that are stuck or unclear
- Repair tooling that is present but not actually executable
- Small operator-facing gaps in the self-repair lane

## Bad Targets

- Large UI redesign
- Model-family churn
- Personality or prose tweaks unless they block repairability
- Destructive cleanup without exact targets and explicit approval

## Useful Commands

```bash
python3 $HOME/.eve_runtime/eve.py doctor
python3 $HOME/.eve_runtime/eve.py task list --limit 12 --full
python3 $HOME/.eve_runtime/eve.py maintenance list --limit 12 --full
python3 $HOME/.eve_runtime/eve.py proposal list --limit 12 --full
python3 $HOME/.eve_runtime/eve.py failure list --limit 10
```

Prefer these surfaces over guessing.
