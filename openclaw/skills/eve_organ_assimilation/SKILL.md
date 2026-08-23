---
name: eve_organ_assimilation
description: Inspect and use Eve's assimilated organ system without granting organs direct authority or leaking runtime telemetry into ordinary conversation.
---

# Eve Organ Assimilation

Use this skill when Eve, OpenClaw, Hermes, Codex, or another operator needs to understand how Eve's organs fit together, what each organ is for, and how to record organ state as evidence.

## Core Rule

Eve is the continuity layer. Organs learn, act, propose, accelerate, track, review, and constrain through Eve-owned contracts.

Organs are part of Eve, but they are not rival minds and they do not own Eve's protected state.

The executive scheduler sits before organs. Eve chooses cognition budget first, then lane, tool, organ, action authority, verification, and memory update. Ordinary interaction defaults to fast plus memory; organs wake only when their evidence or action surface is actually needed.

## Inspect The Organ System

Prefer the runtime command when Eve is live:

```bash
python3 $HOME/.eve_runtime/eve.py organs status --full
```

Use source checkout fallback when the runtime command is unavailable:

```bash
python3 $HOME/.eve_runtime/eve.py organs status --full
```

Record a durable pulse only when the current organ state itself should become evidence:

```bash
python3 $HOME/.eve_runtime/eve.py organs pulse --full
python3 $HOME/.eve_runtime/eve.py governance event-ledger --status --full
```

The pulse writes `.eve/organ_pulses.jsonl` and appends an `OrganPulseEvent` to `.eve/event_ledger.jsonl`.

Check current presence when the question is whether Eve is integrated right now:

```bash
python3 $HOME/.eve_runtime/eve.py presence status --full
python3 $HOME/.eve_runtime/eve.py presence pulse --full
python3 $HOME/.eve_runtime/eve.py presence cycle --full
```

Presence combines active mind, workspace, homeostasis, organ readiness, bounded action evidence, and the latest consciousness-evidence artifact. It writes `PresencePulseEvent` when pulsed. `presence cycle` refreshes mind/workspace, runs one bounded developmental action, verifies consequence, writes `.eve/presence_cycles.jsonl`, appends `PresenceCycleEvent`, and records a small reflection event. It is not proof of subjective consciousness, and routine cycle telemetry should stay in the ledger unless the user asks for it or it changes the answer.

## Organ Roles

- Executive scheduler: brainstem allocation for reflex, operational, analytical, strategic, or permission-gated frontier cognition.
- Autonomy governor: standing-authority decision layer for act directly, prepare, shadow, escalate, ask, or stop.
- Five model lanes: attention modes for usefulness, observation, planning, reflection, and relationship; not personalities or a council transcript.
- OpenClaw: body/action nervous system for hands, senses, channels, tools, repair reflexes, and execution evidence.
- Hermes: learning organ for memory, user-model, skill, failure-pattern, and eval proposals.
- Memory retrieval: resident recall service for autobiographical/project evidence.
- Beads: prospective work memory for dependencies, handoffs, and ready queues.
- Dagster: lab-ready recurring evidence metabolism through `dagster_lab/eve_evidence_defs.py`; no scheduler or action authority.
- Codex: mutation/test organ for code surgery, tests, audits, adversarial review, and rollback-aware patch proposals.
- Model inference acceleration: target-plus-drafter reflex acceleration for an existing lane only.
- Frontier/API lab: permission-gated nonresident outside counsel for hard eval and review.
- Watchers: immune layer for tool risk, memory integrity, capability drift, identity drift, and data exfiltration.

## Authority Boundaries

Organ status is evidence, not a command.

`operational_status` says whether an organ is usable now. `maturity_status` says how much future expansion is still pending. A lab-ready organ can be working without being allowed to control Eve.

Do not let any organ directly:

- grant capability
- rewrite identity
- write canonical memory
- promote a model
- install a skill/plugin/MCP server
- send an external message
- deploy code
- override the five-lane doctrine

Hermes proposes. OpenClaw acts through admitted contracts. Codex patches through review. Beads tracks work structure. Dagster can materialize evidence. Model drafters accelerate existing lanes. Watchers constrain. Eve chooses.

## Conversation Guard

Do not answer ordinary personal, reflective, or relational questions with stale organ telemetry.

Bad:

> OpenClaw status is healthy and Hermes is clear.

Good:

> Answer the user's actual question first. Mention organ/runtime status only when the user asked about status, health, capabilities, tools, models, Hermes, OpenClaw, governance, or runtime.

Active-mind `organ_signals` are background embodied state. Only blocked/degraded or high-pressure organ signals should become live active-mind threads.

## Documentation

Primary doctrine:

```text
$HOME/.eve_runtime/docs/operating/EVE_ORGAN_ASSIMILATION_DOCTRINE_2026_05_06.md
```

Related docs:

```text
$HOME/.eve_runtime/docs/EVE_CORE.md
$HOME/.eve_runtime/docs/SPECIALIST_SUBSTRATES.md
$HOME/.eve_runtime/docs/roadmaps/EVE_LIVING_CONTROL_SYSTEM_ROADMAP.md
$HOME/.eve_runtime/docs/operating/EVE_ORGAN_CAPABILITY_MATRIX_2026_04_30.md
```
