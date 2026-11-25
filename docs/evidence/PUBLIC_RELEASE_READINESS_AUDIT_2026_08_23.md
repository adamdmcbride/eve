# Eve Public-Release Readiness Audit

Status: evidence-log  
Last reviewed: 2026-08-23  
Current authority: published pre-alpha source gate
Supersedes: none  
Superseded by: none

## Decision

**The initial public source is published; Eve is not ready for a version tag or
stable-release claim.** The public repository was created from the passing clean
export, not from the private checkout or its history.

The publication target is the maintainer's personal repository configured in
`public_release.json`. Eve is not an Eden product and must not be published by
or on behalf of an Eden account or organization.

## Verified source boundary

The current private checkout intentionally remains remote-free. Its runtime,
continuity, and development history are not publication material.

The deterministic release policy selected 324 source files. The initial clean
root and each subsequent public hardening commit independently retained that
same file boundary. The current public tree reports:

- public-tree audit errors: 0;
- candidate files: 324;
- tracked public files: 324;
- private tracked paths included: 0.

The private source checkout still has no Git remote. Its dirty-worktree,
remote-free, and excluded-private-material warnings remain evidence about the
source boundary, not findings in the published repository.

The export policy excludes, among other things:

- conversations, imported transcripts, user profiles, and relationship memory;
- `.eve`, `.openclaw`, coordination, Beads/Dolt, generated wiki/dream, and
  runtime mirror state;
- model weights, private datasets, embeddings, hidden probes, backups, logs,
  databases, and credentials;
- owner-specific launch configuration and private project history;
- isolated experimental adapters that were still under separate review when
  the first public source snapshot was frozen.

The source release gate now emits a deterministic schema 2 manifest containing
sorted relative paths, byte counts, per-file SHA-256 digests, total bytes, and a
canonical tree digest. Export is transactional: it copies into a sibling
staging directory, re-audits that staged tree, requires exact manifest parity,
and renames it into place only after both checks pass. The verifier rejects
path traversal, duplicate or unsorted entries, summary tampering, changed or
missing files, non-regular files, and unmanifested tree content. This is the
mechanism intended to compare a reviewed source candidate, GitHub root, and
extracted release archive; a manifest that was merely generated is not proof
until verification succeeds against the independently obtained tree.

The public `.gitignore` independently defaults secrets, environments, model
files, local training data, continuity stores, OpenClaw state, and generated
runtime material to local-only.

## Portability and install result

Public defaults are user-neutral and local-first:

- no source behavior asset assumes the maintainer's name or home directory;
- the default inference backend is `llama.cpp`;
- five logical lanes map onto three resident substrates by default;
- model files, hosted providers, background services, and OpenClaw are never
  installed or enabled as an implicit bootstrap side effect;
- missing optional learned artifacts do not prevent a clean source install or
  runtime sync;
- update bundles use an explicit source allowlist and exclude private/runtime
  roots.

`bin/eve_bootstrap.py` has been exercised in an isolated clean export with
Python 3.12. The locked core/dev environment installed successfully, and an
isolated runtime sync reported matching first-party source/runtime hashes while
honestly marking optional learned artifacts unavailable.

The source install now also creates one stable `eve` command inside the locked
environment. Its Unix and Windows launchers locate `eve.py` relative to the
environment, contain no checkout-specific absolute path, and are installed by
same-directory atomic replacement. A relocation test moved a checkout into a
path containing a space and verified exact argument forwarding. The launcher is
an interim source-install contract only: no wheel, PyPI distribution, daemon,
model, or external provider is implied.

Bootstrap execution truth is now explicit. Schema-2 `install --json` isolates
child output and emits one final result with a terminal status, completed-step
count, exact failed command, rollback flag, and bounded 8 KiB diagnostic tail.
The executor stops before all later commands on a failed or unstartable step.
Human-readable mode reports the same partial-progress boundary without a Python
traceback. This does not make install transactional: previously completed
environment or runtime-sync steps remain in place and are truthfully reported
as not rolled back.

## License and provenance result

- Eve's original source is Apache-2.0.
- The notice inventory covers all 17 declared direct dependencies at their
  locked versions.
- `bin/eve_dependency_license_audit.py` reports zero direct-dependency errors
  and zero warnings.
- `mlx-embeddings` and `arize-phoenix` are forbidden public declarations; Eve
  does not distribute or install them through project extras.
- External runtimes and model weights retain their own licenses and are not
  distributed as Eve source.

