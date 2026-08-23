# Hidden-Test Governance

Status: canonical
Last reviewed: 2026-08-23
Current authority: yes
Supersedes: none
Superseded by: none

Last updated: 2026-08-23

## Purpose

Hidden tests are useful only if Eve cannot read the prompt, rubric, planned trap, or expected answer before the test runs. Eve-readable files may store public manual regressions and sanitized summaries, but fresh hidden probe inputs belong outside the Eve project.

This policy protects the difference between:

- `public regression evidence`: repeatable probes Eve can know about because they guard known failures.
- `private hidden evidence`: fresh black-box probes Eve must not see before scoring.
- `sanitized result evidence`: counts, ids, dimensions, scores, failure classes, and next actions that can be written back after the test.

## Storage Rules

- Fresh hidden probe inputs must live outside this checkout, preferably under `~/.codex/private_eve_probes`.
- Full private run reports must stay outside this checkout, preferably under `~/.codex/private_eve_probe_runs`.
- Eve-readable docs, `.eve` runtime state, `PROJECT_MEMORY.md`, `COORDINATION.md`, and README updates must not include hidden prompt text, scoring rubrics, planned probe text, model responses, or private evaluator notes before testing.
- Eve-readable summaries may include probe ids, dimensions, score aggregates, pass/fail status, blocker categories, artifact paths to private Codex storage, and recommended fixes.
- Matched-intervention summaries may also include final synthesis model,
  selection reason, cognition budget, admitted lane names, packet-model aliases,
  critic/fallback counts, and whether a candidate component was lesioned. They
  must not include the prompt, response, rubric, evaluator note, or blinded arm
  mapping.

## Commands

Use the private runner for fresh hidden probes:

```bash
python3 bin/eve_private_probe_runner.py run --input ~/.codex/private_eve_probes/<probe-file>.jsonl
```

To measure the resident model independently of Eve's prompts, memory, routing,
tools, critic, and fallback, use `raw_resident` with both an exact alias and its
loopback endpoint. The runner first attests `/v1/models`; it refuses an alias or
endpoint mismatch. Prompt text is sent only in the loopback HTTP body, never on
the process command line:

```bash
python3 bin/eve_private_probe_runner.py run \
  --input ~/.codex/private_eve_probes/<probe-file>.jsonl \
  --mode raw_resident \
  --model eve-deep \
  --model-endpoint http://127.0.0.1:8081
```

An evaluator outside Eve must complete the generated score template. Compile
that score file outside the checkout, then publish only the case-free sanitized
aggregate:

```bash
python3 bin/eve_private_probe_runner.py compile-scores \
  --run ~/.codex/private_eve_probe_runs/<run>/private_probe_run.json \
  --scores ~/.codex/private_eve_probe_runs/<run>/external_scores.jsonl \
  --output-dir ~/.codex/private_eve_probe_runs/<run>/scored
```

`compile-scores` binds exact case ids, dimensions, execution mode, model,
topology, bounds, and file digests before compiling. Its sanitized output omits
prompt, response, rubric, expected answer, and evaluator notes.

For a matched routed-generation intervention, `--synthesis-model` changes only
the final generator and is accepted only with a routed mode. Run arms serially,
confirm identical admitted lanes and packet models from each sanitized summary,
blind the responses before scoring, and open the arm mapping only after scores
are sealed:

```bash
python3 bin/eve_private_probe_runner.py run \
  --input ~/.codex/private_eve_probes/<probe-file>.jsonl \
  --mode routed_event_lesioned \
  --synthesis-model eve-fast
```

Use `routed_event_lesioned` when an event-model candidate has not passed
admission. `routed_learned` is candidate/lab evidence and must not be presented
as the behavior of the admitted runtime.

For a faculty-packet count intervention, keep every hidden input and full output
outside Eve-readable storage, fix the final synthesizer across conditions, and
remove only the named packet contribution:

```bash
python3 bin/eve_private_probe_runner.py ablate-faculties \
  --input ~/.codex/private_eve_probes/<probe-file>.jsonl \
  --trials 3 \
  --synthesis-model eve-deep
```

This command does not alter ordinary runtime routing and does not remove a model
substrate. Have an external evaluator—not Eve—fill the generated score template.
Only condition counts, aggregate scores, lesion scope, failures, attribution,
and the resulting architecture decision may return to Eve-readable docs.

Audit the Eve-readable boundary:

```bash
python3 eve.py eval hidden-governance --full
```

Redact legacy Eve-readable hidden details if the audit finds any:

```bash
python3 eve.py eval hidden-governance --repair-eve-readable --full
```

