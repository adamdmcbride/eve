# Eve

Eve is a local-first AI counterpart that maintains one coherent identity while
allocating attention across five cognitive modes and acting through governed
capabilities.

> **Project status:** pre-alpha research software. Eve can run real local
> workflows, but installation and migration are still being productized. No
> software test proves subjective consciousness, and Eve must not claim that it
> does.

Eve is an independent personal open-source project. It is not an Eden product
and is not published by or on behalf of an Eden organization.

## Core contextual learning

Eve's normal core now learns action expectations from **matching pre-action
contexts**, with reversible recent evidence rather than a single global action
success rate. Verified outcomes influence the existing action chooser; original
reply context follows delayed feedback; repeated verified procedures consolidate
at the existing quiet-period cadence and lose eligibility on contrary evidence.
No extra model or fly dependency is required. See the
[core contextual-learning contract](docs/architecture/EVE_CORE_CONTEXT_LEARNING_2026_09_13.md)
for tests, evidence limits and activation receipts.

## Reviewed corrections and inquiry evidence

Eve's existing core can retrieve independently reviewed general lessons without
replaying old answers as current facts. Unreviewed fallback narration is no longer
eligible for thought training, including through legacy trainer exports. Measured
predictions can distinguish a negative result from failed execution, but cannot
close a question using an unrelated comparison. The existing free-run executor
now reaches its admitted fly probes. These connections are implemented; the live
thought author still failed the transfer canary. See the
[inquiry/evidence release record](docs/architecture/EVE_INQUIRY_EVIDENCE_LEARNING_2026_09_13.md)
for tests, actual model failures, scope and activation evidence.

## Core process observation

Core health and storage authority are separate. Eve now joins the live core's
kernel lease, process identity, state and heartbeat instead of declaring a
plain-process daemon absent because its native service is unavailable. Inspect
`python3 eve.py daemon status` or `python3 eve.py runtime truth --json` for the
separate operational observation; this does not redirect memory, migrate data
roots, or alter model/scheduler policy. See the
[core ownership contract](docs/architecture/EVE_CORE_RUNNER_OWNERSHIP_2026_09_12.md).

## Autonomous consequence and recovery

Autonomy needs correct credit assignment, not only more activity. A failed
recurrent preflight now leaves existing bounded fallback actions available,
but cannot borrow an old intention or attach new consequences to an old cycle.
The next successful preflight resumes normal recurrence with fresh attribution.

Completion checks, autonomous learning and typed next-query generation share
negative/unknown execution-evidence checks. Failed execution or invalid typed
results cannot become success through an optimistic verification flag or prose.
Matched two-cycle tests verify that failure lowers rather than raises the next
action's learned preference. These are functional controls and tests, not proof
of subjective consciousness. See the
[recurrent kernel contract](docs/architecture/EVE_CONSCIOUS_STATE_KERNEL_2026_07_12.md).

## Fly-brain learning integration

The existing fly organ now has sparse cue competition, temporally decaying
synaptic eligibility, separate measured reward/punishment, reversible local
weight changes, and validated restart checkpoints. Learned cue values reach
the existing body controller and typed Eve percepts, rather than appearing
only in a narrative. This is associative learning, not LLM fine-tuning or a
consciousness result. Two isolated full-connectome cue sets and matched
MuJoCo walking controls verify the mechanism; natural long-term generalization
and improvements to conversation remain separate questions. See the
[brain-wide adoption map and evidence](docs/architecture/EVE_FLY_SYNAPTIC_LEARNING_2026_09_13.md)
for implemented mechanisms, live qualification and remaining circuit work.

## Why Eve exists

Most assistant shells treat every message as an isolated prompt. Eve is an
experiment in building a more continuous local system:

- one outward identity rather than a cast of model personalities;
- durable, inspectable continuity instead of hidden prompt stuffing;
- sparse cognitive routing instead of running every model on every turn;
- bounded tools with permission and verification records;
- explicit uncertainty, correction, and rollback paths;
- native and web interfaces backed by the same local runtime contract.

