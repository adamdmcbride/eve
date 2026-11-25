"""Request-local wiring to existing evidence and recurrence owners."""
from copy import deepcopy

from eve_core.preflight import ConversationPreflight
from eve_core.turns import ConversationTurn
from eve_late import core


class LegacyConversationEvidence:
    def __init__(self, message, thread_limit):
        self.message, self.thread_limit = message, thread_limit

    def resolve_operator(self):
        return deepcopy(core.resolve_external_operator_result_context(deepcopy(self.message), prefer_runtime=True))

    def needs_thread(self, body):
        return core.epistemic_reference_resolution_request(body)

    def read_thread(self):
        return deepcopy(core.read_messages(thread_id=str(self.message.get("thread_id") or ""), limit=self.thread_limit))


class LegacyConversationPerception:
    def __init__(self, config, turn, *, lesion_event=False, allow_candidate_event=False):
        self.config, self.turn = config, turn
        self.lesion_event, self.allow_candidate_event = lesion_event, allow_candidate_event

    def perceive(self, body, *, allow_semantic, thread_messages):
        kwargs = {"allow_semantic": allow_semantic, "thread_messages": deepcopy(thread_messages)}
        if self.turn.surface == "chat":
            kwargs.update(lesion=not self.turn.learned_epistemic_enabled, lesion_event=self.lesion_event,
                          allow_candidate_event=self.allow_candidate_event)
        else:
            kwargs["current_message_id"] = self.turn.message_id
        return deepcopy(core.build_epistemic_perception_frame(deepcopy(self.config), body, **kwargs))

    def sparse(self, body):
        return core.eve_epistemic.lesioned_frame() if not self.turn.learned_epistemic_enabled else core.eve_epistemic.build_frame(body)


class LegacyConversationContinuity:
    def __init__(self, message, turn):
        self.message, self.turn = message, turn

    def observe_previous(self):
        return deepcopy(core.observe_inbound_reply_consequence(deepcopy(self.message)))

    def refresh_social(self):
        return deepcopy(core.build_reply_other_minds_preflight_state())

    def open_cycle(self, body, *, source, persist, frame, social):
        kwargs = {"source": source, "inbound": body, "persist": persist, "epistemic_frame_override": deepcopy(frame)}
        if self.turn.surface == "chat":
            kwargs["learned_epistemic_enabled"] = self.turn.learned_epistemic_enabled
        else:
            kwargs["other_minds_model"] = deepcopy(social)
        return deepcopy(core.build_recurrent_conscious_state(**kwargs))

    def record_correction(self, body, *, target_message_id, consequence_observed, consequence_joined):
        return deepcopy(core.record_user_correction(body, source="reply_turn", thread_id=self.turn.thread_id,
                        message_id=self.turn.message_id, target_message_id=target_message_id,
                        metadata={"surface": "generate_eve_reply", "prior_reply_consequence_observed": consequence_observed,
                                  "prior_reply_consequence_joined": consequence_joined}))


class LegacyConversationPreflightJournal:
    def warning(self, kind, summary, metadata):
        core.append_entry(kind, summary, metadata=metadata)


def _compose(config, message, turn, thread_limit=0, *, lesion_event=False, allow_candidate_event=False):
    return ConversationPreflight(
        LegacyConversationEvidence(deepcopy(message), thread_limit),
        LegacyConversationPerception(deepcopy(config), turn, lesion_event=lesion_event, allow_candidate_event=allow_candidate_event),
        LegacyConversationContinuity(deepcopy(message), turn), LegacyConversationPreflightJournal()).prepare(turn)


def prepare_reply_preflight(config, inbound_message, inbound_body, *, thread_limit):
    message = deepcopy(inbound_message)
    turn = ConversationTurn(inbound_body, "reply", synthetic=core.conversation_message_is_synthetic(message),
                            source_owner=core.message_source_owner(message), message_id=str(message.get("id") or ""),
                            thread_id=str(message.get("thread_id") or ""))
    return _compose(config, message, turn, thread_limit)


def prepare_chat_preflight(config, body, *, session_id, private_audit=False, lesion=False, lesion_event=False):
    turn = ConversationTurn(body, "chat", synthetic=bool(private_audit), session_id=session_id,
                            learned_epistemic_enabled=not lesion)
    return _compose(config, {}, turn, lesion_event=lesion_event, allow_candidate_event=bool(private_audit))