GitHub currently generates an SPDX dependency-graph SBOM with 187 package
records, and Dependabot reports zero open alerts. The complete transitive
license review remains a gate for the first public tag. Weekly `uv` and GitHub
Actions Dependabot updates support that review; they do not replace it.

Every checkout in the public release and scheduled SBOM workflows now sets
`persist-credentials: false`. Workflow permissions remain `contents: read`, all
external actions remain full-SHA pinned, and no `pull_request_target` or
`workflow_run` trigger executes checked-out contribution code. The workflow
contract test enforces checkout-count parity with explicit non-persistence so a
future job cannot inherit authenticated Git access by omission.

The source candidate now also carries the advanced Python CodeQL workflow that
was already present in the personal public repository. It uses interpreted
`build-mode: none`; runs on push, ordinary pull request, weekly schedule, and
manual dispatch; and does not install or execute repository code. Its analysis
job grants `contents: read` plus the single `security-events: write` permission
needed to upload CodeQL results. Immutable checkout/CodeQL pins, credential
non-persistence, matching init/analyze revisions, trigger safety, and the absence
of other write scopes are enforced by the workflow contract test.
The release policy now lists CodeQL, the scheduled transitive-SBOM/license
gate, Dependabot, and the main release audit as required files rather than only
allowlisted files. The deterministic candidate audit therefore blocks an
export if any of these controls is missing; this is source-policy evidence, not
proof that a newly exported revision has already run on GitHub.

## Security evidence

Bounded secret-pattern scans found no high-confidence credential signature in
the candidate. A checksum-verified Gitleaks 8.30.0 scan also reported no leak in
the private history, but the private history remains non-public because it
contains personal material that is not a credential.

The new public history begins from clean root commit `cb45f3a`. CI independently
runs the deterministic release audit, direct dependency-license audit, portable
runtime contracts, full-root Gitleaks scan, and pull-request dependency review.

On public commit `c09d412`, release run `32659127007` passed `core-contracts`,
`release-audit`, and `secret-history`. CodeQL run `32659126815` passed all
configured language jobs and left zero open code-scanning alerts after the
reviewed HTTP, HTML, local-storage, proxy-error, and policy-classification
hardening. Dependabot also reports zero open alerts.

The personal repository has secret scanning, push protection, Dependabot
security updates, and private vulnerability reporting enabled. Local continuity
files are created owner-only (`0600`); `SECURITY.md` explicitly documents that
they remain plaintext application data and are not a credential vault.

`main` is protected for the single-maintainer phase: pull requests are required
with zero mandatory reviewers, the four public-release jobs are required and
strict, administrators are included, linear history and conversation resolution
are required, and force-pushes and branch deletion are disabled.

## Local verification

Observed passing checks include:

- 27 release-audit, bootstrap, dependency, and portability contracts;
- 245 capability-intelligence, topology, OpenClaw, bootstrap, and portable
  runtime contracts in the current public CI group;
- 37 specialist-substrate contracts, including strict Hermes JSON behavior;
- direct dependency inventory: 17 dependencies, 0 errors, 0 warnings;
- `uv lock --check`;
- OpenClaw template JSON validation and shell syntax checks;
- public candidate audit: 0 errors.

These groups overlap intentionally; each command is a bounded gate rather than
an inflated unique-test count.

## Remaining gates before a public tag

1. Review the GitHub dependency-graph SBOM and every unresolved transitive
   license.
2. Verify native app launch, chat, and service status on supported macOS.
3. Verify start/stop restores every Eve-owned service without ambiguous state.
4. Only then consider a signed pre-release tag; do not describe the current
   pre-alpha source as stable.

## Reproduction

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run python -m unittest \
  tests.test_public_release_audit \
  tests.test_eve_bootstrap \
  tests.test_dependency_license_audit \
  tests.test_public_portability

uv run python bin/eve_dependency_license_audit.py --json
python3 bin/eve_public_release_audit.py \
  --root . \
  --full

python3 bin/eve_public_release_audit.py \
  --root . \
  --write-manifest /path/outside/eve-public-manifest.json \
  --export /path/outside/eve-public-export \
  --full

python3 bin/eve_public_release_audit.py \
  --root /path/outside/eve-public-export \
  --verify-manifest /path/outside/eve-public-manifest.json \
  --exact-tree \
  --full
```

Export remains fail-closed and refuses a non-empty destination or a candidate
with a blocking finding. Manifest output is required to remain outside the
audited source and exported tree so it cannot invalidate or self-reference the
artifact it describes.
