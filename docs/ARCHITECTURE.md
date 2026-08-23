# Eve architecture

Status: canonical  
Last reviewed: 2026-08-23  
Current authority: public architecture overview  
Supersedes: none  
Superseded by: none

Eve is one local control system that allocates cognition across five logical
attention modes. Models, tools, applications, and sidecars are replaceable
substrates around a durable Eve-owned state; none of them independently becomes
Eve's identity or authority.

## System shape

```text
User
  │
  ▼
Native app / local web app / CLI
  │
  ▼
Conversation boundary
  │  validates the turn, thread, attachments, and current intent
  ▼
Executive scheduler
  │  selects a cognition budget and only the modes the turn warrants
  ├── fast
  ├── observer
  ├── planner
  ├── deep
  └── relationship
  │
  ▼
Continuity kernel
  │  workspace, evidence, experience, commitments, memory,
  │  self/world/other models, homeostasis, and current focus
  ▼
Governed action boundary
  │  permission → execution → verification → durable consequence
  ▼
Local system and admitted organs
```

The outward contract is one conversation with Eve. Lane packets may be recorded
for inspection, but they are not five personalities speaking over one another.

## Logical modes and physical substrates

The five modes are behavior contracts, not a required process count. A normal
local topology can run three resident `llama.cpp` substrates:

- `fast` and `relationship` share a low-latency substrate;
- `observer` and `planner` share a structured-reasoning substrate;
- `deep` uses a separate integration substrate.

This mapping is configurable. Every inference record should preserve both the
logical mode and the physical model endpoint so monitoring never mistakes
process count for cognitive identity. See [the lane specifications](model_lanes/README.md).

## Cognition budgets

The scheduler chooses a budget before it chooses modes:

- **reflex** — static or deterministic handling for a narrow safe turn;
- **operational** — direct answer plus current local context;
- **analytical** — structured observation or planning where warranted;
- **strategic** — multi-mode work with one deep integration pass;
- **frontier** — exceptional, explicitly gated research or external capability.

Simple chat should stay simple. A greeting does not justify five model calls.
A live diagnostic does require fresh evidence. A multi-mode turn should produce
one integrated answer rather than a transcript of an internal panel. The full
contract is in [the executive scheduler](EXECUTIVE_SCHEDULER.md).

## Durable state

Eve's durable state is local and inspectable. The source modules separate these
responsibilities even while `eve.py` remains the compatibility facade:

| Concern | Owned by |
| --- | --- |
| Operational storage and read-only health | `eve_db.py`, `eve_store.py` |
| Evidence and provenance | `eve_evidence.py` |
| Experience and continuity | `eve_experience.py`, `eve_consciousness.py` |
| Commitments and unfinished work | `eve_commitments.py` |
| Permissions and governed proposals | `eve_governance.py` |
| Model topology and resource policy | `eve_model_topology.py`, `eve_model_governor.py` |
| Platform/runtime paths | `eve_platform.py`, `eve_profile.py` |
| Conversation and app APIs | `eve_web.py`, `bin/eve_app_server.py` |

Runtime data belongs outside the public source tree. A source checkout may be
synced into a local runtime mirror, but source, runtime state, and public export
remain distinct artifacts.

## Evidence and action lifecycle

An action is not complete because a model says it is. The normal lifecycle is:

1. classify the user's request and the required authority;
2. select an admitted capability;
3. obtain permission when the action crosses a configured boundary;
4. execute through the owning adapter;
5. verify the observable consequence;
6. record the result and any remaining uncertainty;
7. report only what that evidence supports.

Failed, bypassed, partial, and unverified outcomes remain distinct. The UI may
summarize them, but must not erase those distinctions.

## Organ boundaries

- **OpenClaw** is an action and channel nervous system. It can execute admitted
  capabilities and return evidence; it does not own identity or canonical
  memory.
- **Hermes** is a proposal-only learning organ. Its outputs enter governance
  review and do not directly rewrite durable knowledge.
- **Codex** is an external builder/operator. A patch or report is evidence until
  it is reviewed, tested, and deliberately adopted.
- **Model servers** provide inference. They do not grant themselves tools,
  permissions, persistence, or authority.
- **Research labs** are optional and fail closed. Passing a canary does not make
  a component part of the live runtime.

## Applications

The native macOS application and local web client use the same local API and
thread model. The macOS app can use WebKit for the conversation surface while
still providing native windowing, menus, permissions, lifecycle, and recovery.
The monitor is an operator surface, not a second Eve process.

Local services use a configurable namespace. Fresh installs default to
`local.eve`; existing installs may retain an older namespace until their
generated service definitions are migrated. No person's name or home directory
is part of the source contract.

## Security and privacy boundary

Eve is local-first, not magically private. Any enabled external provider,
channel, browser, connector, or model host creates a separate data boundary that
must be reviewed. The public repository distributes no model weights, personal
memory, credentials, captures, or private evaluation fixtures.

Camera, microphone, filesystem, network, and account access remain explicit,
bounded capabilities. A UI indicator is not proof that access occurred; runtime
evidence must identify the owning process, request, and result.

## Research boundary

Eve can be evaluated for functional integration: continuity, source monitoring,
error correction, self/world separation, prospective memory, bounded autonomy,
and causal response to internal state. Those measurements do not establish
subjective experience. Public claims must preserve that distinction.

## Change discipline

Behavioral changes should be characterized before extraction or redesign:

1. add or update the narrow contract test;
2. make the smallest source change;
3. run the focused test and the affected routing/evaluation suite;
4. verify source/runtime parity when deploying locally;
5. retain a rollback path;
6. keep private evidence out of commits and issue reports.
