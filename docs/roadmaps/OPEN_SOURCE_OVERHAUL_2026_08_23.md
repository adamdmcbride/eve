# Eve Open-Source Overhaul

Status: active
Last reviewed: 2026-08-23
Current authority: published pre-alpha source; tagged release gated
Supersedes: none
Superseded by: none

## Outcome

Ship Eve as a trustworthy, understandable, local-first product from the user's
personal GitHub account without publishing the user's runtime, conversations,
memory, machine paths, credentials, or private development history.

This is not a big-bang rewrite. Eve is alive, heavily integrated, and being
changed by other bounded workstreams. The overhaul must preserve observable
behavior behind compatibility seams while making each seam testable and
replaceable.

## Product story

The public product should be explainable in one sentence:

> Eve is a local AI counterpart that maintains one coherent identity while
> allocating attention across five modes and acting through governed organs.

Everything public should reinforce that story. A contributor should not need to
understand a 100,000-line command file, a personal runtime database, or a wall
of internal evidence to install Eve, talk to her, inspect what she is doing, and
decide what she may do.

## Non-negotiable boundaries

- One Eve; lanes are attention modes, not personalities.
- Five logical lane contracts may share resident model processes.
- Runtime state, user profiles, memories, conversations, logs, model weights,
  local evidence, and coordination ledgers are never source distribution.
- OpenClaw is an admitted action/body organ, Hermes is proposal-only learning,
  and Codex is a separate operator.
- Public defaults must not name or assume the repository owner.
- No action, learning proposal, model update, or self-repair claim becomes true
  without its owned verification path.
- The current private Git history will not be made public.

## Phase 0 — safe release boundary

Current checkpoint: complete for the initial public source snapshot. The
private checkout remains remote-free; a zero-error candidate is exported into a
new history and re-audited before publication.

Deliverables:

- deterministic include/exclude policy in `public_release.json`;
- read-only secret, privacy, portability, license-metadata, and tracked-private
  material audit;
- export that refuses to run until the audit is clean and refuses non-empty
  destinations;
- hashed candidate manifest;
- Apache-2.0 root license for user-authored work;
- contribution, conduct, security, issue, pull-request, and CI foundations;
- independent full-history secret scan before publication.

Exit gate: a clean candidate tree can be generated without transformations and
passes the audit a second time after copying.

## Phase 1 — separate product from person and machine

Current checkpoint: complete for the initial public source boundary. Public
defaults, behavior assets, installer paths, service labels, web/native source,
and runtime configuration are user-neutral; local identity and runtime material
remain excluded. Further first-run productization is still planned, but it no
longer blocks publication of the pre-alpha source.

1. Replace hard-coded home paths with a single platform/configuration service.
2. Generate LaunchAgents from portable templates; do not ship owner-specific
   labels or paths as executable defaults.
3. Move the human's name, relationship context, channels, and preferences into
   first-run local configuration.
4. Keep generic prompt contracts in source and render local user context at
   runtime.
5. Stop tracking imported conversations, generated memory/wiki/dream material,
   coordination logs, dataset pointers, and private operator history.
6. Replace the oversized private README with a concise public product guide;
   retain deep doctrine in a navigable architecture shelf.
7. Add synthetic example configuration and fixtures that contain no real user
   or machine data.

Exit gate: a fresh macOS user can clone the candidate and no source file assumes
the user's username, home directory, email, conversations, or existing runtime.

## Phase 2 — turn the monolith into a compatibility facade

The end state is a small executable facade over explicit packages, not a second
implementation beside the first:

```text
eve/
  core/          identity, scheduler, autonomy, governance contracts
  cognition/     lane admission, reply council, active mind
  continuity/    memory, evidence, experience, commitments
  organs/        OpenClaw, Hermes, Codex, Beads, Dagster adapters
  runtime/       configuration, state roots, process and model supervision
  interfaces/    HTTP/OpenAI compatibility, web, native app contracts
  cli/           thin command registration and presentation
```

Migration rules:

1. Add characterization tests around a bounded command family.
2. Extract implementation into one owned module.
3. Re-export the existing name from `eve.py` so callers and tests keep working.
4. Verify source/runtime parity and narrow integration behavior.
5. Only then remove duplicate implementation.

