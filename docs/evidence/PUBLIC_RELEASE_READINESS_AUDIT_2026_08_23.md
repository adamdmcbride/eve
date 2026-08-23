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
```

Export remains fail-closed and refuses a non-empty destination or a candidate
with a blocking finding.
