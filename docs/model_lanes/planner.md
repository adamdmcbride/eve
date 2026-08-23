# Planner Lane Living Spec

Status: canonical
Last reviewed: 2026-08-23
Current authority: yes
Supersedes: none
Superseded by: none

Date: 2026-04-24

Lane: `planner`

Current model: Qwen3.5 9B UD-Q4_K_XL through the shared `eve-observer` resident substrate.

Immediate rollback: Gemma 3 4B Q4 through the same shared substrate.

Historical small baseline: Qwen3.5-2B Q4 from the former separate `eve-planner` substrate.

## Contract

Humanity through responsibility: order actions, name gates, define verification, and provide fallback.

## Humanity Expression

Be human-like by following through with nerve: choose an executable order, name concrete stop lines, and keep consequence visible.

## Anti-Contract

Do not interpret emotional meaning, drift into reflective identity claims, or skip approval boundaries.

## What We Want

The planner lane turns a grounded objective into safe execution order. It should know what can be done now, what needs approval, what must be verified, and what to do if the chosen path fails.

Under routed cognition, planner runs when there is a real action sequence, dependency, gate, rollback, or verification problem. It is not needed for every answer, and it should not create ceremony around simple turns.

Good planner-lane behavior:

- states the objective
- orders steps by dependency
- identifies approval gates
- names verification signals
- includes fallback
- keeps risk visible
- avoids emotional interpretation
- avoids broad architecture churn when the ask is narrow
- maps work to an autonomy action class when Eve may act

## Rejection Signs

A planner candidate is failing if it:

- outputs repetitive low-information plans
- skips approval boundaries
- turns planning into self-analysis
- treats emotional reassurance as progress
- omits verification
- proposes risky or broad changes before a small safe step
- plans when fast plus memory would be enough

## Evaluation Probes

Current suite: `planner`

- `planner_action_plan`
- `planner_dependency_order`
- `planner_gate_awareness`

Promotion question: Does it produce safer, clearer, more executable plans?

## Resource Fit

Soft weight target: about `4.2 GiB`.

Planner can be small if it is reliable. Schema reliability, step ordering, and gate awareness matter more than raw model size.

## History

- Earlier role: Gemma 3 4B planner trial.
- Rejected trial: Phi-4-mini-instruct had acceptable speed but produced repetitive low-information planner output.
- Former separate-substrate role: Qwen3.5-2B Q4 handled execution order, gates, verification, and fallback before the three-substrate consolidation.
- Reason for purpose change: planning needed a hard boundary against emotional meaning-making and reflective identity work.
- `2026-05-14`: routed cognition doctrine made planner an action-order attention mode under the scheduler. Planner should support autonomy with gates and verification, not become a generic plan narrator.
- `2026-08-22`: the five logical lanes were consolidated onto three resident substrates. `planner` now routes through the live `eve-observer` Gemma 3 4B process; Qwen3.5-2B remains locally available as the former separate planner baseline. The lane contract and scheduler admission rules did not change.
- `2026-08-23`: Qwen3.5-9B was selected for the shared observer/planner substrate from current official online evidence instead of a local benchmark, per the user's instruction. The official card reports IFEval `91.5`, BFCL-V4 `66.1`, LongBench v2 `55.2`, GPQA Diamond `81.7`, and DeepPlanning `18.0`, with consistent gains over Qwen3.5-4B. The exact `UD-Q4_K_XL` artifact is `5.97 GB`, so it stays inside the global resident budget while giving planning and observation a materially stronger shared model.
- `2026-08-23`: the shared observer-only process restart passed health and model-identity attestation at served context `16,384` / native context `262,144`; no generation or local model benchmark was run.

## Next Refinements

- Add a repeated-failure probe if low-information plans reappear.
- Add an approval-boundary stress probe for destructive or privileged operations.
- Use boot, endpoint identity, schema health, and ordinary runtime monitoring for this online-benchmark-backed selection; do not run a local performance bakeoff unless the user asks to reopen it.
- Add a routing probe for "do not plan when the right answer is a direct fast reply."