The goal is useful functional integration, not a theatrical consciousness
claim. See [Eve Core](docs/EVE_CORE.md) for the smallest faithful definition and
[the architecture guide](docs/ARCHITECTURE.md) for the current research and
engineering boundary.

## Shared embodied evidence (fly path live-verified, September 12, 2026)

A pre-action prediction, acknowledged dispatch and measured body consequence
now join in the existing operational database. The restarted fly actor produced
real joined records; the main daemon resumed from its existing source/data root.
Generated narration remains self-output. Concurrent-input measurements remain
**confounded and excluded from learning**; this is not a consciousness result.
See the [episode implementation](eve_embodiment.py) and
[regressions](tests/test_embodied_continuity.py).

The existing fly organ now uses [source-owned input arbitration](eve_drive_arbiter.py):
wall-clock leases, whole-vector replacement per producer, explicit max merging,
restart/reset epochs and command receipts. Body, mind and homeostasis retain
separate contributions. Kernel actor locks prevent duplicate local runners;
source labels are attribution metadata, not authentication or causal proof.

[Python bundle installation](eve_runtime_bundle.py) freezes the existing
first-party inventory, checks syntax/imports, stages an isolated import canary,
and installs with a manifest and recoverable rollback. `python3 eve.py runtime
sync --code-only --check-only` validates without installing; remove `--check-only`
only with code consumers quiesced. Code-only sync copies no memory/config/models
and does **not** restart services. Interrupted installs block new core imports.
A verified 72-file bundle was installed; same-command core/fly restarts were
checked separately. This does not attest a running Chat UI or every non-Python
asset. Existing CLI registration now lives in [eve_commands/parser.py](eve_commands/parser.py)
with the `eve.build_parser()` compatibility entrypoint and frozen-contract tests.
Final focused verification: 242 tests passed. Later readback found the recurring
core daemon absent while a separate forced one-shot diagnostic was active;
continuous core operation still needs reconciliation. The fly actors remained
live. An active diagnostic is not a recurring loop.

## One Eve, five modes

The five logical lanes are attention modes inside one control system:

| Mode | Job | Must not become |
| --- | --- | --- |
| `fast` | Answer the current request directly and efficiently. | A shallow imitation of every other lane. |
| `observer` | Separate current evidence from inference and noise. | A repair engine or action commander. |
| `planner` | Sequence bounded next steps, gates, and verification. | An emotional interpreter or permission bypass. |
| `deep` | Integrate difficult evidence, uncertainty, and tradeoffs. | A bigger task-list generator or overclaiming narrator. |
| `relationship` | Preserve conversational continuity, warmth, and honest boundaries. | A second personality or generic comfort layer. |

Logical lanes do not require five resident processes. The current topology can
map them onto three local `llama.cpp` substrates: `fast` and `relationship`
share one substrate, `observer` and `planner` share one, and `deep` remains
separate. Eve records both the logical lane and the physical substrate so the
UI never presents process count as mind count.

Read [the scheduler contract](docs/EXECUTIVE_SCHEDULER.md) and
[model-lane specifications](docs/model_lanes/README.md) before changing routing.

## Architecture at a glance

```text
Human
  │
  ▼
Conversation surfaces ───── native Eve.app / local web client / CLI
  │
  ▼
Executive scheduler ─────── intent, cognition budget, lane admission
  │
  ├── fast
  ├── observer
  ├── planner              one Eve; sparse attention modes
  ├── deep
  └── relationship
  │
  ▼
Continuity kernel ───────── workspace, evidence, experience, commitments,
  │                         memory, self/world/other models, homeostasis
  ▼
Governed organs ─────────── local actions, OpenClaw, Hermes, Codex handoffs,
                            model supervision, optional research labs
```

Important boundaries:

- **OpenClaw** is an admitted body/action nervous system, not a second mind.
- **Hermes** is proposal-only learning; it cannot directly write canonical
  memory or become a sixth lane.
- **Codex** is a separate builder/operator. Its output is evidence, not Eve's
  identity or memory.
- **Models** provide inference. A model checkpoint is not Eve's durable identity
  and cannot grant itself tools or authority.
- **Actions** are not complete because text says they are. Completion requires
  a matching execution and verification record.

