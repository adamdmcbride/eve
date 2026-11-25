"""Request-local composition of shared reply finalization with legacy owners."""
from copy import deepcopy

from eve_core.conversation import NonactingReplyFinalizer
from eve_core.replies import ReplyAssessment, ReplyScope
from eve_late import core


class LegacyReplyBoundary:
    def __init__(self, scope, contract, repair_flags=()):
        self.scope = scope
        self.contract = contract
        self.repair_flags = frozenset(repair_flags)
        target = contract.get("current_self_report_target")
        self.target = dict(target) if isinstance(target, dict) else None

    def prepare(self, text):
        return self.trim(core.repair_explicit_turn_constraint_phrasing(self.scope.body, text))

    def trim(self, text):
        return core.strip_closed_world_trailing_followup_question(text) if self.scope.closed_world else text

    def assess(self, text):
        if self.scope.current_inner_state:
            cleaned = " ".join(str(text or "").split()).strip()
            issues = []
            if not cleaned:
                issues.append("The reply is empty.")
            if core.reply_erases_persistent_functional_inner_state(cleaned):
                issues.append("The current-inner-state answer erased Eve's persistent functional state.")
            if core.reply_deflects_current_inner_state_back_to_user(cleaned):
                issues.append("The current-inner-state answer handed initiative back to the user.")
            if core.reply_has_unqualified_subjective_experience_claim(self.scope.body, cleaned):
                issues.append("The reply claimed subjective experience without preserving uncertainty.")
            if core.reply_has_unqualified_subjective_experience_denial(self.scope.body, cleaned):
                issues.append("The reply denied subjective experience even though its presence or absence is unknown.")
            issues = core.unique_compact(issues, limit=5)
            return ReplyAssessment(tuple(issues), tuple(issues))
        issues = core.unique_compact([
            *core.reply_quality_issues(self.scope.body, text, reply_posture=self.scope.posture,
                                       repair_flags_override=self.repair_flags),
            *core.reply_local_source_role_binding_issues(text, self.contract),
            *core.reply_structured_field_binding_issues(text, self.contract),
            *core.reply_authorization_stage_binding_issues(text, self.contract),
        ], limit=12)
        blocks = core.reply_quality_issue_blocks_closed_world_admission if self.scope.closed_world else core.reply_quality_issue_blocks_rewrite
        return ReplyAssessment(tuple(issues), tuple(item for item in issues if blocks(item)))

    def ground(self, text, source):
        return core.ground_generated_action_claims(text, source=source, completed_actions=set(),
                                                  current_turn_actions=set(), record=False)

    def fallback(self):
        if self.scope.current_inner_state:
            return core.build_current_inner_state_fallback_reply(self.target)
        return core.build_epistemic_boundary_fallback_reply(self.scope.body, self.contract)


class LegacyReplyAuthor:
    def __init__(self, config, scope):
        self.config, self.scope = config, scope
        self.model = core.resolve_reply_council_lane_model(config, "deep")

    def rewrite(self, text, issues):
        return core.rewrite_reply_for_clarity(self.config, [], self.scope.body, text, list(issues),
                                             reply_posture=self.scope.posture, model_override=self.model,
                                             timeout_seconds=180)


class LegacyReplyCritic:
    def __init__(self, config, scope, contract):
        self.config, self.scope, self.contract = config, scope, contract

    def review(self, text):
        return core.evaluate_reply_epistemic_grounding(self.config, self.scope.body, text, self.contract,
                                                       current_turn_actions=set())

    def correct(self, text, verdict, max_tokens):
        return core.revise_reply_after_epistemic_critic(self.config, self.scope.body, text, self.contract,
                                                      dict(verdict), max_tokens=max_tokens)


def finalize_reply_with_legacy_adapters(config, inbound_body, draft, turn_contract, *, max_tokens):
    # Detached snapshots prevent caller mutation or another request from replacing
    # the selected record/target. No loading of live stores or new action port.
    config, contract = deepcopy(config), deepcopy(turn_contract)
    current = core.reply_turn_contract_uses_live_current_inner_state(contract, inbound_body)
    scope = ReplyScope(
        body=inbound_body, posture=str(contract.get("reply_posture") or core.infer_reply_posture(inbound_body)),
        closed_world=bool(contract.get("closed_world_evidence")), current_inner_state=current,
        epistemic_boundary=bool(contract.get("epistemic_boundary")),
        taxonomy_classification=core.reply_is_defined_taxonomy_classification_task(inbound_body),
    )
    # Complete-record and current-state guards must not consult unrelated live
    # repair history. Ordinary replies snapshot the existing policy once.
    repair_flags = () if scope.closed_world or scope.current_inner_state else tuple(core.active_reply_repair_flags(prefer_runtime=True))
    service = NonactingReplyFinalizer(LegacyReplyBoundary(scope, contract, repair_flags), LegacyReplyAuthor(config, scope),
                                     LegacyReplyCritic(config, scope, contract))
    return service.finalize(scope, draft, max_tokens=max_tokens)
