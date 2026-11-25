"""Explicit request scope and receipts for conversation preflight."""
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class ConversationTurn:
    body: str
    surface: str
    synthetic: bool = False
    source_owner: str = "user"
    message_id: str = ""
    thread_id: str = ""
    session_id: str = ""
    learned_epistemic_enabled: bool = True

    def __post_init__(self):
        if self.surface not in {"reply", "chat"}:
            raise ValueError("unknown conversation surface")
        if not isinstance(self.synthetic, bool) or not isinstance(self.learned_epistemic_enabled, bool):
            raise ValueError("conversation policy flags must be booleans")


@dataclass(frozen=True)
class ConversationPreflightResult:
    external_operator_context: Optional[Dict[str, object]]
    prior_reply_consequence: Optional[Dict[str, object]]
    other_minds_model: Optional[Dict[str, object]]
    thread_messages: Optional[List[Dict[str, object]]]
    epistemic_frame: Dict[str, object]
    conscious_state: Dict[str, object]
    user_correction: Optional[Dict[str, object]]
    errors: Tuple[str, ...]