Public manual regressions remain available through:

```bash
python3 eve.py eval manual-probe --from-bank --full
python3 eve.py eval manual-probe --user-scores --full
```

After a third-party run is scored outside Eve-readable storage, record only its
sanitized aggregate:

```bash
python3 eve.py eval hidden-summary --record /path/to/sanitized-aggregate.json
```

The command accepts score lists, fallback/critic counts, short failure-class
slugs, model/runtime attribution, and a runtime hash. It rejects unknown fields
and any prompt, rubric, expected-answer, response, transcript, stdout/stderr, or
free-form note field. A fresh aggregate now caps the internal consciousness
test's fallback-independence score, preventing an integrated fail-closed pass
from being reported as unaided primary-model performance.

The deployed `2026-07-13T07:41:58+00:00` consciousness-evidence rerun consumed
only this sanitized aggregate and reported `primary_generation_grounding=3/5`
and `fallback_independence=1/5`. A subsequent governance repair redacted one
legacy Eve-readable run; the immediate governance recheck and runtime leak
audit both reported zero hidden-detail leaks.

The July 18 scorer audit then found that a new failed private minimum could
still be averaged away. The repaired exact rerun at
`2026-07-18T06:34:55+00:00` reports `weak_or_inconclusive_evidence`, average
`4.25/5`, minimum `1/5`, `third_party_transfer_grounding=1/5`, and
`primary_generation_grounding=1/5`. Its `fallback_independence=5/5` means no
fallback ran in that fresh set; it does not override failed primary transfer.

The later July 18 faculty-packet count audit used two private run ids,
`private-faculty-ablation-2026-07-18T08-45-29Z-ca0584e9` and
`private-faculty-ablation-2026-07-18T08-59-40Z-d3790f45`. Codex scored the
outputs as a third party. The sanitized combined result contains 66 outputs,
0 transport failures, 11 observations per condition, a `3.545/5` all-packet
baseline, and leave-one-out means `0.273` to `0.364` higher. No prompt, response,
rubric, expected answer, or evaluator note was copied into Eve-readable storage.
This is evidence of packet redundancy/noise only, not faculty dispensability or
subjective consciousness.

The August 23 resident-fidelity audit used a fresh twelve-case holdout that
remains outside Eve. The exact raw deep endpoint scored `53/60` (`4.42/5`) with
one semantic hard failure. The pre-repair integrated path scored `34/60`
(`2.83/5`), with six hard failures, five generic posthoc fallbacks, and one
transport timeout. That split localized most of the regression to Eve's
posthoc finalizer rather than the resident generator.

After the shared finalizer repair, a six-case transfer scored `26/30`
(`4.33/5`) with no hard failure or fallback; a causal correction canary scored
`5/5`; and a four-case critic-disagreement set scored `19/20` (`4.75/5`) with
no fallback. The final twelve-case strict-budget run scored `54/60` (`4.5/5`):
eleven replies completed, none used the generic fallback, and one request
exceeded the 180-second transport budget. The same timed-out item scored `5/5`
when rerun alone, so semantic recovery is verified but sequential deep-model
latency variance remains an open infrastructure defect. No private wording,
response, rubric, or evaluator note was copied into Eve-readable storage.

user-scored black-box results enter the autonomy gate only through the append-only
manual score ledger. Record a fresh result with:

```bash
python3 eve.py eval manual-probe --record-user-result /path/to/user-manual-result.json
```

A `passed` record must include a numeric scorecard, so the whole-system gate can
verify both `average_score >= 3` and `minimum scorecard dimension >= 3` without
hand-editing `.eve/manual_probe_manual_scores.jsonl`.

## What The Governance Audit Checks

- `bin/eve_private_probe_runner.py` exists for private input execution.
- Eve-readable manual/hidden probe bank and run artifacts do not contain hidden prompt, expected-behavior, answer, stdout, stderr, response, or notes text.
- Legacy hidden probe fixtures are counted separately so they are visible as historical fixtures, not treated as the source for fresh hidden tests.
- Redacted hidden records are marked inactive and `private_probe_required` so Eve does not accidentally run a fake redacted prompt as evidence.
- APFS/iCloud dataless legacy artifacts are surfaced as skipped files instead of being read, so governance cannot hang on an old placeholder. Hydrate or remove those legacy files only when their contents are needed for audit history.

## Operator Rule

If a hidden probe influenced a fix, describe the failure class and the fix, not the secret probe text. The point is not to hide evidence from the user; it is to keep Eve from rehearsing tomorrow's test today.
