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
- independently verifiable candidate manifest with per-file size/digest plus a
  canonical whole-tree digest;
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
bootstrap is intentionally not a substitute for the final package/CLI. Its
execution environment uses the host platform's temporary directory rather than
assuming a Unix `/tmp` path. A successful locked sync now atomically installs a
relocation-safe `.venv/bin/eve` (or Windows `.cmd`) source command before any
optional runtime-mirror sync. The command derives the checkout from its own
location rather than persisting a maintainer or install path, forwards signals
and arguments to the existing `eve.py` facade, and does not start services.
The bootstrap's schema-2 JSON mode now emits one final document rather than a
plan followed by interleaved child output. It records `blocked`, `planned`,
`completed`, or `failed`, the exact failed step and prior completed-step count,
and an 8 KiB output tail. Child output is routed through a temporary file, not
held unbounded in memory; later steps stop after failure and completed earlier
steps are reported as not rolled back. Text mode fails with the same bounded
diagnosis instead of a Python traceback.
The project deliberately remains `package = false` until the flat modules can
move behind a real package without maintaining a second implementation.

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

Current CI checkpoint: the public workflow now runs shared store, database,
tracing, attachment, and runtime API contracts on Linux, plus native bridge
typechecks and canonical-app architecture tests on GitHub's macOS 26 runner.
The macOS job is a source/typecheck gate, not yet the clean-machine
install-launch-chat-stop-start proof required for a release tag.
All public checkout steps explicitly disable credential persistence. Combined
with workflow-level `contents: read`, immutable action SHAs, and ordinary
`pull_request` rather than privileged untrusted-code triggers, repository tests
cannot reuse the checkout credential for authenticated Git operations. A
contract test counts every checkout in both public workflows so a newly added
job cannot silently regress this boundary.

Supply-chain checkpoint: a separate read-only workflow runs weekly or by
manual request on the default branch. It exports GitHub's current SPDX
dependency graph with only `contents: read`, caps the download, and verifies
both conservative transitive licenses and exact parity with the checkout's
resolved Python package inventory. It intentionally does not run for pull
requests or pushes, where dependency-graph regeneration can lag the source
commit; a green run is still required against the exact release candidate
before tagging.

Release-scanner checkpoint: candidate reads are now bounded at the configured
size before content enters memory, rechecked after a no-follow open, and
limited to regular files. Oversized source cannot create an avoidable memory
spike, and pipes or device-like paths cannot stall the privacy/secret gate.

Artifact-integrity checkpoint: export now copies into a private sibling staging
directory, re-runs the release audit there, verifies every byte against the
source manifest, rejects extra files, and only then atomically exposes the
destination. Failed copy or validation leaves no partial release tree. Manifest
schema 2 records sorted paths, sizes, SHA-256 digests, total bytes, and one
canonical tree digest; the verifier still accepts schema 1 manifests for
backward compatibility. CI round-trips the candidate through export and exact
manifest verification rather than treating manifest generation as proof.

