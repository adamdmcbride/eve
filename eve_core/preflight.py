"""Ordered conversation integration without storage, models or global state."""
from typing import Mapping

from .preflight_ports import ConversationContinuity, ConversationEvidence, ConversationPerception, ConversationPreflightJournal
from .turns import ConversationPreflightResult, ConversationTurn


def _mapping(value, *, optional=False):
    if value is None and optional:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("invalid preflight mapping receipt")
    return dict(value)


class ConversationPreflight:
    def __init__(self, evidence: ConversationEvidence, perception: ConversationPerception,
                 continuity: ConversationContinuity, journal: ConversationPreflightJournal):
        self.evidence, self.perception = evidence, perception
        self.continuity, self.journal = continuity, journal

    def prepare(self, turn: ConversationTurn) -> ConversationPreflightResult:
        errors = []

        def failed(kind, summary, exc, metadata):
            # Failure text can contain credentials or private model inputs. Keep
            # only classification here; journaling itself cannot break fallback.
            reason = type(exc).__name__
            errors.append(kind + ": " + reason)
            if not turn.synthetic:
                try:
                    self.journal.warning(kind, summary, {**metadata, "reason": reason})
                except (Exception, SystemExit) as journal_error:
                    errors.append("preflight_journal_failed: " + type(journal_error).__name__)

        message_meta = {"thread_id": turn.thread_id, "observed_message_id": turn.message_id}
        operator = previous = social = correction = None
        messages = None
        if turn.surface == "reply":
            try:
                operator = _mapping(self.evidence.resolve_operator(), optional=True)
            except (Exception, SystemExit) as exc:
                failed("external_operator_result_resolution_failed",
                       "The reply continued, but Eve could not resolve the external-operator result envelope.",
                       exc, {"message_id": turn.message_id, "source_owner": turn.source_owner})
            if not turn.synthetic and turn.source_owner == "user":
                # Exact prior-reply feedback must reach the next recurrent cycle.
                try:
                    previous = _mapping(self.continuity.observe_previous(), optional=True)
                except (Exception, SystemExit) as exc:
                    failed("reply_consequence_observation_failed",
                           "The reply continued, but Eve could not join the prior reply's user consequence.", exc, message_meta)
                try:
                    social = _mapping(self.continuity.refresh_social(), optional=True)
                except (Exception, SystemExit) as exc:
                    failed("reply_social_preflight_failed",
                           "The reply continued, but Eve could not refresh the exact-lineage social state.", exc, message_meta)
            try:
                if self.evidence.needs_thread(turn.body):
                    messages = self.evidence.read_thread()
                    if not isinstance(messages, list) or any(not isinstance(item, Mapping) for item in messages):
                        raise ValueError("invalid thread receipt")
            except (Exception, SystemExit) as exc:
                messages = []
                failed("reply_reference_preflight_failed", "The reply continued without unavailable thread references.", exc, message_meta)
        else:
            messages = []
        # CLI retains its existing semantic/lesion controls. Synthetic mailbox
        # turns and external operator reports never trigger semantic escalation.
        allow_semantic = turn.surface == "chat" or (not turn.synthetic and operator is None)
        try:
            frame = _mapping(self.perception.perceive(turn.body, allow_semantic=allow_semantic, thread_messages=messages))
        except (Exception, SystemExit) as exc:
            frame = _mapping(self.perception.sparse(turn.body))
            failed("epistemic_perception_preflight_failed",
                   "Reply continued with the public sparse percept after semantic perception failed.", exc,
                   {"thread_id": turn.thread_id})
        source = (
            "chat_private_preflight" if turn.synthetic else "chat_preflight"
        ) if turn.surface == "chat" else (
            "reply_synthetic_preflight" if turn.synthetic else
            "reply_external_operator_result_preflight" if operator is not None else "reply_preflight"
        )
        state = {}
        try:
            state = _mapping(self.continuity.open_cycle(turn.body, source=source, persist=not turn.synthetic,
                                                       frame=frame, social=social))
        except (Exception, SystemExit) as exc:
            failed("conscious_cycle_preflight_failed", "Conversation continued after conscious-cycle preflight failed.",
                   exc, {"session_id": turn.session_id} if turn.surface == "chat" else {"thread_id": turn.thread_id})
        if turn.surface == "reply" and not turn.synthetic and turn.source_owner == "user":
            try:
                correction = _mapping(self.continuity.record_correction(
                    turn.body, target_message_id=str((previous or {}).get("scored_reply_id") or ""),
                    consequence_observed=(previous or {}).get("consequence_observed") is True,
                    consequence_joined=(previous or {}).get("conscious_consequence_joined") is True), optional=True)
            except (Exception, SystemExit) as exc:
                failed("reply_correction_preflight_failed", "The reply continued without a durable correction receipt.", exc, message_meta)
        return ConversationPreflightResult(operator, previous, social, messages, frame, state, correction, tuple(errors))
