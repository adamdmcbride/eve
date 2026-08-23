# Eve Dependency License Audit

Status: evidence-log  
Last reviewed: 2026-08-23  
Current authority: direct-dependency review complete; transitive inventory pending  
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
- DVC and Ragas were removed from the public `oss-lab` extra after the initial
  GitHub dependency graph exposed open advisories with no patched release for
  their affected dependency paths. Their optional probes remain fail-closed
  and user-managed rather than installing a knowingly vulnerable graph.
- `public_release.json` lists both as forbidden declared dependencies.
- The release audit fails if either dependency is reintroduced into
  `pyproject.toml`.
- Existing optional integration probes remain non-authoritative and can report
  a separately installed local component.
- Deterministic direct-dependency gate: 17 declared dependencies, zero errors,
  zero warnings.

## Remaining gate

Publish the clean source root first, then generate and review GitHub's
dependency-graph SBOM for that exact root commit before the first public tag.
GitHub supports `uv` version updates and transitive dependency submission, so
the repository includes a weekly `uv` Dependabot configuration in addition to
the deterministic direct-dependency gate. Any unknown, conflicting, or
source-available transitive license remains a tag blocker until explicitly
resolved.