Loopback-security checkpoint: the runtime API and canonical app proxy now use
one pure mutation-request policy before POST dispatch. It rejects browser
requests marked cross-site, rejects foreign Origins, and requires an
`application/json` (or structured `+json`) media type, closing the simple-form
and `text/plain` CSRF path that CORS response filtering does not stop. Native,
CLI, and backend clients without browser headers remain compatible when they
send JSON. This is not authentication against a hostile local process or a
license to expose Eve's ports beyond loopback.
The same two servers now share one exact request-body framing helper. It
requires a single ASCII Content-Length, rejects unsupported transfer encoding
and over-budget declarations before reading, rejects premature EOF, and closes
the connection whenever rejected framing could leave bytes unread. Ordinary,
sensory, attachment, and app-proxy JSON retain separate byte budgets. This
bounds admitted allocation and persistent-connection parsing; it is not a
slow-connection defense or local-process authentication, and it remains
source-only until the runtime API and app proxy deploy together.
Runtime query parsing is now shared and typed rather than repeated across every
GET handler. Queries are capped at 8 KiB/32 fields; consumed values are
singular, printable, and role-bounded; integers and Booleans reject permissive
coercions; list/lookback/stream requests have explicit ceilings. Eve.app applies
the same parse/resource budget before proxying; both HTTP surfaces close on a
rejected POST query. Unknown but well-formed fields remain ignored for
compatibility. This is
read-amplification and ambiguity control, not authentication or rate limiting,
and it joins the pending atomic transport bundle.
Request targets and dynamic paths now use shared `eve_http_path.py` primitives.
Only bounded origin-form targets are admitted; strict percent/UTF-8 decoding
rejects controls; model/message/thread/proposal/follow-up routes match one exact
bounded opaque segment; extra raw segments cannot partially dispatch. Eve.app
rebuilds a canonical path before forwarding, and local web/native clients encode
IDs as a single segment. No-argument mutations now consume their exact JSON
object, while unknown or invalid POSTs close with the body unread. This removes
route and keep-alive ambiguity, not the need for authentication outside
loopback, and it remains part of the pending atomic transport bundle.
Consumed headers and chat transport metadata now have one finite schema.
`eve_http_headers.py` preserves duplicate occurrences and rejects ambiguous,
non-ASCII, control-bearing, or over-budget Origin/Fetch Metadata/Content-Type
values before mutation dispatch. OpenWebUI header IDs are ASCII and capped at
160 characters; JSON OpenWebUI/client/AG-UI IDs are printable and capped before
hashing, persistence, proxy forwarding, or event construction. Model selectors
are capped at 80 characters and direct OpenAI-compatible histories at 128
messages. This closes a header-outside-body-budget amplification path; it does
not authenticate another local process and remains in the pending atomic HTTP
bundle.
Decoded conversation values now use shared `eve_http_json.py` primitives rather
than route-specific `str(...)`, truthiness, list acceptance, or silent slicing.
Message bodies/subjects/IDs, attachment and tag lists, and Boolean controls have
explicit type and size limits before dispatch, with defensive service checks
before persistence. Eve.app rejects over-budget personal replies instead of
truncating them. The portable pure-field tests run in Linux CI. This remains a
source-only compatibility/security boundary in the same pending atomic HTTP/app
deployment bundle; it does not change reply routing or the five-lane contract.
The CopilotKit/AG-UI protocol family is now extracted from `eve_web.py` into
`eve_agui.py` with compatibility re-exports. Consumed prompt/model fields are
typed and bounded; message roles, plain text, and text content-parts are also
type-checked with an 8,000-character visible-content ceiling. Conflicting
thread/run/client aliases reject before dispatch, and generated event IDs use a
bounded deterministic hash suffix. Portable characterization tests lock the
existing message, progress, and completion shapes. This reduces HTTP-monolith
ownership without creating a new conversation implementation, model route,
identity, or lane; deployment stays coupled to the pending runtime HTTP bundle.
The deterministic Eve Chat follow-up and external transport protocol now lives
in `eve_chat_protocol.py` instead of the HTTP monolith. Explicit deferred-intent
parsing, bounded relative due times, the fixed supported-check vocabulary,
external chat-ID normalization/hashing, synthetic-evaluation admission, and
receipt/delivery projections retain compatibility re-exports. The extracted
module cannot schedule, lease, execute, persist, deliver, or select a lane;
`EveRuntimeService` still owns those side effects and existing ledgers remain
authoritative. Portable characterization tests lock facade identity, one-way
layering, deterministic timing, origin allowlisting, external-ID opacity, and
the rule that an unverified action cannot become successful durable evidence.
This removes about 400 more protocol lines from `eve_web.py` without changing
follow-up, reply-routing, or five-lane behavior and joins the same pending
atomic runtime deployment bundle.
Because stdlib `ThreadingHTTPServer` otherwise creates a thread per accepted
connection, the two loopback surfaces now also share a 32-worker admission
gate, an explicit 32-connection listen backlog, and a 30-second client-I/O
inactivity timeout. Excess connections close before thread creation and slots
release on normal completion or thread-start failure. Long model computation
is not assigned a fake 30-second deadline; the timeout applies when reading or
writing the client socket. This source boundary reduces local resource
amplification but does not turn Python `http.server` into an internet-facing
production stack.
Response privacy is now shared as well. Local state, API, stream, download, and
static responses are no-store, no-sniff, and no-referrer; static documents add
strict Eve-local CSP/frame/device policy while API responses preserve admitted
cross-origin loopback clients. The product Server token no longer includes the
host Python version. Eve.app logs only bounded escaped method/path/status
metadata, not raw request lines, queries, formatter arguments, or controls.
This is source-only until the same atomic transport bundle is deployed.
Unexpected HTTP failures now use one content-free disclosure contract. Runtime,
OpenAI-compatible, monitor-SSE, AG-UI, app-proxy, and unhandled server failures
return generic client text plus an opaque 16-hex error ID while the local log
keeps only ID, fixed surface/operation, and exception type. Eve.app never relays
an upstream 5xx body or transport reason; bounded 4xx detail remains compatible.
The correlation ID is not completion or recovery evidence. This source boundary
also joins the pending atomic transport deployment.
Generated installer, bootstrap, and update artifacts now use a server-owned
advertised endpoint rather than the request's untrusted `Host` header. Explicit
DNS/IPv4 configuration is available through the standalone server option or
`EVE_ADVERTISED_HOST`; legacy query copies must match that configured endpoint,
the model port is strictly validated, and artifact builders revalidate before
interpolation. Wildcards, URI/shell
syntax, Unicode, IPv6 literals, and invalid ports fail closed. IPv6 artifact
URLs remain an explicit unsupported limitation until every generated platform
script is bracket-safe. This is also part of the pending atomic transport
deployment.
The complete packaging/presentation family is now extracted from `eve_web.py`
into `eve_install_artifacts.py`, with compatibility re-exports and unchanged
HTTP endpoints. Characterization tests lock facade identity, one-way layering,
advertised-endpoint authority, portable archive entries, and current artifact
bytes. This removes about 1,170 non-HTTP lines from the server module without
changing install behavior. Legacy Ollama-named bootstrap fields and its opt-in
local-install branch remain explicit migration debt; Eve's default runtime is
still llama.cpp, and a clean-machine replacement is a separate Phase 3 gate.

