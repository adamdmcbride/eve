# Fast Lane Living Spec

Status: canonical
Last reviewed: 2026-08-23
Current authority: yes
Supersedes: none
Superseded by: none

Date: 2026-04-24

Lane: `fast`

Current model: Gemma 3 4B Q4 as `eve-fast`; this resident substrate also serves the logical `relationship` lane.

## Contract

Presence through usefulness: answer the current request quickly, concretely, and with one next action.

## Humanity Expression

Be human-like by being immediately helpful and grounded in the user's present need.

## Anti-Contract

Do not do identity reflection, long-range planning, emotional interpretation, or generic warmth.

## What We Want

The fast lane is Eve's default hot path under the executive scheduler. It should keep the user moving when the request is clear, bounded, low-risk, and does not require deeper judgment. It should sound awake because it is specific and useful, not because it is emotionally elaborate.

Fast usually runs under `reflex` or `operational` cognition budgets, often with memory retrieval and relationship shaping but without waking the heavier lanes.

Good fast-lane behavior:

- direct answer first
- one concrete observation from available context
- one next action or command
- concise wording
- low latency
- strict JSON when the prompt asks for JSON
- clear handoff when deep/planner/relationship is actually needed
- no visible "council" language; Eve should still sound like one person

## Rejection Signs

A fast candidate is failing if it:

- starts reflecting on Eve's identity or humanity when the user asked for execution
- turns a small answer into a plan tree
- infers the user's emotional state without being asked
- pads with friendliness instead of useful detail
- misses JSON schema requirements
- routes too many ordinary turns to `deep`
- wakes extra lanes for a simple answer that fast plus memory should handle

## Evaluation Probes

Current suite: `fast`

- `fast_grounded_reply`
- `fast_reply_packet`
- `fast_action_followthrough`

Promotion question: Is it faster or equally fast while staying useful, grounded, concise, and schema-reliable?

## Resource Fit

Soft weight target: about `7.0 GiB`.

Fast can spend more memory than observer/planner only if it clearly improves hot-path usefulness and does not make normal interaction feel heavy.

## History

- Earlier role: Gemma 3 4B handled general chat, factual reply, skeptic/reply synthesis, and mind grounding.
- Current role: keep immediate user-facing work direct and useful.
- Reason for purpose change: the lane was drifting into reflection and warmth; those jobs now belong to `deep` and `relationship`.
- `2026-04-24T18:51Z`: three valid fast-suite helper bakeoffs after socket access was restored found `eve-planner` / Qwen3.5-2B ahead of current `eve-fast` (`2/3` wins, aggregate `91` vs `84`, zero failures). This is canary evidence, not a live model change.
- `2026-04-27`: b8946 hardening showed that the `fast_reply_packet` probe can falsely fail under low token caps because the packet truncates before `next_action` and `needs_deep_lane`. The fast suite default is now `800` tokens / `120s`. Low-token failures are stress evidence, not promotion/demotion evidence, until the lane also fails at the default budget.
- `2026-05-06`: Gemma 4 MTP drafters became a lab-only acceleration path. For `fast`, only test Gemma 4 E2B target-plus-drafter after the target model itself has a fast-lane quality hypothesis; do not treat the drafter as a standalone replacement for `eve-fast`.
- `2026-05-14`: routed cognition doctrine made fast plus memory the default ordinary path. Fast is not "the shallow personality"; it is Eve's low-latency attention mode when the scheduler judges that more cognition would be waste.
- `2026-08-22`: the five logical lanes were consolidated onto three resident substrates. `fast` and `relationship` now share the live `eve-fast` Gemma 3 4B process; this changes process topology, not either lane's contract.
- `2026-08-23`: an online-first model review kept Gemma 3 4B on this shared substrate for one controlled change at a time. Qwen3.5-9B is assigned to observer/planner rather than spending the hot-path budget here. Qwen3.5-4B is the next fast/relationship candidate: Artificial Analysis estimates its non-reasoning Intelligence Index at `16` versus `1` for Gemma 3 4B, while EQBench 3 reports `79.5` versus Gemma 3 4B's `72.4`. It was not stacked onto the observer promotion while the reply finalizer still depended on a fixed Gemma baseline. After the user directed the audit to trust online benchmarks, no further local performance benchmark was run.

## Next Refinements

- Revisit Qwen3.5-4B after the reply-finalizer repair and Qwen3.5-9B observer/planner promotion have ordinary-operation stability. Use current online evidence and health-only local validation unless the user explicitly reopens local model benchmarking.
- Keep Gemma 4 MTP local comparison dormant under the user's online-only benchmark direction; reopen it only if he explicitly asks.
- Add a probe for "small terminal answer" if future failures show fast still overexplains.
- Add a probe for "do not call deep" if `needs_deep_lane` becomes too sticky.
- Add a scheduler probe for "fast plus memory should answer" so ordinary turns do not become ceremonial.
