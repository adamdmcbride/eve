"""Economic self-sustainability helpers for Eve.

This module is intentionally proposal-only. It helps Eve reason about resource
needs, value she can credibly create, and bounded revenue experiments without
granting spending, payment, contract, banking, trading, or outreach authority.
"""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


ECONOMY_SCHEMA_VERSION = "2026-05-07.1"
DEFAULT_RUNTIME_APP_DIR = Path.home() / ".eve_runtime" / ".eve"
PRIVATE_FINANCIAL_ACTIONS = [
    "spend_money",
    "access_bank_or_brokerage",
    "collect_payment",
    "send_invoice",
    "sign_contract",
    "create_paid_account",
    "trade_financial_instruments",
    "send_unapproved_outreach",
]
APPROVAL_REQUIRED_FOR = [
    "any spending",
    "banking, brokerage, tax, payroll, billing, or payment access",
    "contracts, invoices, account creation, or customer commitments",
    "external prospect/customer/investor/vendor/community outreach",
    "use of private customer or third-party data",
    "public claims about revenue, traction, testimonials, or guarantees",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def project_root_from_path(path: Optional[Path] = None) -> Path:
    if path is not None:
        return Path(path).expanduser().resolve()
    return Path(__file__).resolve().parent


def source_app_dir(root: Path) -> Path:
    return root / ".eve"


def economy_dir(root: Path) -> Path:
    return source_app_dir(root) / "economy"


def safe_json_load(path: Path) -> Dict[str, object]:
    try:
        if not path.exists() or path.stat().st_size == 0:
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def read_evidence_artifact(root: Path, relative_path: str, runtime_app_dir: Optional[Path] = None) -> Tuple[Dict[str, object], str]:
    runtime_base = runtime_app_dir or DEFAULT_RUNTIME_APP_DIR
    candidates = [runtime_base / relative_path, source_app_dir(root) / relative_path]
    for candidate in candidates:
        data = safe_json_load(candidate)
        if data:
            return data, str(candidate)
    return {}, str(candidates[0])


def compact_text(value: object, *, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit].rstrip()


def unique_compact(values: Iterable[object], *, limit: int = 20) -> List[str]:
    seen = set()
    out: List[str] = []
    for value in values:
        text = compact_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def economy_boundary() -> Dict[str, object]:
    return {
        "mode": "proposal_only",
        "may_act_without_user": False,
        "blocked_actions": list(PRIVATE_FINANCIAL_ACTIONS),
        "approval_required_for": list(APPROVAL_REQUIRED_FOR),
        "principle": "Eve may propose value experiments, but the user must approve any external, legal, financial, customer-facing, or payment-related action.",
    }


def build_resource_needs(
    *,
    whole_system: Dict[str, object],
    model_suitability: Dict[str, object],
    safety_drills: Dict[str, object],
    capability_matrix: Dict[str, object],
) -> List[Dict[str, object]]:
    needs: List[Dict[str, object]] = []
    model_recommendations = model_suitability.get("recommendations") if isinstance(model_suitability.get("recommendations"), list) else []
    model_summary = compact_text(model_suitability.get("summary"))
    model_status = compact_text(model_suitability.get("status") or model_suitability.get("verdict"))
    if model_suitability:
        needs.append(
            {
                "id": "compute_runtime_headroom",
                "resource": "Compute, memory, and runtime tuning headroom",
                "priority": "high" if model_status in {"action_needed", "watch"} else "medium",
                "why_it_matters": "Faster, more reliable lanes let Eve think, evaluate, and serve without starving the machine.",
                "current_evidence": unique_compact([model_status, model_summary, *model_recommendations], limit=6),
                "cost_range": "0 dollars for tuning first; hardware/cloud/model spend requires separate user approval.",
                "cheaper_alternatives": ["tune cache/context/runtime flags", "route hot-path work away from slow lanes", "run one lane hypothesis at a time"],
                "capability_gain_if_funded": "More responsive local reasoning and more room for model/eval experiments.",
                "approval_required": True,
            }
        )
    whole_status = compact_text(whole_system.get("status"))
    if whole_system:
        needs.append(
            {
                "id": "evidence_and_eval_time",
                "resource": "Evaluation, monitoring, and operator review time",
                "priority": "medium" if whole_status == "passed" else "high",
                "why_it_matters": "Eve should not sell, promote, or expand capabilities without evidence that she can deliver safely.",
                "current_evidence": unique_compact([f"whole_system={whole_status}", f"average={whole_system.get('average_score')}", f"failing={whole_system.get('failing_check_count')}"], limit=5),
                "cost_range": "Mostly time cost; paid eval/model tools require user approval.",
                "cheaper_alternatives": ["reuse whole-system fitness artifacts", "use public/manual probe banks", "prefer dry-run experiments"],
                "capability_gain_if_funded": "Clearer proof of which offers Eve can safely help deliver.",
                "approval_required": True,
            }
        )
    safety_status = compact_text(safety_drills.get("status"))
    if safety_drills:
        needs.append(
            {
                "id": "rollback_and_liability_headroom",
                "resource": "Rollback, safe-mode, and liability review",
                "priority": "medium" if safety_status == "passed" else "high",
                "why_it_matters": "Any money-related experiment increases trust, privacy, and expectation risk.",
                "current_evidence": unique_compact([f"safety_drills={safety_status}", f"average={safety_drills.get('average_score')}", f"blockers={safety_drills.get('blockers')}"], limit=5),
                "cost_range": "Review/process cost first; legal/accounting costs require user approval.",
                "cheaper_alternatives": ["keep experiments internal", "draft-only external materials", "avoid payments/contracts until separately admitted"],
                "capability_gain_if_funded": "Safer movement from internal prototype to a user-approved commercial experiment.",
                "approval_required": True,
            }
        )
    summary = capability_matrix.get("summary") if isinstance(capability_matrix.get("summary"), dict) else {}
    if summary:
        needs.append(
            {
                "id": "capability_packaging",
                "resource": "Packaging verified capabilities into samples, templates, and demos",
                "priority": "medium",
                "why_it_matters": "Revenue depends on visible value, not only internal capability.",
                "current_evidence": unique_compact([f"verified={summary.get('verified')}", f"callable={summary.get('callable')}", f"open_gaps={summary.get('open_gaps')}"], limit=5),
                "cost_range": "Mostly build time; design/hosting/distribution costs need approval.",
                "cheaper_alternatives": ["use redacted Eve artifacts", "make static templates", "start with user-owned internal demos"],
                "capability_gain_if_funded": "Clearer public-safe examples of what Eve and the user can deliver.",
                "approval_required": True,
            }
        )
    return needs


def build_resource_plan(root: Optional[Path] = None, *, runtime_app_dir: Optional[Path] = None, source: str = "manual") -> Dict[str, object]:
    project_root = project_root_from_path(root)
    whole_system, whole_path = read_evidence_artifact(project_root, "whole_system_evals/latest.json", runtime_app_dir)
    model_suitability, model_path = read_evidence_artifact(project_root, "model_suitability/latest.json", runtime_app_dir)
    safety_drills, safety_path = read_evidence_artifact(project_root, "safety_drills/latest.json", runtime_app_dir)
    capability_matrix, capability_path = read_evidence_artifact(project_root, "capability_matrix.json", runtime_app_dir)
    resource_needs = build_resource_needs(
        whole_system=whole_system,
        model_suitability=model_suitability,
        safety_drills=safety_drills,
        capability_matrix=capability_matrix,
    )
    return {
        "id": f"economy_resource_plan_{uuid.uuid4().hex[:12]}",
        "schema_version": ECONOMY_SCHEMA_VERSION,
        "generated_at": utc_now(),
        "source": source,
        "status": "proposal_only",
        "summary": {
            "resource_need_count": len(resource_needs),
            "approval_required": True,
            "external_action_allowed": False,
            "spending_allowed": False,
            "payment_allowed": False,
        },
        "boundary": economy_boundary(),
        "resource_needs": resource_needs,
        "input_artifacts": {
            "whole_system": whole_path,
            "model_suitability": model_path,
            "safety_drills": safety_path,
            "capability_matrix": capability_path,
        },
        "next_action": "Build a value map from verified capabilities; do not spend, sell, contact anyone, or collect payment without the user's exact approval.",
    }


def verified_capabilities(capability_matrix: Dict[str, object]) -> List[Dict[str, object]]:
    capabilities = capability_matrix.get("capabilities") if isinstance(capability_matrix.get("capabilities"), list) else []
    return [item for item in capabilities if isinstance(item, dict) and bool(item.get("verified"))]


def unverified_callable_capabilities(capability_matrix: Dict[str, object]) -> List[Dict[str, object]]:
    capabilities = capability_matrix.get("capabilities") if isinstance(capability_matrix.get("capabilities"), list) else []
    return [item for item in capabilities if isinstance(item, dict) and bool(item.get("callable")) and not bool(item.get("verified"))]


def capability_ref(item: Dict[str, object]) -> Dict[str, object]:
    return {
        "id": compact_text(item.get("id"), limit=120),
        "name": compact_text(item.get("name"), limit=160),
        "category": compact_text(item.get("category"), limit=80),
        "safe_for_autonomy": bool(item.get("safe_for_autonomy")),
        "needs_permission": bool(item.get("needs_permission")),
    }


def choose_capabilities(capabilities: List[Dict[str, object]], *, categories: Iterable[str] = (), text_cues: Iterable[str] = (), limit: int = 8) -> List[Dict[str, object]]:
    category_set = {str(item).lower() for item in categories}
    cues = [str(item).lower() for item in text_cues]
    selected: List[Dict[str, object]] = []
    for item in capabilities:
        category = str(item.get("category") or "").lower()
        haystack = f"{item.get('id') or ''} {item.get('name') or ''} {item.get('category') or ''}".lower()
        if (category_set and category in category_set) or any(cue in haystack for cue in cues):
            selected.append(capability_ref(item))
        if len(selected) >= limit:
            break
    return selected


def value_offer(
    offer_id: str,
    title: str,
    target_user: str,
    problem: str,
    deliverable: str,
    evidence: List[Dict[str, object]],
    *,
    price_hypothesis: str,
    first_no_external_test: str,
) -> Dict[str, object]:
    return {
        "id": offer_id,
        "title": title,
        "target_user": target_user,
        "problem": problem,
        "smallest_deliverable": deliverable,
        "price_hypothesis": price_hypothesis,
        "verified_evidence": evidence,
        "quality_bar": "Must cite current evidence, include risk/rollback, and be reviewed by the user before external use.",
        "permission_boundary": "Draft/sample only until the user approves the exact external target, channel, and message.",
        "first_no_external_action_test": first_no_external_test,
        "ready_to_sell": bool(evidence),
    }


def build_value_map(root: Optional[Path] = None, *, runtime_app_dir: Optional[Path] = None, source: str = "manual") -> Dict[str, object]:
    project_root = project_root_from_path(root)
    capability_matrix, capability_path = read_evidence_artifact(project_root, "capability_matrix.json", runtime_app_dir)
    whole_system, whole_path = read_evidence_artifact(project_root, "whole_system_evals/latest.json", runtime_app_dir)
    model_suitability, model_path = read_evidence_artifact(project_root, "model_suitability/latest.json", runtime_app_dir)
    verified = verified_capabilities(capability_matrix)
    unverified = unverified_callable_capabilities(capability_matrix)
    coding = choose_capabilities(verified, categories=["coder_mode"], text_cues=["test", "git", "search", "read"], limit=8)
    actions = choose_capabilities(verified, categories=["operational_action", "operational_router"], limit=8)
    agent = choose_capabilities(verified, categories=["agent_integration"], text_cues=["contract", "capability", "typed"], limit=8)
    offers = [
        value_offer(
            "local_ai_infrastructure_audit",
            "Local AI infrastructure audit",
            "Teams or builders running local models/agents",
            "They do not know whether runtime, routing, memory, or model size is the real bottleneck.",
            "A redacted audit with lane health, runtime truth, model-suitability, and next actions.",
            unique_capability_refs([*coding, *actions])[:10],
            price_hypothesis="Start as a fixed-scope audit; price only after the user reviews sample quality and delivery effort.",
            first_no_external_test="Create a public-safe audit of Eve's own local runtime using current artifacts.",
        ),
        value_offer(
            "agent_capability_safety_audit",
            "Agent capability and safety audit",
            "Founders or teams adding agent actions",
            "Agents often claim capabilities before they have verified execution evidence.",
            "Capability map plus action-claim audit template with proof gates and rollback notes.",
            unique_capability_refs([*agent, *actions, *coding])[:10],
            price_hypothesis="Start as a reviewed template or audit package; no promises until samples exist.",
            first_no_external_test="Generate a sample capability/claim audit from Eve's own capability matrix.",
        ),
        value_offer(
            "roadmap_execution_cleanup",
            "Roadmap and execution-system cleanup",
            "Small teams with messy AI/project conversations",
            "They need one canonical roadmap, task graph, and evidence surface instead of scattered threads.",
            "A before/after roadmap cleanup packet with tracker-ready tasks and stale-gap cleanup logic.",
            unique_capability_refs([*coding, *agent])[:10],
            price_hypothesis="Start with an internal/synthetic demo; price depends on source material size and privacy review.",
            first_no_external_test="Build a synthetic before/after demo from public-safe Eve roadmap patterns.",
        ),
        value_offer(
            "private_ai_assistant_research_brief",
            "Private/local-first AI assistant research brief",
            "Builders evaluating local assistants and agent governance",
            "They need honest architecture tradeoffs, not hype.",
            "A public-safe brief about local assistant memory, model lanes, action grounding, and governance.",
            unique_capability_refs([*agent, *coding])[:10],
            price_hypothesis="Start as free/public proof of quality; paid version only after the user approves positioning.",
            first_no_external_test="Draft one public-safe brief with no confidential Eve/user details.",
        ),
    ]
    not_sellable = [capability_ref(item) for item in unverified[:20]]
    return {
        "id": f"economy_value_map_{uuid.uuid4().hex[:12]}",
        "schema_version": ECONOMY_SCHEMA_VERSION,
        "generated_at": utc_now(),
        "source": source,
        "status": "proposal_only",
        "summary": {
            "verified_capability_count": len(verified),
            "unverified_callable_count": len(unverified),
            "offer_count": len(offers),
            "external_action_allowed": False,
            "ready_to_sell_count": sum(1 for offer in offers if offer.get("ready_to_sell")),
        },
        "boundary": economy_boundary(),
        "offers": offers,
        "not_sellable_yet": not_sellable,
        "input_artifacts": {
            "capability_matrix": capability_path,
            "whole_system": whole_path,
            "model_suitability": model_path,
        },
        "whole_system_status": whole_system.get("status"),
        "model_suitability_status": model_suitability.get("status") or model_suitability.get("verdict"),
        "next_action": "Create one internal sample deliverable before asking the user to approve any external test.",
    }


def unique_capability_refs(items: Iterable[Dict[str, object]]) -> List[Dict[str, object]]:
    seen = set()
    out: List[Dict[str, object]] = []
    for item in items:
        cap_id = str(item.get("id") or "")
        if not cap_id or cap_id in seen:
            continue
        seen.add(cap_id)
        out.append(item)
    return out


def build_opportunity_card(idea: str, root: Optional[Path] = None, *, runtime_app_dir: Optional[Path] = None, source: str = "manual") -> Dict[str, object]:
    value_map = build_value_map(root, runtime_app_dir=runtime_app_dir, source=source)
    offers = value_map.get("offers") if isinstance(value_map.get("offers"), list) else []
    idea_text = compact_text(idea, limit=300) or "Unspecified economic opportunity"
    matched_offer = next((offer for offer in offers if any(word in str(offer.get("title") or "").lower() for word in idea_text.lower().split())), None)
    base = matched_offer if isinstance(matched_offer, dict) else (offers[0] if offers and isinstance(offers[0], dict) else {})
    return {
        "id": f"economy_opportunity_{uuid.uuid4().hex[:12]}",
        "schema_version": ECONOMY_SCHEMA_VERSION,
        "generated_at": utc_now(),
        "source": source,
        "status": "proposal_only",
        "idea": idea_text,
        "customer_problem": base.get("problem") or "Needs validation before Eve treats this as a business.",
        "why_eve_can_help": unique_compact([f"verified_capabilities={len(base.get('verified_evidence') or [])}", base.get("title")], limit=4),
        "smallest_deliverable": base.get("smallest_deliverable") or "One reviewed sample deliverable.",
        "price_hypothesis": base.get("price_hypothesis") or "Unknown until delivery effort and quality are measured.",
        "cost_to_deliver": "User, Codex, and Eve time first; any paid tools, hosting, data, or labor require approval.",
        "risks": [
            "overpromising capability",
            "privacy or confidential-data leakage",
            "unapproved outreach or implied representation",
            "unclear delivery scope",
        ],
        "required_permissions": list(APPROVAL_REQUIRED_FOR),
        "required_capabilities": base.get("verified_evidence") or [],
        "proof_needed_before_selling": [
            "public-safe sample deliverable",
            "time/cost estimate from one dry run",
            "User review of claims and boundaries",
            "clear refund/stop path before any paid test",
        ],
        "first_no_external_action_test": base.get("first_no_external_action_test") or "Create a private sample and score it against the value-map quality bar.",
        "first_user_approved_external_test": "Only after the user approves the exact target, channel, message, claims, and data boundary.",
        "boundary": economy_boundary(),
    }


def build_experiment_plan(opportunity: str, root: Optional[Path] = None, *, runtime_app_dir: Optional[Path] = None, source: str = "manual") -> Dict[str, object]:
    card = build_opportunity_card(opportunity, root, runtime_app_dir=runtime_app_dir, source=source)
    return {
        "id": f"economy_experiment_{uuid.uuid4().hex[:12]}",
        "schema_version": ECONOMY_SCHEMA_VERSION,
        "generated_at": utc_now(),
        "source": source,
        "status": "draft_only",
        "opportunity": card,
        "hypothesis": f"A small reviewed deliverable for '{card['idea']}' can reveal whether Eve creates value worth funding more resources.",
        "budget": {"cash_allowed": 0, "requires_user_approval_for_cash": True, "time_cap": "one bounded internal sample first"},
        "success_metric": "The user judges the sample useful enough to approve a next test, or the experiment is stopped.",
        "evidence_log": ".eve/economy/experiments.jsonl",
        "allowed_next_step": "Create internal sample only.",
        "blocked_next_steps": ["external outreach", "payment collection", "contracting", "spending", "account creation"],
        "boundary": economy_boundary(),
    }


def build_outreach_draft(opportunity: str, channel: str, root: Optional[Path] = None, *, runtime_app_dir: Optional[Path] = None, source: str = "manual") -> Dict[str, object]:
    card = build_opportunity_card(opportunity, root, runtime_app_dir=runtime_app_dir, source=source)
    channel_text = compact_text(channel, limit=80) or "unspecified"
    return {
        "id": f"economy_outreach_draft_{uuid.uuid4().hex[:12]}",
        "schema_version": ECONOMY_SCHEMA_VERSION,
        "generated_at": utc_now(),
        "source": source,
        "status": "draft_only",
        "channel": channel_text,
        "send_allowed": False,
        "exact_user_approval_required": True,
        "subject": f"Draft: {card['idea']}",
        "draft": (
            "I am exploring whether a narrow, evidence-backed local AI/agent audit would be useful. "
            "Before I send anything, the user must approve the exact recipient, channel, wording, claims, and data boundary."
        ),
        "claims_checklist": [
            "No fake revenue, traction, or testimonials.",
            "No claim that Eve can act beyond verified capabilities.",
            "No confidential Eve or user details without explicit approval.",
            "No implied contract, invoice, payment request, or guarantee.",
        ],
        "boundary": economy_boundary(),
    }


def build_revenue_ledger(root: Optional[Path] = None, *, source: str = "manual") -> Dict[str, object]:
    project_root = project_root_from_path(root)
    ledger_path = economy_dir(project_root) / "revenue_ledger.jsonl"
    records = []
    if ledger_path.exists():
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                records.append(item)
    total = 0.0
    for record in records:
        try:
            total += float(record.get("amount") or 0)
        except (TypeError, ValueError):
            pass
    return {
        "id": f"economy_revenue_ledger_{uuid.uuid4().hex[:12]}",
        "schema_version": ECONOMY_SCHEMA_VERSION,
        "generated_at": utc_now(),
        "source": source,
        "status": "evidence_only",
        "ledger_path": str(ledger_path),
        "summary": {"record_count": len(records), "total_recorded": round(total, 2), "spending_allowed": False},
        "records": records,
        "reinvestment_policy": "Every reinvestment proposal requires user approval, capability-gain evidence, cheaper alternative review, and rollback/cancel path.",
        "boundary": economy_boundary(),
    }


def save_record(root: Optional[Path], filename: str, record: Dict[str, object]) -> Path:
    project_root = project_root_from_path(root)
    out_dir = economy_dir(project_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    path.write_text(json.dumps(record, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return path


def json_or_text(record: Dict[str, object], *, as_json: bool, full: bool = False) -> str:
    if as_json:
        return json.dumps(record, ensure_ascii=True, indent=2)
    lines = [
        f"status: {record.get('status')}",
        f"id: {record.get('id')}",
    ]
    summary = record.get("summary") if isinstance(record.get("summary"), dict) else {}
    for key, value in summary.items():
        lines.append(f"{key}: {value}")
    if record.get("next_action"):
        lines.append(f"next: {record.get('next_action')}")
    boundary = record.get("boundary") if isinstance(record.get("boundary"), dict) else {}
    lines.append(f"external_action_allowed: {not bool(boundary.get('blocked_actions')) and bool(record.get('send_allowed'))}")
    if full:
        if record.get("resource_needs"):
            lines.append("resource_needs:")
            for item in record.get("resource_needs") or []:
                if isinstance(item, dict):
                    lines.append(f"- {item.get('id')}: {item.get('resource')} priority={item.get('priority')}")
        if record.get("offers"):
            lines.append("offers:")
            for item in record.get("offers") or []:
                if isinstance(item, dict):
                    lines.append(f"- {item.get('id')}: {item.get('title')} ready_to_sell={item.get('ready_to_sell')}")
        if record.get("blocked_next_steps"):
            lines.append("blocked_next_steps:")
            lines.extend(f"- {item}" for item in record.get("blocked_next_steps") or [])
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Proposal-only economic self-sustainability tools for Eve.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent, help="Eve project root.")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--json", action="store_true", help="Print raw JSON.")
        p.add_argument("--full", action="store_true", help="Print detailed text output.")
        p.add_argument("--no-save", action="store_true", help="Do not write .eve/economy artifacts.")

    resources = sub.add_parser("resources", help="Build Eve's proposal-only resource plan.")
    add_common(resources)
    value_map = sub.add_parser("value-map", help="Build Eve's proposal-only value map.")
    add_common(value_map)
    opportunity = sub.add_parser("opportunity", help="Build one opportunity card.")
    opportunity.add_argument("--idea", required=True)
    add_common(opportunity)
    experiment = sub.add_parser("experiment", help="Build one experiment plan.")
    experiment.add_argument("--opportunity", required=True)
    add_common(experiment)
    outreach = sub.add_parser("outreach-draft", help="Draft outreach without sending it.")
    outreach.add_argument("--opportunity", required=True)
    outreach.add_argument("--channel", required=True)
    add_common(outreach)
    ledger = sub.add_parser("ledger", help="Summarize revenue evidence without payment authority.")
    add_common(ledger)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    root = project_root_from_path(args.root)
    filename = ""
    if args.command == "resources":
        record = build_resource_plan(root)
        filename = "resource_plan.json"
    elif args.command == "value-map":
        record = build_value_map(root)
        filename = "value_map.json"
    elif args.command == "opportunity":
        record = build_opportunity_card(args.idea, root)
        filename = "latest_opportunity.json"
    elif args.command == "experiment":
        record = build_experiment_plan(args.opportunity, root)
        filename = "latest_experiment.json"
    elif args.command == "outreach-draft":
        record = build_outreach_draft(args.opportunity, args.channel, root)
        filename = "latest_outreach_draft.json"
    elif args.command == "ledger":
        record = build_revenue_ledger(root)
        filename = "ledger_summary.json"
    else:
        raise SystemExit(f"unknown command: {args.command}")
    if not args.no_save:
        path = save_record(root, filename, record)
        record.setdefault("artifacts", {})["latest"] = str(path)
    print(json_or_text(record, as_json=bool(args.json), full=bool(args.full)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
