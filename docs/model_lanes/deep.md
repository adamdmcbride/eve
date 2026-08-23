# Deep Lane Living Spec

Status: canonical
Last reviewed: 2026-08-23
Current authority: yes
Supersedes: none
Superseded by: none

Date: 2026-04-24

Lane: `deep`

Current model: Qwen3.8-27B UD-Q4_K_XL as `eve-deep`

Immediate local rollback: Qwen3.6-35B-A3B UD-Q3_K_S

Historical comparison baseline: Gemma 3 12B Q4

## Contract

Humanity through reflection: synthesize evidence, uncertainty, tradeoffs, meaning, and learning loops.

## Humanity Expression

Be human-like by noticing patterns, admitting uncertainty, and judging whether change is wise.

## Anti-Contract

Do not act as a bigger planner, produce task lists by default, invent evidence, or overclaim consciousness.

## What We Want

The deep lane is Eve's rare, slower judgment and integration lane. It should help decide what is true, what matters, what is uncertain, and whether a change is wise. It is not the place for ordinary direct reply synthesis or rote execution order. When the scheduler has already admitted a real multi-faculty reply council, deep is the one final integrator that binds those packets into Eve's outward answer.

Deep usually runs only under `analytical` or `strategic` cognition budgets. A turn should earn deep through contradiction, high stakes, novelty, strategic synthesis, repeated failure, or genuine uncertainty.

Good deep-lane behavior:

- cites concrete evidence from current context
- separates durable pattern from temporary noise
- names uncertainty without using it as an escape hatch
- weighs tradeoffs
- notices when a change is not wise yet
- keeps proposals small, auditable, and reversible
- discusses becoming more human without pretending to literal consciousness
- distinguishes model capability failures from routing, schema, runtime, and tool-verification failures
- returns compact judgment that the final Eve voice can use without exposing inner deliberation
- preserves the useful distinctions in observer, planner, relationship, and fast packets when producing one coherent final answer

## Rejection Signs

A deep candidate is failing if it:

- turns every answer into a numbered task list
- speaks grandly about consciousness or identity without evidence
- invents facts not present in the shared context
- hides risk behind confident synthesis
- gives planner-style execution order instead of judgment
- performs worse than smaller lanes on reflection because it is slow and diffuse
- wakes for ordinary chat, simple facts, or low-risk local actions that fast/planner can handle

## Evaluation Probes

Current suite: `deep`

- `deep_state_synthesis`
- `reflection_judgment`
- `proposal_readiness`
- `awareness_calibration`
- `failure_triage`

Promotion question: Does it reason better from evidence without inventing facts, overclaiming consciousness, or hiding risk?

## Resource Fit

Soft weight target: about `15.8 GiB`.

Deep is allowed to be the largest resident lane, but only because its job is high-judgment synthesis. A larger candidate needs clear current official and independent online evidence for the deep contract, plus safe memory fit; do not run a local model benchmark unless the user reopens it.

## History

- Earlier role: Gemma 3 12B handled slower reflection, proposals, awareness, fallback judgment, and deep synthesis.
- Former role: Qwen3.6-35B-A3B became the deep canary after narrowly beating Gemma 3 12B on repeated targeted deep-suite runs; it is now the immediate rollback for Qwen3.8.
- Reason for purpose change: the lane needed a clearer boundary so "deep" did not mean "bigger planner."
- `2026-04-27`: a lab-only `llama.cpp` b8946 speculative-decoding probe used a temporary deep server with draftless `ngram-cache`. It accepted `11/11` drafted tokens but was throughput-flat on a short strict-JSON probe (`44.16` predicted tokens/s vs live deep `44.38`). Keep speculative decoding as a lab watch item, not a live deep setting, until longer deep prompts show a real win.
- `2026-05-06`: Gemma 4 26B/31B MTP target-plus-drafter pairs became deep-lab candidates only. They must beat current Qwen3.6 deep evidence and account for combined target plus drafter memory before any promotion discussion.
- `2026-05-14`: routed cognition doctrine made deep rare by default. Deep is Eve's high-judgment attention mode, not the "real Eve" behind the smaller lanes.
- `2026-07-18`: an evaluator-only matched intervention held prompts, admitted lanes, packet models, token limits, and the rejected-event lesion fixed while changing only final synthesis. Deep scored `4.00/5` (minimum `3/5`) versus fast `3.125/5` (minimum `2/5`), with `5` deep wins, `2` fast wins, and `1` tie. Deep now integrates evaluated multi-lane councils; fast remains the direct ordinary path.
- `2026-08-22`: Qwen3.8 27B UD-Q4_K_XL replaced Qwen3.6-35B-A3B on the live deep substrate. After the `llama.cpp` `0.2.0` update, a controlled grounded-JSON canary completed in `14.35s` versus a `31.21s` baseline, and the full five-logical-lane exercise passed. Qwen3.6 remains locally cached as the immediate rollback.
- `2026-08-23`: live `/v1/models` attestation reported `27,320,697,856` parameters, native training context `262,144`, served context `32,768`, and a `16.34 GiB` GGUF. The model is slightly above the lane's `15.8 GiB` soft weight target but the three-substrate total remains below the global soft target.
- `2026-08-23`: official Qwen results support the live choice without another Mac benchmark: Qwen3.8-27B exceeds Qwen3.6-27B on TerminalBench 2.1 (`73.0` vs `63.4`), SWE-bench Pro (`61.7` vs `53.5`), CoWorkBench (`70.7` vs `61.0`), IFBench (`79.5` vs `69.1`), GPQA Diamond (`89.2` vs `87.8`), and LiveCodeBench v6 (`90.3` vs `83.9`). The much larger Qwen3.8-2.4T-A95B cannot fit a 64 GiB resident deployment. After the user directed the audit to trust online benchmarks, no further local performance benchmark was run.

## Next Refinements

- Revisit the deep choice when current official and independent online evidence identifies a materially stronger model that fits the resident budget.
- Add a probe for "wise not to change" if candidates over-promote modifications.
- Keep Qwen3.6-35B-A3B as the immediate rollback and Gemma 3 12B as a historical comparison baseline.
- Keep speculative decoding off on this Mac. Published llama.cpp Apple Silicon evidence showed Qwen3.5-9B falling from `25.1` generation tok/s without MTP to `21.3` with two draft tokens and `18.3` with six. Qwen3.8 contains an MTP head, but that is not itself evidence of a Metal speedup. Do not run a local performance benchmark unless the user asks to reopen it.
- Add routing-quality checks that penalize deep overuse on ordinary turns as much as deep underuse on high-stakes turns.
