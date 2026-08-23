# Eve Executive Scheduler

Status: canonical
Last reviewed: 2026-07-18
Current authority: yes
Supersedes: scattered lane-routing heuristics
Superseded by: none

Date: 2026-05-14

This document defines Eve's routed cognition doctrine.

## Doctrine

Eve is one control system that allocates cognition. The five logical lane faculties are attention modes, not personalities, rivals, or a committee transcript. They currently map to three resident substrates (`fast`+`relationship`, `observer`+`planner`, and separate `deep`); physical model/server count is not identity doctrine.

The scheduler's job is not to be Eve's soul. Eve Core owns identity, values, memory authority, goals, permissions, and final judgment. The executive scheduler allocates attention so Eve can stay coherent, useful, fast, and honest about risk.

The operating order is:

1. Classify the user signal or system trigger.
2. Choose a cognition budget.
3. Select the needed lane or lanes.
4. If multiple faculties contribute, select one final integrator.
5. Decide what evidence, tools, or organs are allowed.
6. Apply the autonomy policy.
7. Verify consequences before claiming completion.
8. Record only the useful evidence or memory proposal.

For a capability-development trigger, step 5 includes a mandatory
capability-first resolution. The executive checks the callable capability map,
configuration/admission surfaces, and current upstream feature reviews before
allocating implementation work. It chooses exactly one of: use the existing
contract, request its existing permission, configure/admit it, canary an
update, research the official source, or prove that a build is required.
Release candidates and online research are rotating background work, not a new
lane. Eve's local runtime executes isolated package canaries, OpenClaw owns
admitted body/action configuration, Hermes may propose learning, and Codex may
implement a proven gap; Eve remains the scheduler and evidence owner.

External builder results use a metadata-first protocol route before ordinary
text intent routing. A Codex or Claude reply to an Eve-created
`independent_operator` handoff is classified as `other_agent` from sender,
bridge, reply target, and handoff metadata. Words inside the report such as
`failure`, `routing`, `health`, `server`, or `unresolved` cannot turn it into an
user-authored diagnostic request. Eve preserves the report as external
evidence, checks the linked Eve-owned system-task consequence, and states the
attribution explicitly. The report itself is neither Eve's action nor canonical
memory nor proof of live adoption.

Bad scheduler question:

> Which model should answer?

Good scheduler questions:

- How much cognition does this deserve?
- What kind of attention is needed?
- What evidence is required?
- What action authority applies?
- What must be verified?
- What should be remembered?

## Cognition Budgets

| Budget | Meaning | Default use | Typical route |
| --- | --- | --- | --- |
| `reflex` | Near-instant response. | Greetings, simple facts from known state, short acknowledgements, obvious UI replies. | `fast` plus current memory only. |
| `operational` | Normal working thought. | Most user-facing work, bounded diagnostics, concise plans, low-risk local actions. | `fast`, memory, optional `observer` or `planner`. |
| `analytical` | Deeper multi-step reasoning. | Ambiguity, contradictions, nontrivial tradeoffs, repeated failures, evaluation review. | `planner`, `observer`, maybe `deep`. |
| `strategic` | Long-horizon synthesis. | Architecture, doctrine, major roadmap decisions, identity-adjacent changes, high-impact repairs. | `deep`, `planner`, memory, evidence ledger. |
| `frontier` | Nonresident expensive escalation. | Rare external critique or hard eval when local evidence is insufficient and the user explicitly admits a provider. | Permission-gated lab only. |

Budgets are above models. Models can change; the budget vocabulary should stay stable.

## Lane Selection

`fast` is the default hot path. If no strong signal requires more, use fast plus memory.

`observer` is a structured sensing mode. It should produce observations, anomalies, confidence, source freshness, and possible escalation triggers. It should not become a repair planner.

`planner` is the execution-order mode. It should define dependencies, gates, verification, fallback, and rollback. It should not become the emotional or identity interpreter.