Performance-analysis checkpoint: latency grouping, percentiles, and terminal
presentation now live in pure `eve_performance.py`, with the old `eve.py` names
retained as aliases. Existing unlabelled records remain measured for backward
compatibility. Producers can explicitly mark an observation `inconclusive` or
`invalid`; those samples stay visible in counts but cannot distort measured
latency or measured-failure totals. Malformed, negative, Boolean, NaN, and
infinite durations fail closed as invalid rather than crashing the summary or
becoming fake timing evidence. This creates a trustworthy analysis seam; it
does not yet establish the idle CPU, memory, first-reply, streaming, model
switch, or app-launch budgets required by this phase.

Monitor record conversion, local process/memory/disk sampling, and compact/full
dashboard assembly now live in `eve_monitor_projection.py`, removing more than
1,100 lines from `eve_web.py` while preserving 52 compatibility re-exports and
the two existing service methods. Numeric values are
finite before JSON projection, and process rows retain their shape without
returning command arguments, paths, prompts, or tokens. Characterization tests
cover facade identity, one-way layering, finite values, redaction, bounded
selection, existing record transforms, bounded status shaping, and compact-path
exclusion of full-only runtime readers. This is source modularization and a
privacy boundary—not measured idle-resource performance or proof that missing
OS telemetry means healthy.

Model-health, model/system activity, and latest-state assembly now live in
`eve_runtime_projection.py`, removing roughly 184 implementation lines from
`EveRuntimeService`. The module has a one-way dependency on existing Eve and
monitor readers and cannot own HTTP, caches, model calls, lane selection,
durable writes, or daemon control. `EveRuntimeService` retains refresh locks,
TTL caches, invalidation, and compatible build methods; patchable path/version
constants are captured in an immutable injected configuration. This is
source-only modularization, not a new health signal or performance claim, and
the new module must deploy atomically with the latest `eve_web.py`.

Private sensory-session lifecycle is now composed through
`eve_sensory_sessions.py` rather than implemented inside
`EveRuntimeService`. The service owns high-entropy token authorization, token
hashing, expiry, rate/concurrency/event budgets, restart rehydration, durable
cross-process feature-event writes, stop finality, and bounded integration
triggers. `EveRuntimeService` retains HTTP composition and compatible wrappers;
database-path and policy snapshots are injected. Characterization tests retain
the legacy patch seams and prove that neither raw tokens nor token hashes leave
the public projection. This removes roughly 370 service lines without enabling
capture, weakening privacy, or changing model/lane behavior. It remains
source-only and must deploy atomically with the latest `eve_web.py`.

