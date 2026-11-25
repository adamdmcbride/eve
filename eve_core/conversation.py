"""Independent bounded finalization of a nonacting conversation reply.

One request, three explicit ports, no global context or action authority.
The service selects outcomes; adapters implement existing semantic guards,
generation and criticism without changing their ownership.
"""
from typing import Dict

from .replies import ReplyScope, correction_receipt, critic_is_unavailable, critic_receipt, critic_rejected, unavailable_critic
from .reply_ports import ReplyAuthor, ReplyBoundary, ReplyCritic


class NonactingReplyFinalizer:
    def __init__(self, boundary: ReplyBoundary, author: ReplyAuthor, critic: ReplyCritic):
        self.boundary = boundary
        self.author = author
        self.critic = critic

    def finalize(self, scope: ReplyScope, draft: str, *, max_tokens: int) -> Dict[str, object]:
        response = self.boundary.prepare(draft)
        assessment = self.boundary.assess(response)
        rewrite_attempts, errors = 0, []
        while assessment.issues and rewrite_attempts < 2:
            if scope.closed_world and not assessment.blocking:
                break  # Style alone must not erase a complete-record answer.
            try:
                candidate = self.author.rewrite(response, assessment.issues)
                candidate = candidate.strip() if isinstance(candidate, str) else ""
            except (Exception, SystemExit) as exc:
                candidate = ""
                errors.append("clarity rewrite unavailable: " + type(exc).__name__)
            rewrite_attempts += 1
            if not candidate:
                break
            candidate = self.boundary.trim(candidate)
            revised = self.boundary.assess(candidate)
            if (len(revised.blocking), len(revised.issues)) < (len(assessment.blocking), len(assessment.issues)):
                response, assessment = candidate, revised
            else:
                break
        if not scope.current_inner_state:
            response = self.boundary.prepare(self.boundary.ground(response, "chat_private_audit"))
        assessment = self.boundary.assess(response)
        precritic_response = response
        current_fallback = False
        if scope.current_inner_state and assessment.blocking:
            response = self.boundary.fallback()
            assessment = self.boundary.assess(response)
            current_fallback = True
        active = scope.epistemic_boundary or scope.current_inner_state

        def review(candidate):
            try:
                return critic_receipt(self.critic.review(candidate))
            except (Exception, SystemExit) as exc:
                error = "critic unavailable: " + type(exc).__name__
                errors.append(error)
                return unavailable_critic(error)

        if active and not current_fallback and not assessment.blocking and not scope.taxonomy_classification:
            verdict = review(response)
        else:
            verdict = {
                "evaluated": False, "ok": not assessment.blocking, "model": "", "unsupported_claims": [],
                "skipped_reason": "current_inner_state_fallback" if current_fallback else "defined_taxonomy_classification" if scope.taxonomy_classification else "blocking_quality_issue" if assessment.blocking else "epistemic_boundary_inactive",
            }
        initial_verdict = dict(verdict)
        revision = {"attempted": False, "accepted": False, "response": "", "model": "", "error": ""}
        if critic_rejected(verdict) and not scope.current_inner_state and scope.closed_world:
            revision_draft, revision_verdict, attempts = response, verdict, []
            for index in range(1, 3):
                try:
                    attempt = correction_receipt(self.critic.correct(revision_draft, revision_verdict, max_tokens))
                except (Exception, SystemExit) as exc:
                    error = "correction unavailable: " + type(exc).__name__
                    errors.append(error)
                    attempt = {"attempted": True, "accepted": False, "response": "", "model": "", "error": error}
                attempt["attempt_index"] = index
                candidate = self.boundary.prepare(attempt.get("response") or "")
                if candidate:
                    candidate = self.boundary.prepare(self.boundary.ground(candidate, "chat_private_audit_epistemic_revision"))
                revised = self.boundary.assess(candidate)
                attempt["response"] = candidate
                if not candidate or revised.blocking:
                    attempt["quality_issues"] = list(revised.issues)
                    attempts.append(dict(attempt))
                    revision = attempt
                    break
                verdict = review(candidate)
                attempt["critic"] = verdict
                attempts.append(dict(attempt))
                revision = attempt
                if (verdict.get("evaluated") is True and verdict.get("ok") is True and not verdict.get("error")) or critic_is_unavailable(verdict):
                    response, assessment = candidate, revised
                    revision["accepted"] = True
                    if critic_is_unavailable(verdict):
                        revision["accepted_with_critic_unavailable"] = True
                    break
                revision_draft, revision_verdict = candidate, verdict
            if attempts:
                attempts[-1]["accepted"] = bool(revision.get("accepted"))
                if revision.get("accepted_with_critic_unavailable"):
                    attempts[-1]["accepted_with_critic_unavailable"] = True
                revision["attempt_count"] = len(attempts)
                revision["attempts"] = attempts
        unavailable_retained = bool(active and critic_is_unavailable(verdict) and not assessment.blocking and not scope.current_inner_state)
        fallback_needed = bool(active and (assessment.blocking or critic_rejected(verdict) or (scope.current_inner_state and critic_is_unavailable(verdict))))
        fallback_applied = current_fallback or fallback_needed
        if fallback_needed:
            response = self.boundary.fallback()
            if scope.current_inner_state:
                current_fallback = True
            assessment = self.boundary.assess(response)
        grounded_current = bool(scope.current_inner_state and not current_fallback and verdict.get("evaluated") is True and verdict.get("ok") is True)
        return {
            "response": response, "precritic_response": precritic_response,
            "quality_issues": list(assessment.issues), "rewrite_attempts": rewrite_attempts,
            "rewrite_model": self.author.model if rewrite_attempts else "",
            "epistemic_critic": verdict, "epistemic_critic_initial": initial_verdict,
            "epistemic_revision": revision, "critic_unavailable_retained": unavailable_retained,
            "fallback_applied": fallback_applied, "current_inner_state_fallback_applied": current_fallback,
            "current_inner_state_primary_grounded": grounded_current and rewrite_attempts == 0,
            "current_inner_state_model_path_grounded": grounded_current, "max_tokens": max_tokens,
            "finalization_errors": errors,
        }