Start with low-coupling command and presentation families already partially
separated under `eve_commands/`; do not begin with the scheduler, memory
authority, or final reply path while other work is active there.

Exit gate: `eve.py` is a compatibility entrypoint and composition root rather
than the owner of domain behavior.

## Phase 3 — make installation a product

- Turn the Python project into a real installable package with an `eve` CLI.
- Provide `eve init`, `eve doctor`, `eve start`, `eve stop`, and `eve status` as
  the supported lifecycle.
- Detect or configure llama.cpp; never bundle model weights.
- Provide a model manifest with compatible examples, checksums, memory budgets,
  and honest optional features.
- Make the native Mac app talk to a versioned local API contract.
- Build, sign, notarize, and package the Mac app only after the source install is
  reproducible.
- Keep web UI and native UI as clients of the same state and conversation
  contracts, not separate products with divergent behavior.

Exit gate: a clean Mac can install, initialize, start, chat, inspect services,
and uninstall without editing source paths.

Interim bootstrap: `python3 bin/eve_bootstrap.py check` and
`python3 bin/eve_bootstrap.py install --dry-run` provide a reviewed source
installation contract while the monolith is still a compatibility facade. The
bootstrap is intentionally not a substitute for the final package/CLI.

## Phase 4 — quality and security

- Split hermetic unit/contract tests from model/runtime/integration tests.
- Run Linux tests for portable core and macOS tests for app/runtime integration.
- Add formatting, static typing at public boundaries, dependency review, SBOM,
  license inventory, secret scanning, and CodeQL.
- Threat-model loopback HTTP, filesystem roots, action admission, prompt/tool
  injection, channel adapters, updates, plugins, MCP, and model artifacts.
- Establish performance budgets for idle CPU, resident memory, first reply,
  streaming cadence, model switching, and app launch.
- Measure before optimizing; never hide degraded behavior behind a green label.

Exit gate: protected default branch, reproducible CI, no unresolved critical
findings, and a documented rollback for each state migration.

## Phase 5 — personal GitHub public beta

Current checkpoint: the clean source is published at the configured personal
GitHub repository. The private checkout remains remote-free. The
324-file public boundary, Apache-2.0 license, CI, full-history Gitleaks scan,
CodeQL, Dependabot, secret scanning, push protection, and private vulnerability
reporting are live. The default branch requires pull requests, strict release
checks, linear history, and conversation resolution, and blocks force-pushes and
deletion. CodeQL and Dependabot currently have zero open alerts. A version tag
remains gated by the complete release definition below.

1. Keep repository ownership personal and independent from Eden.
2. Maintain `main` protection with the established release checks, linear
   history, no force pushes or deletion, and a pull-request requirement with
   zero mandatory reviewers while the project has one maintainer.
3. Complete native app and full Eve-service lifecycle verification on supported
   macOS.
4. Complete transitive dependency-license review; do not equate a generated
   SBOM or zero vulnerability alerts with license clearance.
5. Publish a limitations page: local-first is not zero-risk, consciousness-like
   evidence is not proof of subjective experience, and optional organs have
   distinct authority.
6. Only after those gates, create a signed pre-release tag and verify its archive
   against the reviewed public manifest.

Exit gate: the tagged archive independently matches the reviewed manifest; the
private working repository remains remote-free.

## Phase 6 — community without architecture drift

- Publish a small roadmap organized by user outcomes, not internal subsystem
  count.
- Label good first issues around docs, portability, tests, and accessibility.
- Require an architecture decision record for authority, identity, state, or
  model-topology changes.
- Add plugin/organ extension contracts only after two real integrations prove
  the seam.
- Keep experimental research in labs until it passes named promotion gates.

## Definition of first public release

The first release is ready only when all of these are true:

- public audit: zero errors;
- full Git history secret scan: zero unreviewed findings;
- license and third-party provenance inventory: complete;
- clean-machine installation: verified;
- core unit/contract suite: green;
- native app launch/chat/service status: verified on supported macOS;
- start/stop removes and restores all Eve-owned services without ambiguity;
- public documentation contains no owner-specific identity or private state;
- exact exported manifest equals the GitHub root commit and release archive.
