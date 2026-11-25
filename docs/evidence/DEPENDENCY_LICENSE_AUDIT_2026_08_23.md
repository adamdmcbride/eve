# Eve Dependency License Audit

Status: evidence-log  
Last reviewed: 2026-08-23  
Current authority: direct-dependency review complete; exact public SBOM reviewed; next-SBOM recheck pending  
Supersedes: none  
Superseded by: none

## Decision

Keep Eve's public install groups permissive. Do not declare or automatically
install `mlx-embeddings` or `arize-phoenix` in the public project metadata.
Their integrations may remain detectable and user-managed.

This is release engineering, not legal advice.

## Method

1. Read the exact direct dependency versions from `uv.lock`.
2. Queried official PyPI JSON metadata for each direct dependency.
3. Downloaded the exact py-trees 2.4.0, mlx-embeddings 0.1.0, and
   arize-phoenix 14.6.0 source distributions from PyPI.
4. Verified each archive against the SHA-256 recorded by PyPI.
5. Downloaded the exact LanceDB 0.37.1 macOS arm64 wheel and verified its PyPI
   SHA-256 before reading the bundled license.
6. Recorded the reviewed direct dependency inventory in
   `THIRD_PARTY_NOTICES.md`.
7. Added `bin/eve_dependency_license_audit.py` and
   `tests/test_dependency_license_audit.py` so project metadata, `uv.lock`, the
   notice inventory, install groups, reviewed versions, and forbidden direct
   dependencies cannot drift silently.
8. Retrieved GitHub's SPDX 2.3 SBOM for public `main`
   `e33ce6d9512fc549a6fa65c444c08af5952da3ea`, generated at
   `2026-08-23T19:20:07Z`: 187 packages, 414 dependency relationships, SBOM
   SHA-256 `227dfdf79159d4be82f2b6adc0c730bb14a6b052bf2896f9189eed8f4d262073`.
9. Verified the three pinned GitHub Actions' exact license files as MIT and
   recorded their immutable URLs and hashes in `public_release.json`.
10. Resolved two scanner-overbroad package conclusions against exact official
    PyPI JSON: `aiohappyeyeballs==2.7.1` and `typing-extensions==4.16.0` both
    declare PSF licensing. Their exact metadata hashes are recorded in policy.
11. Resolved the SBOM root package's `NOASSERTION` against the exact Apache-2.0
    `LICENSE` at public-main commit `e33ce6d9512fc549a6fa65c444c08af5952da3ea`;
    its SHA-256 is
    `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30`.
12. Bound SBOM review to the checkout's complete resolved Python package
    inventory: every registry package/version in `uv.lock`, plus the project
    name/version, must
    exactly equal the SBOM's PyPI package URLs. Non-Python packages such as
    pinned GitHub Actions remain independently license-reviewed. The audit also
    records the exact `uv.lock` SHA-256.

No dependency archive or third-party license copy is added to the Eve source
tree by this audit.

## Exact artifact evidence

| Artifact | SHA-256 | Observed license |
| --- | --- | --- |
| `py_trees-2.4.0.tar.gz` | `cd8738a80e7422aec2b133270b6aa92e3e83926ded2ba9b3614028dba99cdb41` | BSD 3-Clause text |
| `lancedb-0.37.1-cp310-abi3-macosx_11_0_arm64.whl` | `c15c46f23cf6959c79fb93cdba2c76536cf784d3134386662da03dc6ccac3c26` | Apache-2.0 text |
| `mlx_embeddings-0.1.0.tar.gz` | `f80c1e1be26ff7bd22b15c1fba4cc03afd44c86e00a431b5fa75ffd7500affb1` | GNU GPL v3 text |
| `arize_phoenix-14.6.0.tar.gz` | `0203f5d0a2a94be60f5ca964f8f0b6cb1509b3ea7f123edad9269bcff28d9a38` | Elastic License 2.0 text |

## Result

- `mlx-embeddings` was removed from the `techlab` extra.
- `arize-phoenix` was removed from the `oss-lab` extra.
- `peft` was removed from the public `oss-lab` extra. Its exact SBOM path was
  `Eve -> PEFT 0.20.0 -> Torch 2.13.0 -> CUDA toolkit`; that path introduced
  seven `LicenseRef-NVIDIA-Proprietary` packages and two CUDA packages with
  `NOASSERTION`. PEFT remains a detectable, separately installed lab tool; this
  change removes automatic public distribution, not Eve's governed adapter capability.
- DVC and Ragas were removed from the public `oss-lab` extra after the initial
  GitHub dependency graph exposed open advisories with no patched release for
  their affected dependency paths. Their optional probes remain fail-closed
  and user-managed rather than installing a knowingly vulnerable graph.
- `public_release.json` lists all three license-blocked direct dependencies as
  forbidden declarations.
- The release audit fails if either dependency is reintroduced into
  `pyproject.toml`.
- Existing optional integration probes remain non-authoritative and can report
  a separately installed local component.
- Deterministic direct-dependency gate: 16 declared dependencies, zero errors,
  zero warnings.
- The dependency audit now accepts `--sbom <spdx.json> --source-revision <sha>`
  and fails closed on unresolved or non-permissive transitive licenses unless
  an exact package URL has a reviewed effective license, evidence URL, and
  evidence SHA-256 in `public_release.json`. SBOM runs require an immutable
  full-length revision and record the analyzed artifact's own SHA-256 and SPDX
  creation metadata.
- The current pre-removal public SBOM correctly remains blocked with ten
  errors after the six exact evidence overrides: seven proprietary NVIDIA
  packages, two unresolved CUDA packages, and one stale-lock-inventory finding.
  Its PyPI graph contains all 147 currently expected package identities plus
  26 pre-removal extras (`peft`, `torch`, and their acceleration graph). The
  audit reviewed 178 of 187 packages and reported zero warnings.

## Remaining gate

Merge the PEFT removal through the protected public PR flow, wait for GitHub's
dependency graph to regenerate, then run the conservative SPDX audit against
that new exact commit. The current published SBOM is expected to remain blocked
because it truthfully describes the pre-removal commit. Any remaining unknown,
conflicting, source-available, or proprietary transitive license remains a tag
blocker until explicitly resolved. No first public tag should be created before
that new-SBOM readback passes.