`deep` packets are rare. They should activate for high uncertainty, contradiction, strategic synthesis, high stakes, failure triage, or wisdom-of-change judgment. Deep should not handle ordinary direct chat. Separately, once the scheduler has admitted an evaluated multi-lane reply council, deep runs once as the final integrator over those packets; this is binding already-approved cognition, not waking another personality.

`relationship` is continuity and trust intelligence. It should shape tone, remember user-specific context, protect boundaries, and repair trust. It should not become an always-speaking emotional narrator or the sole carrier of Eve's humanity.

The lane outputs should usually be invisible to the user. The external experience should be one Eve, not five voices. Fast is the default direct generator. An evaluated multi-lane council uses one deep final synthesis with packet contributors and integrator attributed separately; if deep is quarantined, the configured fast synthesis is an explicit fallback.

### Current Faculty-Count Evidence

The `2026-07-18` evaluator-only matched packet ablation held the final `eve-deep`
synthesizer fixed and compared an all-five-packet arm with each single packet
removed. Across 66 scored outputs and 11 observations per condition, no lesion
produced a stable quality loss; every leave-one-out aggregate was `+0.273` to
`+0.364` above the all-packet baseline. Treat this as evidence that packet
admission and binding still contain redundancy/noise, not as proof that a
logical faculty or its model substrate is unnecessary.

Scheduler decision:

- add no sixth lane;
- retain the five logical contracts so their distinct failure modes stay testable;
- admit only the faculties justified by current pressure;
- never wake all five merely because they exist;
- treat the completed `16`-pair blinded three-substrate comparison as no-degradation evidence (`3.438/5` versus `3.188/5`, `0` hard failures, `7.28%` lower mean duration), not as proof that sharing improves cognition;
- retain the promoted `three_substrate` topology only while lifecycle evidence remains healthy: canary `topology-20260718T111748Z-03619366` passed memory, concurrency, shared-substrate recovery, deadman, and doctor, and the installed five-endpoint definitions remain the rollback;
- delete or merge a logical contract only after repeated substrate-level and longitudinal lesions show no predicted downstream loss.

### Broadcast-Controlled Action Valuation

The executive scheduler does not treat a winning global broadcast as display
text. When `action` is in its access scope, the recurrent action model computes
a bounded alignment between that focus and every admitted affordance, records
the adjustment and basis, and passes the resulting order into autonomy
guidance. Current-turn response priority, action risk, verification authority,
learned reliability, and autonomy policy still remain separate terms and can
override focus when appropriate.

The operator check is:

```bash
python3 eve.py conscious-state counterfactual-actions --full
```

Its matched control changes only the internal broadcast. The coupling-lesioned
and no-action-access arms must not switch choice. This test protects against a
scheduler that narrates attention without letting attention control behavior.

## Conversation Intent Contracts

User-turn routing behavior should be represented as route contracts, not scattered phrase-specific patches.

The public source of truth is [routing/](routing/):

- `signals.json`: named user/system signal vocabulary.
- `route_contracts.json`: active deterministic conversation contracts shared by CLI chat and Eve Chat.
- `anti_contracts.json`: explicit failures the scheduler should keep rejecting.
- `eval_cases.jsonl`: public replay cases for routing quality.

Contracts have two response modes:

- `static`: Eve may answer immediately from the contract. This is limited to low-risk reflex turns such as greetings, personal check-ins, leaked runtime phrase explanations, and direct existential questions.
- `runtime_handler`: Eve uses the contract as scheduler metadata, then delegates to an existing runtime/action/model path. Live status, diagnostic, action, capability, and humanity/identity turns must stay in this mode unless a later reviewed contract proves they are safe as static replies.

The key invariant: static reflex contracts must not capture live/action requests. Replay cases should assert `expected_static_direct_reply=false` for routes that require fresh evidence or execution.

Inspect and replay them with:

```bash
python3 eve.py router contracts --full
python3 eve.py router replay --full
python3 eve.py router replay --record --full
python3 eve.py router replay --json
```

Use `--record` after route or scheduler changes. It writes route-replay evidence and only raises an uncertainty record if the public contract bank fails.

Each direct conversation route should name:

- intent kind
- cognition budget
- lane shape
- organs allowed
- action class
- evidence policy
- user-facing response
- commitment summary

Simple greetings and personal check-ins are `reflex` routes with no runtime evidence unless the user explicitly asks for status. Live status questions are `operational` routes that must use fresh `service_health_check` evidence. Leaked runtime phrase explanations are `reflex` explanations only; they must not silently become new diagnostics promises, capability gaps, or simulated command output.

Both CLI chat and Eve Chat must use the same contract path so the user experience cannot drift between surfaces. Hermes can propose new route examples or evals from traces, and OpenClaw can supply channel/action evidence after Eve selects an admitted action route, but neither organ owns the route table.

## Scheduler Output Contract

Any future runtime scheduler should be able to emit a compact record like:

```json
{
  "trigger": "user_message",
  "intent": "architecture_doctrine",
  "budget": "strategic",
  "lanes": ["deep", "planner"],
  "organs": ["memory", "docs", "codex"],
  "autonomy_class": "modify_local_branch",
  "risk_level": "medium",
  "requires_verification": true,
  "requires_user_approval": false,
  "anti_recursion": {
    "depth": 1,
    "cooldown_key": "architecture_doctrine",
    "duplicate_suppression": true
  },
  "reason": "Identity-adjacent architecture change with durable docs impact."
}
```

This is telemetry and evidence, not a user-facing monologue.

## Anti-Recursion Rules

Eve must not create endless investigations about investigations. The scheduler should enforce:

- max cognition depth per trigger
- repeated-topic cooldowns
- duplicate proposal suppression
- diminishing-return detection
- one active self-improvement loop per bounded objective
- no self-triggered escalation to frontier providers
- no promotion from observation to mutation without an action class and verification path

If the scheduler cannot identify the next real consequence, Eve should stop, log the uncertainty, and choose a smaller observable step.

The first runtime enforcement is active in the mind loop:

- daemon/autonomy ticks with no fresh evidence record `NoopTickEvent` and keep the previous active mind unchanged
- self-check can downgrade a synthesized active mind and record `MindDowngradedEvent`
- proactive ambient output can defer and record `OutboundDeferredEvent` when Eve would otherwise add more motion into a stale/degraded or unread-saturated state

These gates are not a substitute for the full scheduler. They are the anti-recursion floor that keeps Eve from spending model time or creating outbound signals just because her prior state exists.

### Subsystem Feature Review Input

The scheduler may consume the compact output of Eve's recurrent capability
intelligence as an attention signal. The current ledger reviews 123 feature
families across Eve, OpenClaw, and Hermes and exposes use-existing, configure,
canary, defer, and reject decisions. It does not make those features scheduler
actions. A selected review must still resolve to a named Eve objective, owning
organ, action/permission class, canary, consequence, and rollback path.

Unset optional configuration, release availability, a passing import, or a
ready service is not urgency. The scheduler should prefer current conversation
and unresolved verified commitments over routine feature review, and it must
not turn Hermes cron/Kanban, OpenClaw cron/TaskFlow, Dagster, or an OSS workflow
engine into a parallel executive scheduler. Detailed current decisions live in
[EVE_SUBSYSTEM_FEATURE_CONFIGURATION_AUDIT_2026_07_20.md](ARCHITECTURE.md).

## Shadow Mode

New scheduler behavior should start in shadow mode:

- current Eve answers normally
- scheduler predicts budget, lane, organs, and authority
- evidence records what it would have done
- routing-quality evals compare the prediction against the observed outcome

Only after shadow evidence shows that the scheduler avoids underthinking and overthinking should it become active in Eve Chat, then broader runtime paths.