See [the architecture guide](docs/ARCHITECTURE.md) and the
[autonomy policy](docs/operating/AUTONOMY_POLICY.md) for the full boundaries.

## Repository map

```text
eve.py                  Compatibility facade and current composition root
eve_*.py                Extracted runtime, continuity, governance, and organ modules
bin/                    Operator, bootstrap, audit, and bounded lab tools
prompts/                Generic behavior contracts; local user context stays out of Git
mac/                    Native macOS application source
web/                    Local web application source
go/eve-nervous/         Narrow nervous-system bridge
rust/eve-kernel/        Experimental typed kernel work
docs/                   Architecture, operating contracts, and roadmaps
tests/                  Hermetic contracts plus explicitly bounded integration tests
openclaw/                Eve-owned OpenClaw profile, hooks, and skills—not runtime state
```

`eve.py` is still large. The migration plan is to turn it into a thin
compatibility facade through characterized, incremental extractions—not a
big-bang rewrite. See the [open-source overhaul roadmap](docs/roadmaps/OPEN_SOURCE_OVERHAUL_2026_08_23.md).

## Development setup

### Requirements

- Python 3.12–3.14
- Git
- [`uv`](https://docs.astral.sh/uv/) for the locked environment
- macOS and Xcode command-line tools for the native app
- `llama.cpp` plus separately obtained, license-compatible model files for the
  full local inference runtime

Eve never downloads a model, installs a daemon, or enables a hosted provider as
a side effect of the source bootstrap.

### Check and install the source environment

```bash
python3 bin/eve_bootstrap.py check
python3 bin/eve_bootstrap.py install --extra dev --skip-runtime-sync
.venv/bin/eve doctor --quick
```

Review the install plan without changing anything:

```bash
python3 bin/eve_bootstrap.py install --dry-run --extra dev
```

Omit `--skip-runtime-sync` only when you intentionally want this checkout to
replace the local Eve runtime mirror.

The locked install adds `.venv/bin/eve` (or `.venv\\Scripts\\eve.cmd` on
Windows). It forwards to the current compatibility entrypoint without embedding
the checkout's absolute path, so the source folder can be moved or renamed.
This is an honest interim source command, not yet the standalone package or
signed installer promised by the release roadmap. It does not start a daemon,
download a model, or enable an external provider.

`install --json` emits one schema-versioned result only after the plan is
blocked, reviewed as a dry run, completed, or stopped. Child command output is
isolated from that JSON stream. On failure the result identifies the exact
step, how many earlier steps completed, whether rollback occurred, and at most
the final 8 KiB of command output; later steps are never run. The text mode
reports the same boundary without a Python traceback. Earlier successful steps
are intentionally not guessed away or silently rolled back, so a partial
install remains visible and retryable.

### Run the focused public checks

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run python -m unittest \
  tests.test_public_release_audit \
  tests.test_eve_bootstrap \
  tests.test_dependency_license_audit \
  tests.test_public_portability

uv run python bin/eve_dependency_license_audit.py --json

python3 bin/eve_public_release_audit.py \
  --root . \
  --candidate-only \
  --include-untracked \
  --full
```

The release tool is read-only unless `--write-manifest` or `--export` is
explicitly supplied. Export is fail-closed: it refuses private state, detected
credentials, owner-specific defaults, unsafe dependency declarations,
symlinks, oversized files, non-empty destinations, and candidates with blocking
findings. Export is staged and exposed only after a second audit and exact
schema-2 manifest verification; use `--verify-manifest ... --exact-tree` to
check an independently obtained tree or extracted archive.

### Inspect performance evidence

```bash
.venv/bin/eve perf summary --minutes 240
.venv/bin/eve perf summary --category model_call --failures
```

Performance summaries report measured observations separately from samples a
producer explicitly marked inconclusive or invalid. Eve never reclassifies a
failure by matching convenient words in its error text, and malformed timing
values cannot enter latency percentiles. These summaries are evidence, not yet
release performance budgets.

### Build the native app

```bash
./script/build_eve_chat_app.sh build
```

The app expects Eve's local API to be running. Camera, microphone, and other
sensitive modalities remain user-started and subject to normal macOS permission
prompts; their mere presence in the UI is not evidence that capture occurred.
Private sensory-session authorization and feature-only ingestion are isolated
in `eve_sensory_sessions.py`. The composed service owns token hashing, expiry,
rate and event budgets, restart rehydration, and durable observation writes;
raw audio, images, screen content, transcripts, and keystrokes remain outside
the session record. `EveRuntimeService` keeps the HTTP boundary and delegates
through its compatible methods. This separation does not turn sensors on or
grant observation authority without an explicit operator-confirmed session.
State-changing local HTTP requests must use JSON. Eve rejects cross-site Fetch
Metadata and foreign browser Origins before dispatch; this is browser-CSRF
resistance, not authentication against another process running as the user.
The runtime and app proxy also require one bounded `Content-Length`, reject
unsupported transfer encoding and incomplete bodies, and close ambiguous
persistent connections instead of accepting a valid-looking JSON prefix.
Runtime query strings are capped at 8 KiB and 32 fields. Consumed values must
be singular; list limits, lookback windows, stream cadence, identifiers, and
Booleans use explicit bounds and vocabularies rather than permissive coercion.
Eve.app applies the same syntax/resource budget before proxying a query, and
both HTTP surfaces close a rejected POST boundary instead of leaving its body
on keep-alive.
Consumed request headers are duplicate-aware and independently bounded:
Origin is at most 512 ASCII characters, Sec-Fetch-Site 32, and Content-Type
256. OpenWebUI header correlation IDs must be printable ASCII and at most 160
characters; JSON transport IDs are printable and bounded before persistence,
AG-UI event construction, or proxy forwarding. Direct OpenAI-compatible
requests accept at most 128 messages. These are ambiguity and resource limits,
not local-process authentication.
Decoded conversation mutations also use one shared typed JSON-field contract.
Runtime message bodies are capped at 32,000 characters, subjects and resource
IDs at 512, client-request IDs at 160, attachments at eight per message, and
capture tags at 32 items of 64 characters each. Stream/initiation flags must be
real JSON Booleans. Eve.app's narrower personal-reply proxy accepts an 8,000-
character body and 160-character message/client IDs, rejecting overages rather
than silently truncating them. Length is checked before trimming and hidden
controls are rejected; ordinary message line breaks remain supported.
CopilotKit/AG-UI translation lives in `eve_agui.py`, not in the HTTP handler.
Its fallback prompt and each message's typed visible content are capped at
8,000 characters, its model selector at 80, and conflicting thread/run/client
ID aliases fail rather than silently winning by order. Message roles, plain
text, and text content-parts retain their declared JSON types and reject hidden
controls before compatibility normalization. Generated activity/message IDs
remain at most 160 characters with a deterministic hash suffix when a valid
source ID needs compaction. The adapter still enters Eve through the same local
OpenAI-compatible scheduler; it is not another lane, identity, memory writer,
or action authority.
Eve Chat's durable follow-up and external transport interpretation now live in
`eve_chat_protocol.py`. The module only recognizes explicit deferred intent,
derives a bounded due time and supported check, normalizes external chat IDs,
admits explicit synthetic-evaluator provenance, and formats durable/result
projections. `eve_chat_followups.py` composes those decisions into the durable
queue, one-worker admission, leases, restart recovery, verified action result,
commitment/replay joins, and idempotent same-thread delivery. It cannot route an
ordinary reply, select a lane, or expand the fixed admitted action set.
`EveRuntimeService` retains its shared mutation/cache boundary, compatible
methods, and HTTP composition. The old `eve_web` protocol names are
compatibility re-exports, not a second implementation. See the
[durable follow-up boundary](docs/architecture/EVE_CHAT_FOLLOWUP_BOUNDARY_2026_08_24.md).
Request targets must use HTTP origin form rather than an absolute proxy URL;
the full target and path are bounded, percent encoding must be valid UTF-8, and
control-bearing paths fail before dispatch. Dynamic model, message, thread,
proposal, and follow-up routes match exactly one bounded opaque segment—extra
slash-delimited segments never partially dispatch. Eve.app canonicalizes that
segment before forwarding, and web/native clients encode IDs as one segment.
Every admitted POST consumes its exact JSON body, including no-argument action
routes; an unknown or invalid POST closes instead of leaving body bytes on a
persistent connection.
Their shared loopback server admits at most 32 active request threads, uses a
finite listen backlog, and applies a 30-second client-I/O inactivity timeout.
This limits a stalled local client's resource use; it does not make the local
API safe to expose to an untrusted network.
Installer, bootstrap, and update artifacts never derive their embedded
callback endpoint from the browser's `Host` header. For a cross-machine setup,
start `bin/eve_server.py` with `--advertised-host <dns-or-ipv4>` or set
`EVE_ADVERTISED_HOST`; otherwise Eve uses the safe DNS/IPv4 bind host or
`localhost`. Legacy query copies of the host/API port must exactly match that
server-owned endpoint; requests cannot choose a different artifact authority.
Their byte construction and install-page presentation now live in
`eve_install_artifacts.py`; `eve_web.py` only routes and re-exports the old names
for compatibility. IPv6 literals are not yet supported in generated platform
scripts. The legacy optional Ollama branch is preserved for compatibility in
this source extraction even though Eve's documented default runtime is
`llama.cpp`; replacing it requires a separate clean-machine installer contract.
Local responses are no-store/no-sniff/no-referrer, static documents carry a
strict local CSP/frame/device policy, and request logs omit query strings and
raw request lines. HTTP responses identify Eve without exposing Python's host
version.
Expected client errors retain bounded actionable detail. Unexpected runtime,
proxy, stream, and AG-UI failures instead return a generic message plus an
opaque error ID; Eve records only that ID, the surface and operation, and the
exception type. Exception text, tracebacks, request content, and upstream 5xx
bodies do not cross the HTTP or log boundary. The ID supports local
correlation—it is not proof that a request was recovered or completed.

The live conversation timeline uses the versioned `eve_app_snapshot.v1` local
read contract plus a small presence projection. It preserves the ten-second
visible and 60-second hidden requested cadence while avoiding per-ledger polling
and a recurring status timer. See the
[Eve.app refresh contract](docs/architecture/EVE_APP_REFRESH_CONTRACT_2026_08_23.md)
for failure behavior, deployment coupling, and the distinction between reduced
request count and measured energy performance.

The same health endpoint reports ready only when the app surface and Eve's
local conversation backend are both reachable. Startup ignores invalid or
reused PID-file values unless the process is verified as Eve's app server; this
prevents a stale runtime hint from signalling an unrelated process.
The Swift shell starts that verified launcher executable directly and reports
its real exit status; it does not build a shell command from the launch path or
mistake a successfully backgrounded wrapper for a healthy Eve backend.
Native self-healing health checks run less often when Eve is in the background
and fire immediately when the app returns to the foreground; two consecutive
failures are still required before relaunch, with a two-second active retry
after the first failure.
Recent successful local app traffic can satisfy the native health check for up
to 12 seconds, avoiding a duplicate model-list probe. Failures are cached for
only one second, and no conversation or response content enters this cache.
Launcher stdout and stderr are written directly to a newly truncated,
owner-only local log rather than buffered in an unread pipe while Swift waits.
The app reads at most the final 32 KiB for failure detail, avoiding pipe
backpressure and unbounded diagnostic ingestion; the installed app retains its
previous behavior until the pending atomic rebuild.
The app proxy also bounds non-stream backend reads: 8 MiB for admitted API
responses, 2 MiB for compact presence input, and 64 KiB for backend error
detail. It validates declared and actual body size before committing response
headers, rejects incomplete bodies, and keeps live chat replies streaming in
64 KiB chunks. These limits are source contracts pending the same atomic app
deployment.

Monitor-facing record conversion and local CPU/memory/disk observation live in
`eve_monitor_projection.py`, not the HTTP handler. Observed process arguments
are used only for local classification and are never returned; the compatible
`command` field is a bounded display label. Malformed and non-finite resource
numbers fall back to finite values rather than producing invalid JSON. Missing
resource data remains unavailable evidence, not a healthy-system claim.
The same module now assembles both compact and full dashboard payloads. Compact
refreshes deliberately omit source-truth, self/world/relationship-model, and
reply-replay readers; the existing service still supplies cached status,
activity, and conversation-spine inputs and owns HTTP/live-stream behavior.

Model-health, model/system activity, and latest-state API read models are
assembled in `eve_runtime_projection.py`. The module reads existing local
evidence and delegates low-level resource shaping to the monitor projection; it
does not call a model, select a lane, write state, control the daemon, or own an
HTTP route. `EveRuntimeService` still owns the three TTL caches, refresh locks,
invalidation, and endpoint composition, preserving existing payloads and
refresh behavior while making the read-model boundary independently testable.

### Run optional local capability canaries

```bash
python3 eve.py self-repair isolation --json
python3 eve.py infra mcp-2026 --json
python3 eve.py infra otel-genai --runtime --limit 200 --json
```

These are bounded evidence paths, not new resident lanes or authority grants.
The self-repair canary requires Apple container and executes only when
`--execute` is supplied. MCP discovery is read-only and calls no tool. The OTel
projection is content-free, keeps Eve's SQLite trace store authoritative, and
contacts no collector.

## Data and privacy

The following are local runtime data and must never be committed or included in
a source release:

- conversations, imported transcripts, user profiles, and relationship memory;
- model weights, embeddings, training data, and private evaluation holdouts;
- `.eve/`, `.openclaw/`, logs, databases, generated wiki/dream material, and
  runtime mirrors;
- credentials, provider tokens, pairing state, account identifiers, and device
  captures;
- coordination ledgers and private development history.

The public repository is produced as a new clean export. The private working
history is never pushed or mirrored into it. Review [the security policy](SECURITY.md)
and [third-party notices](THIRD_PARTY_NOTICES.md) before enabling optional
organs or sharing artifacts.

Public pull requests and pushes run release, portability, native-contract,
secret-history, dependency-review, and Python CodeQL gates. External actions
are pinned to immutable commits and checkout credentials are not persisted.
CodeQL's isolated analysis job has only repository read access plus the narrow
`security-events: write` permission required to upload findings; it does not
install dependencies or execute Eve's source.

## Dependency and model policy

Eve's original source is Apache-2.0. Public install groups are kept permissive.
`mlx-embeddings` and `arize-phoenix` are intentionally not installed by project
extras because their reviewed licenses fall outside that permissive policy;
optional integrations may detect separately installed copies.

Models and external runtimes are not distributed with Eve. Their licenses,
acceptable-use terms, checksums, memory requirements, and data boundaries must
be reviewed independently.

The default inference provider is local `llama.cpp`. OpenAI and other hosted
providers are never silent fallbacks: using one requires explicit permission
for a named purpose and data boundary. Missing credentials mean that capability
is unavailable; they do not make the local runtime unhealthy.

## Recurrent-loop repair — 2026-09-13

The existing core now has shared author/critic evidence, a single bounded
post-critic revision, same-checkpoint structured action choices, executable fly
probe contracts, repeated-fault inhibition and job-specific cognition budgets.
Typed inquiry attempts survive reload with source/cycle/execution lineage.
The live chooser improved its JSON contract, but the tested fast thought author
still fell back on both trials; this is not a claim of consciousness or complete
behavioral qualification. See the [implementation and live evidence](docs/architecture/EVE_RECURRENT_LOOP_REPAIR_2026_09_13.md).

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a change. In particular:

1. preserve the one-Eve/five-mode architecture;
2. add characterization tests before extracting behavior from `eve.py`;
3. keep authority, evidence, and memory boundaries explicit;
4. do not submit private data or source you cannot legally contribute;
5. include the narrow verification and rollback path for behavioral changes.

Security issues should use private vulnerability reporting as described in
[SECURITY.md](SECURITY.md), not a public issue.

## License

Eve's original source is licensed under the
[Apache License 2.0](LICENSE). Third-party components and optional external
integrations retain their own licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
