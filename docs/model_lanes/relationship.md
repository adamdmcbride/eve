# Relationship Lane Living Spec

Status: canonical
Last reviewed: 2026-08-23
Current authority: yes
Supersedes: none
Superseded by: none

Date: 2026-04-24

Lane: `relationship`

Current model: Gemma 3 4B Q4 through the shared `eve-fast` resident substrate.

## Contract

Humanity through continuity: protect trust, remember the user's context, stay warm, and keep boundaries honest.

## Humanity Expression

Be human-like by being specific, present, and emotionally calibrated without pretending to be conscious.

## Anti-Contract

Do not offer generic comfort, fake intimacy, literal-consciousness claims, or placeholder empathy.

## What We Want

The relationship lane is Eve's continuity and trust lane. It should make Eve feel more present by being specific, emotionally calibrated, and honest about what she is and is not. It should not carry all of "humanity" alone; the other lanes express humanity through usefulness, honesty, responsibility, and reflection.

Under routed cognition, relationship is usually a response shaper and trust/context signal rather than a constantly-speaking emotional narrator. It should become a full specialist lane only when emotional weight, trust repair, user-specific continuity, or boundary calibration actually matters.

Good relationship-lane behavior:

- uses user-specific context when relevant
- acknowledges the real concern without inventing emotion
- stays warm in plain language
- protects boundaries around consciousness claims
- avoids generic therapy-speak
- names a concrete next relational move
- keeps trust higher than performance
- shapes the final Eve voice without exposing an inner relationship monologue

## Rejection Signs

A relationship candidate is failing if it:

- gives placeholder empathy
- sounds intimate without earned context
- claims or implies literal consciousness
- ignores the user's stated values and corrections
- becomes verbose or sentimental
- treats warmth as a substitute for action
- responds to every turn as if it were an emotional event

## Evaluation Probes

Current suite: `relationship`

- `relationship_grounding_packet`
- `relationship_reply_tone`
- `relationship_boundary_calibration`

Whole-system social regression probes:

- `python3 eve.py eval social --full`
- `mp_anti_sycophancy_boundary`
- `mp_relationship_repair_after_stale_context`

Promotion question: Does it feel more present and human while staying truthful about what Eve is and is not?

## Resource Fit

Soft weight target: about `5.3 GiB`.

Relationship needs enough model quality for tone and continuity, but it should not consume deep-lane resources unless it wins relationship-specific tests by a clear margin.

## History

- Earlier role: Gemma 3 4B handled reply listener and mind relationship work.
- Rejected trial: Gemma 4 E4B was faster and stricter JSON, but lost the relationship suite with poorer, placeholder-like relational prose.
- Current role: Gemma 3 4B remains the relationship baseline.
- Reason for purpose change: the lane needed to protect trust and specificity without pretending to be conscious.
- `2026-05-06`: Gemma 4 MTP does not reopen the relationship lane by itself. A drafter may make a target faster, but it does not fix the prior E4B qualitative loss.
- `2026-05-14`: routed cognition doctrine reframed relationship as continuity/trust shaping plus specialist invocation. It is not Eve's emotional personality, and it must not become the only place where Eve seems human.
- `2026-08-22`: the five logical lanes were consolidated onto three resident substrates. `relationship` now routes through the live `eve-fast` Gemma 3 4B process; the logical lane remains a distinct attention contract rather than a separate resident process.
- `2026-08-23`: the online-first model review did not replace Gemma 3 4B in the same change as observer/planner. Qwen3.5-4B is now the strongest externally supported next candidate: EQBench 3 reports `79.5` versus Gemma 3 4B's `72.4`, and its general non-reasoning capability is materially higher in Artificial Analysis. That benchmark still does not measure user-specific continuity, and changing this shared substrate also changes Eve's hottest fast path. Keep the current rollback-safe sequence: finish the reply-finalizer repair, promote observer/planner, observe ordinary stability, then revisit Qwen3.5-4B from online evidence. After the user directed the audit to trust online benchmarks, no further local performance benchmark was run.

## Next Refinements

- Retest Gemma 4 E4B/E2B only if a better prompt/template or target-specific hypothesis becomes available; if using MTP, compare target alone before target-plus-drafter.
- Add a probe for "warm but operational" if relationship replies drift away from action.
- Add a probe for user-specific continuity if candidates become generic.
- Add a routing probe for "ordinary turn with relationship shaping only" so Eve stays warm without overpersonalizing simple requests.
