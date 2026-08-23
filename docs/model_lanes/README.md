# Eve Model Lane Living Specs

Status: canonical
Last reviewed: 2026-08-23
Current authority: yes
Supersedes: none
Superseded by: none

Date: 2026-04-24

This directory is the living source of truth for what each of Eve's five logical model-lane faculties is supposed to do. The current runtime maps them to three resident substrates, but logical function and physical model topology are separate decisions. Use these files before changing prompts, adding bakeoff probes, evaluating candidates, or promoting a model.

The central resource and history ledger remains [../FIVE_LANE_MODEL_EVAL_AND_RESOURCE_BUDGET.md](../ARCHITECTURE.md#logical-modes-and-physical-substrates). These lane files explain the intent deeply enough that tests can be written against them and refined over time.

## Project DNA

These specs are not only for the weekly model scout. They are part of Eve's core project doctrine. Eve and Codex should treat them as living behavioral contracts whenever work touches:

- Eve's identity or "becoming more human" direction
- prompts and response style
- active-mind lanes
- reply routing
- model exercises and bakeoffs
- model promotion or rollback
- whole-system fitness tests
- manual probes and hidden evaluations

The runtime topology can evolve. The five disciplines should remain legible: usefulness, honesty, responsibility, reflection, and continuity. A future shared model or shared server may implement more than one discipline only after matched causal lesions show that each function still changes its predicted downstream outcome. Do not add a sixth voice to compensate for weak binding between the five.

Count evidence from `2026-07-18` says the present problem is not too few voices. In two evaluator-private matched runs, 66 outputs were scored with the final deep synthesizer fixed. Removing any one council packet failed to produce a stable loss, and every leave-one-out aggregate slightly beat the forced all-five-packet condition. This is packet-level evidence only, so keep all five behavioral contracts and treat sparse admission as mandatory. The follow-on two-run blinded topology canary completed `16` matched pairs with the five contracts mapped to shared `fast`/`relationship`, shared `observer`/`planner`, and separate `deep`: three substrates averaged `3.438/5` versus `3.188/5`, with `6` wins, `7` ties, `3` losses, `0` hard failures, and `7.28%` lower mean duration. This establishes no relative degradation in the sampled tasks, not a quality benefit. Live lifecycle canary `topology-20260718T111748Z-03619366` then verified exactly three processes, reduced equal-age memory, concurrent routed load, shared failure/recovery, watchdog/deadman recognition, and doctor before promoting `three_substrate`. Keep the five-endpoint service definitions as rollback and keep measuring whether shared contention creates delayed losses.

Update from `2026-05-14`: the controlling architecture is routed cognition. Eve is one control system that allocates cognition; the lanes are attention modes, not personalities, sub-agents, or an inner council transcript. The executive scheduler chooses a cognition budget first, then lane(s), organs/tools, autonomy/action authority, verification, and memory/evidence handling. See [../EXECUTIVE_SCHEDULER.md](../EXECUTIVE_SCHEDULER.md), [../AUTONOMY_POLICY.md](../operating/AUTONOMY_POLICY.md), and [../evals/routing_quality.md](../routing/README.md).

The practical default is fast plus memory. Escalate only when complexity, ambiguity, risk, novelty, emotional weight, operational consequence, or evidence gaps justify more cognition. Deep should be rare. Observer should emit structured signals more than prose. Relationship should shape continuity and trust without becoming a constantly-speaking emotional narrator.

The user-facing reply path now uses a reply council admission layer before full stream generation. All five lanes receive a lightweight pressure score on each eligible turn; only lanes above threshold run a model-backed stream. Simple direct turns remain on fast. Once an evaluated council admits multiple faculties, deep performs the single final synthesis over their packets, with contributor and integrator attribution kept separate. This preserves the five disciplines without forcing every resident model to answer every simple message. The detailed plan lives in [../REPLY_COUNCIL_ROADMAP.md](../EXECUTIVE_SCHEDULER.md).

Non-lane support substrates are documented separately in [../SPECIALIST_SUBSTRATES.md](../ARCHITECTURE.md#organ-boundaries). Memory retrieval, coding/self-repair, and frontier/API lab work may support the five lanes, but they should not become a sixth always-on chat lane.

Provider boundary: Eve's live local provider is `llama.cpp` with five named logical contracts on three resident substrates. This is a physical deployment choice, not a doctrine that any number of weight sets is intrinsically conscious. Hosted/non-local providers such as OpenAI, Anthropic, Bedrock, Gemini, OpenRouter, Groq, Together, or similar require the user's explicit permission before use and must name the provider, model, purpose, and data boundary. Lack of hosted login means that capability is unavailable; it does not justify silently leaving the local `llama.cpp` stack.

| Lane | Living spec | Current model | Suite |
| --- | --- | --- | --- |
| `fast` | [fast.md](fast.md) | Gemma 3 4B Q4 | `fast` |
| `deep` | [deep.md](deep.md) | Qwen3.8-27B UD-Q4_K_XL | `deep` |
| `observer` | [observer.md](observer.md) | Qwen3.5-9B UD-Q4_K_XL | `observer` |
| `planner` | [planner.md](planner.md) | shared Qwen3.5-9B UD-Q4_K_XL | `planner` |
| `relationship` | [relationship.md](relationship.md) | Gemma 3 4B Q4 | `relationship` |

## How To Use These Specs

Before a model selection:

1. Read the lane spec for the lane being tested.
2. Compare current official model-card results and independent online
   benchmarks that map to that lane's contract and anti-contract.
3. Confirm architecture, license, context, quantization, chat-template controls,
   and resident-memory fit.
4. Locally verify only artifact integrity, configuration parity, boot, endpoint
   identity, and health.
5. Update the lane spec when online evidence, ordinary operation, or a changed
   contract justifies a different model decision.

The local `python3 eve.py model bakeoff --suite <lane> ...` harness remains for
historical reproducibility and explicit debugging. Do not use it for model
selection unless the user reopens local benchmarking.

Do not promote a candidate because it is "better overall." Eve's five lanes are five different jobs. A model has to win the job it is being hired to do.

Before a routing change:

1. Decide the cognition budget first.
2. Decide whether the lane is needed or whether fast plus memory is enough.
3. Define the action class and autonomy boundary.
4. Define verification before any completion claim.
5. Run the public routing-quality probes and, when needed, shadow-mode evidence before active canary.

## Refinement Rule

Every lane spec should stay small but alive. Update it when:

- the live model changes
- the lane route changes
- the lane contract or anti-contract changes
- a bakeoff exposes a missing probe
- a model fails in a way the current doc did not predict
- the user clarifies what Eve should become
- the executive scheduler changes how a lane is admitted
