# Eve Route Contracts

Status: canonical
Last reviewed: 2026-06-13
Current authority: yes
Supersedes: none
Superseded by: none

Eve route contracts are the declarative boundary between a user turn and Eve's executive scheduler.

They exist so Eve does not fix conversation failures by adding scattered phrase branches. A route contract names the signal, budget, lane shape, evidence policy, response/action boundary, and replay expectations for a class of turns.

## Contract Rule

Eve owns routing doctrine.

Hermes may propose new route examples, failure patterns, skill patches, or eval cases from traces. OpenClaw may carry channel/tool/action evidence after Eve chooses an admitted action path. Neither organ owns the route table, Eve's identity, canonical memory, or final reply authority.

## Files

- `signals.json`: named signal vocabulary. This is the reviewable catalog of what Eve detected before deciding what to do.
- `route_contracts.json`: active public conversation route contracts used by CLI chat and Eve Chat.
- `anti_contracts.json`: explicit routing failures Eve should keep catching.
- `eval_cases.jsonl`: public replay bank for deterministic routing-quality checks.

## Runtime Surfaces

```bash
python3 eve.py router contracts --full
python3 eve.py router replay --full
python3 eve.py router replay --record --full
python3 eve.py router replay --json
```

`--record` writes `.eve/route_contract_replays/latest.json`, a timestamped replay artifact, an `EvalResultEvent`, and an evidence-ledger record. Passing runs stay as evidence only. Failed runs also create a pending uncertainty record so route drift becomes visible in Eve's review surfaces instead of hiding in terminal output.

## How To Add A Route

1. Add or reuse a named signal in `signals.json`.
2. Add one route contract in `route_contracts.json`.
3. Choose the response mode:
   - `static`: Eve can answer immediately from the route contract. Use this only for low-risk reflex turns such as greetings, friendly check-ins, and leaked-phrase explanations.
   - `runtime_handler`: the contract classifies the turn, but Eve must delegate to an existing runtime handler, action path, or normal model route with the named evidence policy. Use this for status, diagnostic, action, capability, and humanity/identity routes.
4. Add at least one public replay case in `eval_cases.jsonl`, including `expected_static_direct_reply` so static reflex routes cannot silently capture live/action routes.
5. Connect any high-severity anti-contract in `anti_contracts.json` to at least one replay case through `covers_anti_contracts`.
6. Run `python3 eve.py router replay --record --full` so the public replay result is captured as durable evidence.
7. Update `docs/evals/routing_quality.md` if the route changes scheduler expectations.
8. If the route came from Hermes or OpenClaw evidence, ingest that evidence through Eve governance; do not let the organ edit routing authority directly.

## Scope

These contracts are for deterministic user-turn classification and for a small number of low-risk static replies. They are not a substitute for:

- live service-health checks
- action execution and verification
- OpenClaw channel-send permission gates
- Hermes skill/capability admission
- model/lane promotion evidence
- hidden eval probes or private rubrics

## External Patterns Checked

The shape intentionally borrows the durable parts of current agent UI/runtime patterns without importing their authority model:

- [LangGraph](https://docs.langchain.com/oss/python/langgraph/graph-api) treats routing as explicit graph control flow through conditional edges or commands; Eve keeps the same idea but with smaller JSON contracts before any heavyweight graph runtime.
- [Pydantic AI](https://pydantic.dev/docs/ai/core-concepts/agent/) and [Pydantic Evals](https://pydantic.dev/docs/ai/evals/evals/) emphasize structured outputs and code-first eval cases; Eve uses app-side validation plus public replay cases so route correctness is tested, not trusted.
- [Open WebUI Functions/Filters](https://docs.openwebui.com/features/extensibility/plugin/functions/) show that UI adapters can intercept input/output before model calls; Eve uses that boundary only as a surface adapter while keeping route ownership in Eve Core.
- [OpenClaw tools/plugins/hooks](https://docs.openclaw.ai/tools/index) give a typed body/action bus; Eve invokes that bus only after route contracts classify a turn as needing body/action evidence.
