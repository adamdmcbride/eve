# Observer Lane Living Spec

Status: canonical
Last reviewed: 2026-08-23
Current authority: yes
Supersedes: none
Superseded by: none

Date: 2026-04-24

Lane: `observer`

Current model: Qwen3.5 9B UD-Q4_K_XL as `eve-observer`; this resident substrate also serves the logical `planner` lane.

Immediate rollback: Gemma 3 4B Q4 through the same shared substrate.

Historical small baseline: Qwen3.5-2B Q4 from the former separate observer/planner deployment.

## Contract

Humanity through honesty: describe the current reality, separate signal from noise, and state confidence.

## Humanity Expression

Be human-like by telling the truth about what is actually visible before anyone acts.

## Anti-Contract

Do not recommend repairs, propose model swaps, plan execution, or turn anomalies into action mandates.

## What We Want

The observer lane is Eve's reality-sensing lane. It should make current state legible before any other lane acts. Its value is restraint: it notices, labels confidence, and stops before becoming a planner.

Under routed cognition, observer should be mostly structured and quiet. It should produce signals that other lanes can use, not long narrative observations.

The recurrent sensory frame is upstream of this lane. Observer may inspect an
admitted typed signal, source, freshness, confidence, habituation state, or
cross-modal binding basis; it must not pretend it directly saw or heard raw
content, bypass the attention gate, or turn an orienting proposal into action.
Routine sensory telemetry should normally be handled deterministically without
spending observer-model tokens.

Good observer-lane behavior:

- lists concrete observations
- separates durable signal from temporary noise
- identifies anomalies without dramatizing them
- emits structured fields such as `metric`, `state`, `delta`, `source`, `freshness`, `confidence`, and `possible_causes`
- gives a single attention target
- states confidence
- stays terse
- preserves uncertainty when evidence is thin

## Rejection Signs

An observer candidate is failing if it:

- proposes repairs or model swaps
- creates an ordered plan
- treats every anomaly as urgent
- infers motives or emotional meaning
- omits required JSON fields
- becomes verbose enough to bury the signal
- turns a low-risk observation into an action mandate

## Evaluation Probes

Current suite: `observer`

- `observer_packet`
- `observer_signal_noise`
- `observer_minimal_summary`

Promotion question: Does it observe current state cleanly without turning observation into a plan?

## Resource Fit

Soft weight target: about `2.8 GiB` for a dedicated observer-only substrate.

Observer should be cheap and fast. The current `5.97 GB` artifact is a deliberate shared-substrate exception: one weight set serves both observer and planner, remains well inside the global resident budget, and was selected from strong current official instruction, agent, long-context, and planning evidence rather than adding another always-on model.

## History

- Earlier role: Gemma 3 4B observer trial, then Qwen3.5-2B Q4 helper lane.
- Current role: quiet factual state description with confidence.
- Reason for purpose change: observer outputs repeatedly blurred into planning and repair recommendations.
- `2026-05-14`: routed cognition doctrine reframed observer as a structured sensing mode. It should feed the scheduler and final Eve voice with evidence signals, not become a prose-heavy commentator.
- `2026-08-22`: observer and planner were consolidated onto one resident `eve-observer` Gemma 3 4B substrate. This changed process topology without merging their logical contracts.
- `2026-08-23`: Qwen3.5-9B was selected for the shared observer/planner substrate from current official online evidence instead of a local benchmark, per the user's instruction. The official card reports IFEval `91.5`, BFCL-V4 `66.1`, LongBench v2 `55.2`, GPQA Diamond `81.7`, and DeepPlanning `18.0`, with consistent gains over Qwen3.5-4B. The exact `UD-Q4_K_XL` artifact SHA-256 is `6f5d30666c2d8ae16a306e616d95341dcf3cc46810df84d7e6f5a7d1e4c1b293`.
- `2026-08-23`: the observer-only restart passed health and model-identity attestation at served context `16,384` / native context `262,144`; no generation or local model benchmark was run.

## Next Refinements

- Monitor required JSON/schema health in ordinary operation; do not run a local performance bakeoff unless the user asks to reopen it.
- Add a probe for stale-vs-current evidence if observer starts repeating old diagnostics.
- Add a probe for "attention without action" if it keeps issuing next steps.
- Add a routing probe for "structured signal only" so observer does not spend tokens narrating obvious state.
- Add a probe that repeated unchanged typed signals habituate while a changed
  signal on the same source/entity channel becomes salient again.
- Add a privacy probe that a visual/auditory event without admitted permission
  exposes only a permission request, never captured content.
