# Eve Performance Observation Contract

Status: evidence-log  
Last reviewed: 2026-08-23  
Current authority: performance-analysis validity and compatibility boundary  
Supersedes: performance summary helpers embedded in `eve.py`  
Superseded by: none

## Decision

Eve must not turn a runner restriction, malformed duration, or unavailable
measurement into evidence that a runtime path is fast, slow, healthy, or
broken. Performance event persistence remains in the runtime. Pure validation,
grouping, percentiles, and presentation now belong to `eve_performance.py`, and
the compatibility facade aliases the same functions.

This is a measurement-truth repair, not an optimization claim and not a reason
to hide failures.

## Observation states

Every existing event without an observation label remains `measured` so old
ledgers and callers keep their meaning. A producer may explicitly set
`observation_status` at the event root or in metadata:

- `measured` — the named operation ran in an environment able to observe it;
- `inconclusive` — the environment could not make the named measurement;
- `invalid` — the sample or its contract is unusable.

Unknown explicit labels fail closed as invalid. The analyzer does not match
error strings such as “permission denied” or “timeout” to choose a state:
either can be a real product failure or a restricted evaluator boundary, and
the producer owns that provenance.

## Summary rules

- `count` is every event in the group.
- `measured_count`, latency statistics, and `failures` use only measured events
  with finite, non-negative durations.
- `total_failures` retains every `ok=false` record, including unusable samples.
- `inconclusive_count` and `invalid_count` stay visible beside the measured
  result.
- missing legacy duration retains the old zero-duration behavior;
  nonnumeric, Boolean, negative, NaN, and infinite values are invalid.
- group identity, latest-record semantics, nearest-rank p95 behavior, and
  ordinary all-measured terminal output remain compatible.

This means an evaluator can separate “the runtime failed” from “this sandbox
could not perform the probe” without deleting either record or poisoning the
latency baseline.

## Verification

Source verification covers:

- exact `eve.py` alias compatibility;
- existing all-measured grouping, sorting, p95, and presentation;
- explicit inconclusive and invalid samples retained but excluded from measured
  latency;
- malformed and non-finite durations failing closed without a summary crash;
- unknown validity labels remaining visible as invalid;
- empty and failure presentation contracts.

The portable Linux CI suite runs this contract directly. No runtime sync,
service restart, model call, or performance-event write is required by the
test.

Source verification on 2026-08-23:

- `369` portable foundation/runtime tests passed with `ResourceWarning` treated
  as an error;
- `36` focused performance, workflow, release, and portability tests passed;
- Python compilation passed;
- the clean public candidate contained `374` files with `0` blocking findings
  and the three expected private-checkout warnings;
- the documentation audit reported no finding against this document.

A read-only summary of the current development ledger still showed old
permission-bound failures as measured. That is intentional: those historical
producers did not attach observation provenance, and this change does not
silently rewrite or phrase-match their records. Future restricted probes must
label themselves at write time.

## Remaining work

Phase 4 still needs separately measured and versioned budgets for:

1. idle CPU and wakeups;
2. resident memory by app, daemon, and model substrate;
3. app launch to usable conversation;
4. first-token and complete-reply latency by cognition budget;
5. streaming cadence and stalls;
6. model switching and recovery.

Those budgets require clean host-authoritative baselines and regression
fixtures. This extraction makes those future comparisons trustworthy; it does
not invent thresholds from the current mixed development ledger.
