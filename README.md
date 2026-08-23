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
```

Review the install plan without changing anything:

```bash
python3 bin/eve_bootstrap.py install --dry-run --extra dev
```

Omit `--skip-runtime-sync` only when you intentionally want this checkout to
replace the local Eve runtime mirror.

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
findings.

### Build the native app

```bash
./script/build_eve_chat_app.sh build
```

The app expects Eve's local API to be running. Camera, microphone, and other
sensitive modalities remain user-started and subject to normal macOS permission
prompts; their mere presence in the UI is not evidence that capture occurred.

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