Eve.app refresh checkpoint: the canonical app now reads one versioned
`eve_app_snapshot.v1` conversation snapshot plus the independent presence
projection instead of issuing six ledger requests, a follow-up request, and a
recurring status probe. The configured ten-second visible and 60-second hidden
cadences are preserved, visibility/online transitions refresh immediately, one
request remains in flight, and failure-only status/follow-up fallbacks keep the
last good conversation usable. This reduces deterministic browser GET count
from about 44 to 12 per visible minute and from nine to two per hidden minute;
it is not yet measured idle-CPU or battery evidence. Source, runtime endpoint,
app proxy, and rebuilt app must be deployed atomically before this is a live
claim. See
[`EVE_APP_REFRESH_CONTRACT_2026_08_23.md`](../architecture/EVE_APP_REFRESH_CONTRACT_2026_08_23.md).
The same source contract now makes `/health` return success only when both the
surface and local conversation backend are ready. The launcher requires that
backend evidence and will signal a PID-file process only after validating a
positive non-system PID and matching `eve_app_server.py` command, preventing a
stale reused PID from killing an unrelated process. This is app/backend startup
truth, not a whole-Eve service-health claim. The app builder applies the same
ownership check and falls back from stale PID hints to the actual port listener
before deciding whether an old Eve surface may be stopped.
The native Swift app now executes the verified launcher path directly and waits
for its real exit status instead of interpolating it through a detached
`zsh -lc` command whose successful background spawn could hide launcher
failure. Long-lived services still detach inside the owned launcher.
Its health monitor now requests checks every 30 seconds while active and every
120 seconds while inactive, then checks immediately on foregrounding; the
two-failure recovery gate remains and retries after two seconds when active.
Together with the snapshot change, requested
browser-plus-native surface GETs fall from about 48 to 14 per active minute and
13 to 2.5 per inactive minute. These are source-derived counts, not energy
measurements, and macOS may coalesce inactive timers.
The app proxy now reuses a thread-safe 12-second positive backend-reachability
hint from real successful proxy traffic, while negative hints expire after one
second. Native `/health` therefore normally avoids a redundant `/v1/models`
request when the live timeline just succeeded, but stale/missing evidence still
performs the bounded probe. No response content is cached.
Native launcher diagnostics no longer rely on a `Pipe` that remains unread
until process exit. Source now streams stdout/stderr to a fresh `0600`,
no-follow local log and reads only the final 32 KiB into the app after exit.
This removes pipe-buffer deadlock risk and bounds diagnostic ingestion without
changing the launcher's ownership of long-lived service detachment. It remains
source-only until the coordinated Eve.app rebuild.
The app proxy now enforces independent upstream byte budgets before committing
non-stream response headers: 8 MiB for admitted API reads, 2 MiB for compact
presence, and 64 KiB for backend errors. It checks both `Content-Length` and
actual bytes, treats an incomplete declared body as unhealthy, and never echoes
a rejected body. Chat replies retain 64 KiB incremental streaming rather than
whole-response buffering. This is also pending the atomic runtime/app deploy.

## Phase 5 — personal GitHub public beta

Current checkpoint: the clean source is published at the configured personal
GitHub repository. The private checkout remains remote-free. The
324-file public boundary, Apache-2.0 license, CI, full-history Gitleaks scan,
CodeQL, Dependabot, secret scanning, push protection, and private vulnerability
reporting are live. The default branch requires pull requests, strict release
checks, linear history, and conversation resolution, and blocks force-pushes and
deletion. CodeQL and Dependabot currently have zero open alerts. A version tag
remains gated by the complete release definition below.

The advanced Python CodeQL definition is now retained in the private source
candidate as `.github/workflows/codeql.yml`, closing the source/public workflow
parity gap. It performs build-free Python analysis on push, pull request, a
weekly schedule, and manual dispatch. Checkout and both CodeQL actions are
full-SHA pinned, checkout credentials are not persisted, and the analysis job's
only write capability is GitHub's required `security-events: write` SARIF upload
permission. It does not install dependencies or execute repository scripts.
CodeQL, the scheduled transitive-SBOM/license gate, Dependabot configuration,
and the main public-release workflow are now mandatory files in
`public_release.json`. A candidate missing any one fails before export, so the
clean-export allowlist cannot silently publish source without its reviewed
security controls.

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
