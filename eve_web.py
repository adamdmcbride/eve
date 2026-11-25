#!/usr/bin/env python3

import copy
import hashlib
import json
import os
import sys
import threading
import time
import uuid
import webbrowser
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Dict, Optional

import eve
from eve_chat_protocol import (
    EVE_CHAT_FOLLOWUP_LEASE_SECONDS,
    EVE_CHAT_FOLLOWUP_MAX_DELAY_SECONDS,
    EVE_CHAT_FOLLOWUP_POLL_ORIGINS,
    EVE_CHAT_FOLLOWUP_SUPPORTED_ACTIONS,
    EVE_CHAT_FOLLOWUP_WAIT_SLICE_SECONDS,
    canonical_eve_chat_local_origin,
    dict_field,
    durable_eve_chat_followup_action_result,
    eve_chat_followup_ack_text,
    eve_chat_followup_action_for_messages,
    eve_chat_followup_delay_seconds,
    eve_chat_followup_delivery_text,
    eve_chat_followup_due_at,
    eve_chat_followup_requested,
    eve_chat_followup_seconds_until_due,
    first_transport_value,
    openai_chat_evaluation_metadata,
    openai_chat_thread_id,
    openai_chat_transport_metadata,
    recover_eve_chat_followup_action_result,
)
from eve_chat_followups import (
    EveChatFollowupHooks,
    EveChatFollowupPolicy,
    EveChatFollowupService,
)
from eve_agui import (
    COPILOTKIT_AGUI_PROTOCOL,
    agui_event,
    agui_timestamp_ms,
    copilotkit_agui_completion_reply,
    copilotkit_agui_context,
    copilotkit_agui_progress_content,
    normalize_copilotkit_agui_messages,
)
from eve_install_artifacts import (
    MAC_INSTALLER_APP_NAME,
    MAC_INSTALLER_FILENAME,
    MAC_INSTALLER_VERSION,
    advertised_endpoint_query,
    build_linux_installer_bundle,
    build_macos_installer_app_bundle,
    build_macos_installer_bundle,
    build_unix_installer_script,
    build_windows_app_package_archive,
    build_windows_installer_exe,
    build_windows_installer_script,
    customized_windows_launcher,
    customized_windows_script,
    render_install_page,
    render_windows_install_page,
    stage_windows_installer_payload,
    trusted_installer_endpoint,
)
from eve_monitor_projection import (
    _monitor_first_priority,
    _monitor_fitness_checks,
    _monitor_long_run_metrics,
    _monitor_priority_rows,
    _monitor_rank_summary,
    action_execution_to_monitor_json,
    active_mind_audit_event_to_json,
    activity_lane_to_monitor_json,
    autonomy_run_to_monitor_json,
    build_monitor_payload,
    build_monitor_status_payload,
    clamp_percent,
    commitment_record_to_monitor_json,
    conversation_spine_turn_to_monitor_json,
    daemon_running_from_state,
    entry_preview,
    entry_to_json,
    evaluation_to_json,
    evidence_record_to_monitor_json,
    experience_event_to_monitor_json,
    experiment_to_json,
    failure_cluster_to_json,
    fitness_to_monitor_json,
    governance_to_monitor_json,
    human_context_signals_to_monitor_json,
    load_json_file,
    message_preview,
    message_to_json,
    model_call_event_to_monitor_json,
    model_call_matches_lane,
    outcome_to_json,
    process_kind,
    process_title,
    proposal_to_json,
    read_disk_snapshot,
    read_memory_snapshot,
    read_process_table,
    read_recent_jsonl,
    relationship_episode_to_monitor_json,
    reply_council_turn_for_message,
    reply_council_turn_to_monitor_json,
    reply_progress_to_json,
    reply_stream_packets_for_message,
    reply_turn_replay_to_monitor_json,
    safe_float,
    safe_int,
    selected_processes,
    system_task_to_monitor_json,
    tension_to_json,
    text_preview,
    thread_to_json,
    user_correction_to_monitor_json,
)
import eve_attachments
import eve_db
import eve_http_body
import eve_http_headers
import eve_http_json
import eve_http_path
import eve_http_query
import eve_http_security
import eve_http_server
from eve_openai_compat import (
    MAX_OPENAI_COMPAT_CONTEXT_CHARS,
    MAX_OPENAI_COMPAT_MESSAGE_CHARS,
    OPENAI_COMPAT_MODEL_ALIASES,
    OPENAI_COMPAT_MODEL_ID,
    auxiliary_ui_reply as openai_compat_auxiliary_ui_reply,
    estimate_openai_token_count,
    latest_openai_user_content,
    normalize_openai_chat_messages,
    normalize_openai_identifier,
    openai_chat_completion_payload,
    openai_compat_created_at,
    openai_compat_exact_literal_reply,
    openai_message_content_text,
    openai_message_part_text,
    openai_messages_to_eve_body,
    openai_model_record,
)
import eve_sensory
from eve_sensory_sessions import SensorySessionPolicy, SensorySessionService
from eve_runtime_projection import (
    RuntimeProjectionConfig,
    build_activity_payload as build_runtime_activity_payload,
    build_latest_state as build_runtime_latest_state,
    build_model_health_payload as build_runtime_model_health_payload,
)
import eve_profile


ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web"
BIN_DIR = ROOT / "bin"
API_VERSION = 7
EVE_APP_SNAPSHOT_SCHEMA = "eve_app_snapshot.v1"
MODEL_WATCHDOG_STATUS_PATH = eve.APP_DIR / "model_watchdog_status.json"
MODEL_HEALTH_LOG_PATH = eve.APP_DIR / "model_health.jsonl"
RUNTIME_MODEL_WATCHDOG_STATUS_PATH = eve.RUNTIME_APP_DIR / "model_watchdog_status.json"
RUNTIME_MODEL_HEALTH_LOG_PATH = eve.RUNTIME_APP_DIR / "model_health.jsonl"
CAPTURE_KINDS = {
    "observation",
    "goal",
    "learning",
    "experiment",
    "human_interaction",
    "task_outcome",
    "note",
}
ATTACHMENT_STORE_DIR = eve.RUNTIME_APP_DIR / "attachments"
ATTACHMENT_EXTRACT_DIR = ATTACHMENT_STORE_DIR / "extracted"
ATTACHMENT_INDEX_PATH = eve.RUNTIME_APP_DIR / "attachments.jsonl"
ATTACHMENT_EVIDENCE_MARKER = "\n\nAttached files for Eve to inspect:\n"
MAX_ATTACHMENT_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_ATTACHMENT_EXTRACT_CHARS = 12000
MAX_ATTACHMENT_MODEL_CHARS_PER_FILE = 6000
MAX_ATTACHMENT_MODEL_CHARS_TOTAL = 18000
MAX_JSON_REQUEST_BYTES = 2 * 1024 * 1024
MAX_CONVERSATION_BODY_CHARACTERS = 32_000
MAX_CONVERSATION_SUBJECT_CHARACTERS = 512
MAX_CLIENT_REQUEST_ID_CHARACTERS = 160
MAX_CAPTURE_TAGS = 32
MAX_ATTACHMENT_JSON_REQUEST_BYTES = (
    4 * ((MAX_ATTACHMENT_UPLOAD_BYTES + 2) // 3) + 64 * 1024
)
OPENAI_COMPAT_REPLY_CONFIG_OVERRIDES = {
    # Eve Chat uses the same executive scheduler and reply council as every
    # other conversation surface. Do not disable reply streams here: doing so
    # allowed the scheduler to admit deep/relationship lanes while silently
    # executing only the fast lane, which made the saved causal trace false.
    # The council itself keeps ordinary turns on the fast path and escalates
    # only when current-turn pressure crosses a lane threshold.
    "reply_recent_context_limit": 4,
    "reply_thread_context_limit": 4,
    "reply_active_thread_limit": 2,
    "reply_tracker_limit": 1,
    "reply_proposal_limit": 0,
    "model_governor_context_overflow_enforce": False,
}
COPILOTKIT_AGUI_ACTIVITY_TYPE = "EVE_REPLY_PROGRESS"
SENSORY_SESSION_MIN_SECONDS = 30
SENSORY_SESSION_MAX_SECONDS = 60 * 60
SENSORY_SESSION_MAX_BATCHES_PER_10_SECONDS = 10
SENSORY_SESSION_MAX_EVENTS = 5_000
SENSORY_SESSION_MAX_ACTIVE = 4
SENSORY_REQUEST_MAX_BYTES = 128 * 1024
SENSORY_SESSION_MODALITIES = {"auditory", "visual", "proprioceptive"}


def _sensory_session_policy() -> SensorySessionPolicy:
    """Read patchable composition constants without duplicating policy state."""
    return SensorySessionPolicy(
        min_seconds=SENSORY_SESSION_MIN_SECONDS,
        max_seconds=SENSORY_SESSION_MAX_SECONDS,
        max_batches_per_10_seconds=SENSORY_SESSION_MAX_BATCHES_PER_10_SECONDS,
        max_events=SENSORY_SESSION_MAX_EVENTS,
        max_active=SENSORY_SESSION_MAX_ACTIVE,
        modalities=frozenset(SENSORY_SESSION_MODALITIES),
    )


def _runtime_projection_config() -> RuntimeProjectionConfig:
    """Snapshot composition-owned status paths for one projection build."""

    return RuntimeProjectionConfig(
        api_version=API_VERSION,
        model_watchdog_status_path=MODEL_WATCHDOG_STATUS_PATH,
        model_health_log_path=MODEL_HEALTH_LOG_PATH,
        runtime_model_watchdog_status_path=RUNTIME_MODEL_WATCHDOG_STATUS_PATH,
        runtime_model_health_log_path=RUNTIME_MODEL_HEALTH_LOG_PATH,
    )


def _eve_chat_followup_policy() -> EveChatFollowupPolicy:
    """Snapshot patchable follow-up constants for one worker operation."""

    return EveChatFollowupPolicy(
        lease_seconds=EVE_CHAT_FOLLOWUP_LEASE_SECONDS,
        wait_slice_seconds=EVE_CHAT_FOLLOWUP_WAIT_SLICE_SECONDS,
        supported_actions=frozenset(EVE_CHAT_FOLLOWUP_SUPPORTED_ACTIONS),
    )


TEXT_ATTACHMENT_EXTENSIONS = eve_attachments.TEXT_ATTACHMENT_EXTENSIONS


def _attachment_policy() -> eve_attachments.AttachmentPolicy:
    """Build the attachment seam from patchable legacy module constants."""
    return eve_attachments.AttachmentPolicy(
        store_dir=ATTACHMENT_STORE_DIR,
        extract_dir=ATTACHMENT_EXTRACT_DIR,
        index_path=ATTACHMENT_INDEX_PATH,
        evidence_marker=ATTACHMENT_EVIDENCE_MARKER,
        max_upload_bytes=MAX_ATTACHMENT_UPLOAD_BYTES,
        max_extract_chars=MAX_ATTACHMENT_EXTRACT_CHARS,
        max_model_chars_per_file=MAX_ATTACHMENT_MODEL_CHARS_PER_FILE,
        max_model_chars_total=MAX_ATTACHMENT_MODEL_CHARS_TOTAL,
    )


def safe_attachment_filename(name: str) -> str:
    return eve_attachments.safe_attachment_filename(name)


def attachment_type_label(name: str, mime_type: Optional[str] = None) -> str:
    return eve_attachments.attachment_type_label(name, mime_type)


def format_attachment_size(byte_count: int) -> str:
    return eve_attachments.format_attachment_size(byte_count)


def attachment_path_under_store(path: Path) -> bool:
    return eve_attachments.attachment_path_under_store(path, _attachment_policy())


def sha256_file(path: Path) -> str:
    return eve_attachments.sha256_file(path)


def strip_attachment_evidence_block(body: str) -> str:
    return eve_attachments.strip_attachment_evidence_block(body, _attachment_policy())


def extract_attachment_text(path: Path, attachment_id: str) -> Dict[str, object]:
    return eve_attachments.extract_attachment_text(path, attachment_id, _attachment_policy())


def normalize_attachment_payload(payload: Dict[str, object]) -> Dict[str, object]:
    return eve_attachments.normalize_attachment_payload(payload, _attachment_policy())


def upload_attachment_from_json(payload: Dict[str, object]) -> Dict[str, object]:
    return eve_attachments.upload_attachment_from_json(payload, _attachment_policy())


def record_attachments_for_message(
    raw_attachments: list[Dict[str, object]],
    message: Dict[str, object],
    client_request_id: Optional[str] = None,
) -> list[Dict[str, object]]:
    return eve_attachments.record_attachments_for_message(
        raw_attachments,
        message,
        _attachment_policy(),
        client_request_id=client_request_id,
        utc_now=eve.utc_now,
    )


def attachment_evidence_block(records: list[Dict[str, object]]) -> str:
    return eve_attachments.attachment_evidence_block(records)


def attachment_text_excerpts(records: list[Dict[str, object]]) -> str:
    return eve_attachments.attachment_text_excerpts(records, _attachment_policy())


def message_body_with_attachment_evidence(
    body: str,
    records: list[Dict[str, object]],
) -> str:
    return eve_attachments.message_body_with_attachment_evidence(
        body,
        records,
        _attachment_policy(),
    )


def attachment_metadata(records: list[Dict[str, object]]) -> Dict[str, object]:
    return eve_attachments.attachment_metadata(records)


def read_attachment_records(
    thread_id: Optional[str] = None,
    message_id: Optional[str] = None,
    limit: int = 100,
) -> list[Dict[str, object]]:
    return eve_attachments.read_attachment_records(
        _attachment_policy(),
        thread_id=thread_id,
        message_id=message_id,
        limit=limit,
    )


def json_bytes(payload: Dict[str, object]) -> bytes:
    return json.dumps(payload, ensure_ascii=True).encode("utf-8")





class TTLCache:
    def __init__(self, ttl_seconds: float):
        self.ttl_seconds = ttl_seconds
        self._value: Optional[object] = None
        self._expires_at = 0.0

    def get(self) -> Optional[object]:
        if self._value is None:
            return None
        if time.monotonic() >= self._expires_at:
            self.clear()
            return None
        return copy.deepcopy(self._value)

    def set(self, value: object) -> object:
        self._value = copy.deepcopy(value)
        self._expires_at = time.monotonic() + self.ttl_seconds
        return copy.deepcopy(value)

    def clear(self) -> None:
        self._value = None
        self._expires_at = 0.0


class EveRuntimeService:
    def __init__(self, status_ttl_seconds: float = 2.0, model_health_ttl_seconds: float = 5.0, activity_ttl_seconds: float = 1.0):
        self._status_cache = TTLCache(status_ttl_seconds)
        self._model_health_cache = TTLCache(model_health_ttl_seconds)
        self._activity_cache = TTLCache(activity_ttl_seconds)
        self._mutation_lock = threading.RLock()
        self._status_refresh_lock = threading.Lock()
        self._model_health_refresh_lock = threading.Lock()
        self._activity_refresh_lock = threading.Lock()
        self._eve_chat_followup_service = EveChatFollowupService(
            policy_provider=_eve_chat_followup_policy,
            hooks=EveChatFollowupHooks(
                run_mutation=lambda operation: self._run_mutation(operation),
                start_worker=lambda followup_id: self.start_eve_chat_followup_worker(followup_id),
                existing_delivery=lambda followup_id, thread_id: self._existing_eve_chat_followup_delivery(
                    followup_id,
                    thread_id,
                ),
                complete_cycle=lambda **kwargs: self._complete_eve_chat_followup_cycle(**kwargs),
                recover_action_result=lambda record: recover_eve_chat_followup_action_result(record),
            ),
        )
        # Preserve prior introspection while the child service becomes the
        # single owner of in-process worker admission state.
        self._followup_workers_lock = self._eve_chat_followup_service._followup_workers_lock
        self._active_followup_workers = self._eve_chat_followup_service._active_followup_workers
        self._sensory_session_service = SensorySessionService(
            database_path_provider=lambda: self._sensory_database_path(),
            policy_provider=_sensory_session_policy,
        )
        # Preserve the existing introspection/patch seam while the composed
        # service becomes the single owner of session state.
        self._sensory_sessions_lock = self._sensory_session_service._sensory_sessions_lock
        self._sensory_sessions = self._sensory_session_service._sensory_sessions

    def invalidate_caches(self) -> None:
        self._status_cache.clear()
        self._model_health_cache.clear()
        self._activity_cache.clear()

    def _run_mutation(self, operation):
        with self._mutation_lock:
            try:
                return operation()
            finally:
                self.invalidate_caches()

    @staticmethod
    def _sensory_database_path() -> Path:
        runtime_path = eve.RUNTIME_OPERATIONAL_DB_PATH
        if runtime_path.exists() or eve.running_from_runtime_bundle():
            return runtime_path
        return eve.OPERATIONAL_DB_PATH

    def _sensory_session_observation_stats(self, session_id: str) -> tuple[int, Optional[str]]:
        return self._sensory_session_service._sensory_session_observation_stats(session_id)

    def _sensory_session_observation_count(self, session_id: str) -> int:
        return self._sensory_session_service._sensory_session_observation_count(session_id)

    def _write_sensory_observations(
        self,
        record: Dict[str, object],
        events: list[Dict[str, object]],
    ) -> tuple[list[Dict[str, object]], int]:
        return self._sensory_session_service._write_sensory_observations(record, events)

    def _prune_sensory_sessions(self, *, now: Optional[datetime] = None) -> None:
        self._sensory_session_service._prune_sensory_sessions(now=now)

    def _rehydrate_sensory_session(self, session_id: str) -> Optional[Dict[str, object]]:
        return self._sensory_session_service._rehydrate_sensory_session(session_id)

    @staticmethod
    def _public_sensory_session(record: Dict[str, object]) -> Dict[str, object]:
        return SensorySessionService._public_sensory_session(record)

    def sensory_status(self) -> Dict[str, object]:
        return self._sensory_session_service.sensory_status()

    def start_sensory_session(self, payload: Dict[str, object]) -> Dict[str, object]:
        return self._sensory_session_service.start_sensory_session(payload)

    def _authorized_sensory_session(self, session_id: object, token: object) -> Dict[str, object]:
        return self._sensory_session_service._authorized_sensory_session(session_id, token)

    def stop_sensory_session(self, payload: Dict[str, object]) -> Dict[str, object]:
        return self._sensory_session_service.stop_sensory_session(payload)

    def ingest_sensory_events(self, payload: Dict[str, object]) -> Dict[str, object]:
        return self._sensory_session_service.ingest_sensory_events(payload)

    def _find_message(self, message_id: str) -> tuple[list[Dict[str, object]], Dict[str, object]]:
        messages = eve.read_messages()
        try:
            index = eve.find_record_index(messages, message_id)
        except SystemExit as exc:
            raise LookupError(str(exc)) from exc
        return messages, messages[index]

    def ordered_thread_summaries(self, limit: Optional[int] = None, status: Optional[str] = None) -> list[Dict[str, object]]:
        summaries = list(reversed(eve.read_thread_summaries()))
        if status:
            summaries = [item for item in summaries if item.get("status") == status]
        if limit is not None:
            summaries = summaries[:limit]
        return summaries

    def activity_entries(self, limit: int) -> list[Dict[str, object]]:
        return eve.read_entries(limit=limit, exclude_kinds=sorted(eve.LOW_SIGNAL_ENTRY_KINDS))

    def _build_model_health_payload(self, limit: int = 5) -> Dict[str, object]:
        return build_runtime_model_health_payload(
            config=_runtime_projection_config(),
            limit=limit,
        )

    def model_health_payload(self, limit: int = 5, force: bool = False) -> Dict[str, object]:
        if not force:
            cached = self._model_health_cache.get()
            if cached is not None:
                return cached
        with self._model_health_refresh_lock:
            if not force:
                cached = self._model_health_cache.get()
                if cached is not None:
                    return cached
            return self._model_health_cache.set(self._build_model_health_payload(limit=limit))

    def _build_activity_payload(self, model_health: Optional[Dict[str, object]] = None) -> Dict[str, object]:
        health = model_health if isinstance(model_health, dict) else self.model_health_payload(limit=5)
        return build_runtime_activity_payload(model_health=health)

    def activity_payload(self, model_health: Optional[Dict[str, object]] = None, force: bool = False) -> Dict[str, object]:
        if not force:
            cached = self._activity_cache.get()
            if cached is not None:
                return cached
        with self._activity_refresh_lock:
            if not force:
                cached = self._activity_cache.get()
                if cached is not None:
                    return cached
            return self._activity_cache.set(self._build_activity_payload(model_health=model_health))

    def _build_latest_state(self) -> Dict[str, object]:
        return build_runtime_latest_state(
            config=_runtime_projection_config(),
            ordered_thread_summaries=self.ordered_thread_summaries,
            model_health_payload=self.model_health_payload,
        )

    def latest_state(self, force: bool = False) -> Dict[str, object]:
        if not force:
            cached = self._status_cache.get()
            if cached is not None:
                return cached
        with self._status_refresh_lock:
            if not force:
                cached = self._status_cache.get()
                if cached is not None:
                    return cached
            return self._status_cache.set(self._build_latest_state())

    def bootstrap_payload(
        self,
        primary_host: str = "",
        api_port: int = 8787,
        ollama_port: int = 11434,
    ) -> Dict[str, object]:
        return eve.bootstrap_bundle_payload(
            primary_host=primary_host,
            api_port=api_port,
            ollama_port=ollama_port,
        )

    def update_manifest(
        self,
        primary_host: str = "",
        api_port: int = 8787,
        ollama_port: int = 11434,
    ) -> Dict[str, object]:
        payload = eve.build_update_manifest(
            primary_host=primary_host,
            api_port=api_port,
            ollama_port=ollama_port,
        )
        if primary_host:
            app_package = build_windows_app_package_archive(primary_host, api_port)
            payload["app_package"] = {
                "sha256": hashlib.sha256(app_package).hexdigest(),
                "bytes": len(app_package),
                "filename": "EveWindowsAppPackage.zip",
            }
        return payload

    def code_bundle_archive(self) -> bytes:
        return eve.build_code_bundle_archive()

    def windows_app_package_archive(self, primary_host: str, api_port: int) -> bytes:
        return build_windows_app_package_archive(primary_host, api_port)

    def last_active_thread_id(self, threads: list[Dict[str, object]]) -> Optional[str]:
        for thread in threads:
            if thread.get("status") != "archived":
                return str(thread.get("thread_id"))
        return None

    def wake_eve_if_needed(self) -> Dict[str, object]:
        def operation() -> Dict[str, object]:
            config = eve.load_config()
            state = eve.load_state()
            now = datetime.now(timezone.utc)
            started_daemon = False

            if not daemon_running_from_state(state):
                try:
                    eve.start_launch_agent()
                except SystemExit:
                    eve.install_launch_agent()
                    eve.start_launch_agent()
                started_daemon = True

            state = eve.load_state()
            last_loop = eve.parse_iso_datetime(state.get("last_loop_at"))
            should_wake = started_daemon or last_loop is None or now - last_loop > timedelta(minutes=5) or not state.get("current_focus")
            completed: list[str] = []
            outreach_record: Optional[Dict[str, object]] = None

            if should_wake:
                state["last_loop_at"] = eve.utc_now()
                state["last_outreach_check_at"] = eve.utc_now()
                try:
                    result = eve.generate_continuous_thought(
                        config,
                        context_limit=int(config["thought_context_limit"]),
                        thought_history_limit=int(config["thought_history_limit"]),
                        max_tokens=int(config["thought_max_tokens"]),
                    )
                    eve.append_entry(
                        "thought",
                        str(result["response"]),
                        metadata={
                            "model": result["model"],
                            "source_entries": result["source_entries"],
                            "source_thoughts": result["source_thoughts"],
                            "source_threads": result["source_threads"],
                            "source_messages": result["source_messages"],
                            "source": "web_wake",
                        },
                    )
                    state["last_loop_at"] = eve.utc_now()
                    state["last_thought_at"] = eve.utc_now()
                    state["current_focus"] = " ".join(str(result["response"]).split())[:160]
                    completed.append("thought")
                except SystemExit as exc:
                    eve.append_entry("wake_error", f"wake thought failed: {exc}", metadata={"source": "web"})

                try:
                    outreach_record = eve.create_eve_outreach_message(
                        config,
                        source="web_wake",
                        notify=False,
                        allow_none=True,
                        state=state,
                    )
                    if outreach_record is not None:
                        state["last_outreach_at"] = eve.utc_now()
                        completed.append("outreach")
                except SystemExit as exc:
                    eve.append_entry("wake_error", f"wake outreach failed: {exc}", metadata={"source": "web"})
                    eve.record_personal_conversation_check(
                        source="web_wake",
                        status="failed",
                        reason=f"Personal conversation check failed: {exc}",
                        state=state,
                    )

                threads = eve.read_thread_summaries(limit=24)
                state["thread_attention"] = threads
                state["active_thread_count"] = len([item for item in threads if item.get("status") != "archived"])
                eve.save_state(state)

            threads = self.ordered_thread_summaries(limit=24)
            return {
                "status": self.latest_state(force=True),
                "completed": completed,
                "selected_thread_id": str(outreach_record["thread_id"]) if outreach_record else self.last_active_thread_id(threads),
                "awakened": bool(should_wake),
            }

        return self._run_mutation(operation)

    def threads(self, limit: int = 30, status: Optional[str] = None, audience: Optional[str] = None) -> list[Dict[str, object]]:
        threads = self.ordered_thread_summaries(limit=limit, status=status)
        if audience:
            threads = [item for item in threads if str(item.get("audience") or "user") == audience]
        return [thread_to_json(item) for item in threads]

    def reply_progress(
        self,
        client_request_id: Optional[str] = None,
        thread_id: Optional[str] = None,
        active_only: bool = True,
    ) -> Dict[str, object]:
        progress = eve.latest_reply_progress(
            client_request_id=client_request_id,
            thread_id=thread_id,
            active_only=active_only,
        )
        return {"job": reply_progress_to_json(progress)}

    def reply_turn_replays(
        self,
        limit: int = 20,
        thread_id: Optional[str] = None,
        reply_message_id: Optional[str] = None,
    ) -> list[Dict[str, object]]:
        records = eve.read_reply_turn_replays(
            limit=limit,
            thread_id=thread_id,
            reply_message_id=reply_message_id,
            prefer_runtime=True,
        )
        return [reply_turn_replay_to_monitor_json(item) for item in records]

    def reply_council_turns(
        self,
        limit: int = 20,
        thread_id: Optional[str] = None,
        reply_message_id: Optional[str] = None,
    ) -> list[Dict[str, object]]:
        records = eve.read_reply_council_turns(
            limit=limit,
            thread_id=thread_id,
            reply_message_id=reply_message_id,
            prefer_runtime=True,
        )
        return [reply_council_turn_to_monitor_json(item) for item in records]

    def conversation_spine(
        self,
        limit: int = 20,
        thread_id: Optional[str] = None,
        role: Optional[str] = None,
        direction: Optional[str] = None,
        include_synthetic: bool = True,
    ) -> list[Dict[str, object]]:
        records = eve.read_conversation_spine_turns(
            limit=limit,
            thread_id=thread_id,
            role=role,
            direction=direction,
            include_synthetic=include_synthetic,
            prefer_runtime=True,
        )
        return [conversation_spine_turn_to_monitor_json(item) for item in records]

    def messages(
        self,
        limit: int = 30,
        sender: Optional[str] = None,
        recipient: Optional[str] = None,
        status: Optional[str] = None,
        thread_id: Optional[str] = None,
        initiated: bool = False,
        personal: bool = False,
    ) -> list[Dict[str, object]]:
        messages = eve.read_messages(
            limit=None if initiated or personal else limit,
            sender=sender,
            recipient=recipient,
            status=status,
            thread_id=thread_id,
        )
        if initiated:
            messages = [
                item
                for item in messages
                if item.get("sender") == "eve"
                and item.get("recipient") == "user"
                and (
                    not item.get("reply_to")
                    or str(item.get("kind") or "") == "proactive_outreach"
                    or "update" in str(item.get("kind") or "")
                    or "outreach" in str(item.get("kind") or "")
                )
            ]
        if personal:
            messages = [
                item
                for item in messages
                if eve.message_is_personal_conversation(item)
            ]
        if initiated or personal:
            messages = messages[-limit:]
        return [message_to_json(item) for item in messages]

    def personal_conversation_status(self) -> Dict[str, object]:
        return eve.personal_conversation_status_payload()

    def eve_app_snapshot(self) -> Dict[str, object]:
        """Return the bounded read model Eve.app needs for one refresh.

        This composes existing read-only service contracts. It does not create
        a second source of truth, mark messages or follow-ups as seen, or infer
        state that the underlying ledgers do not expose.
        """
        return {
            "schema": EVE_APP_SNAPSHOT_SCHEMA,
            "api_version": API_VERSION,
            "generated_at": eve.utc_now(),
            "personal_messages": self.messages(
                limit=30,
                sender="eve",
                recipient="user",
                personal=True,
            ),
            "thoughts": self.thoughts(limit=24),
            "activity": self.activity(limit=50),
            "reflections": self.reflections(limit=5),
            "personal_status": self.personal_conversation_status(),
            "followups": self.eve_chat_followups(
                status="delivered,failed",
                surface="eve_chat_ui",
                include_seen=False,
                limit=12,
            ),
        }

    def open_message(self, message_id: str) -> Dict[str, object]:
        _, message = self._find_message(message_id)
        if message.get("recipient") == "user" and message.get("status") == "unread":
            def operation() -> Dict[str, object]:
                return message_to_json(eve.update_message_record(message_id, status="read"))

            return self._run_mutation(operation)
        return message_to_json(message)

    def thread_messages(self, thread_id: str) -> list[Dict[str, object]]:
        messages = eve.read_messages(thread_id=thread_id)
        return [message_to_json(item) for item in messages]

    def proposals(self, limit: int = 20, status: Optional[str] = None) -> list[Dict[str, object]]:
        proposals = eve.read_proposals(limit=limit, status=status)
        return [proposal_to_json(item) for item in proposals]

    def governance(self, limit: int = 20, runtime: bool = True) -> Dict[str, object]:
        return eve.governance_status_payload(limit=limit, prefer_runtime=runtime)

    def reflections(self, limit: int = 10) -> list[Dict[str, object]]:
        return [entry_to_json(item) for item in eve.read_entries_by_kind("reflection", limit=limit)]

    def thoughts(self, limit: int = 10) -> list[Dict[str, object]]:
        return [entry_to_json(item) for item in eve.read_entries_by_kind("thought", limit=limit)]

    def tensions(self, limit: int = 10, status: Optional[str] = None) -> list[Dict[str, object]]:
        return [tension_to_json(item) for item in eve.read_tensions(limit=limit, status=status)]

    def experiments(self, limit: int = 10, status: Optional[str] = None) -> list[Dict[str, object]]:
        return [experiment_to_json(item) for item in eve.read_experiments(limit=limit, status=status)]

    def evaluations(
        self,
        limit: int = 20,
        target_kind: Optional[str] = None,
        target_id: Optional[str] = None,
        evaluator: Optional[str] = None,
        thread_id: Optional[str] = None,
        since_days: Optional[int] = None,
    ) -> list[Dict[str, object]]:
        evaluations = eve.read_evaluations(
            limit=limit,
            target_kind=target_kind,
            target_id=target_id,
            evaluator=evaluator,
            thread_id=thread_id,
            since_days=since_days,
        )
        return [evaluation_to_json(item) for item in evaluations]

    def outcomes(
        self,
        limit: int = 20,
        target_kind: Optional[str] = None,
        target_id: Optional[str] = None,
        direction: Optional[str] = None,
        thread_id: Optional[str] = None,
        since_days: Optional[int] = None,
    ) -> list[Dict[str, object]]:
        outcomes = eve.read_outcomes(
            limit=limit,
            target_kind=target_kind,
            target_id=target_id,
            direction=direction,
            thread_id=thread_id,
            since_days=since_days,
        )
        return [outcome_to_json(item) for item in outcomes]

    def failure_clusters(self, limit: int = 20, status: Optional[str] = None, since_days: Optional[int] = None) -> list[Dict[str, object]]:
        clusters = eve.read_failure_clusters(limit=limit, status=status, since_days=since_days)
        return [failure_cluster_to_json(item) for item in clusters]

    def activity(self, limit: int = 20) -> list[Dict[str, object]]:
        return [entry_to_json(item) for item in self.activity_entries(limit=limit)]

    def monitor_status_payload(self) -> Dict[str, object]:
        return build_monitor_status_payload(
            self.latest_state(),
            api_version=API_VERSION,
        )

    def monitor_payload(self, compact: bool = False) -> Dict[str, object]:
        status = self.monitor_status_payload()
        model_health = status.get("model_health") if isinstance(status.get("model_health"), dict) else None
        activity = self.activity_payload(model_health)
        return build_monitor_payload(
            status=status,
            activity=activity,
            conversation_spine=self.conversation_spine,
            compact=compact,
        )

    def ask(
        self,
        body: str,
        subject: str = "Question from user",
        client_request_id: Optional[str] = None,
        attachments: Optional[list[Dict[str, object]]] = None,
        config_overrides: Optional[Dict[str, object]] = None,
        message_metadata: Optional[Dict[str, object]] = None,
        thread_id: Optional[str] = None,
    ) -> Dict[str, object]:
        body = eve_http_json.require_text_value(
            body,
            label="Message body",
            maximum_characters=MAX_CONVERSATION_BODY_CHARACTERS,
            multiline=True,
        )
        subject = eve_http_json.require_text_value(
            subject,
            label="Message subject",
            maximum_characters=MAX_CONVERSATION_SUBJECT_CHARACTERS,
        ) or "Question from user"
        client_request_id = eve_http_json.require_text_value(
            client_request_id,
            label="client_request_id",
            maximum_characters=MAX_CLIENT_REQUEST_ID_CHARACTERS,
        ) or None
        thread_id = eve_http_json.require_text_value(
            thread_id,
            label="thread_id",
            maximum_characters=512,
        ) or None
        raw_attachments = eve_http_json.object_list_value(
            attachments,
            label="attachments",
            maximum_items=eve_attachments.MAX_ATTACHMENTS_PER_MESSAGE,
        )
        if not body and raw_attachments:
            body = "Please inspect the attached file{}.".format("" if len(raw_attachments) == 1 else "s")
        if not body:
            raise ValueError("Message body is required")

        def operation() -> Dict[str, object]:
            config = eve.load_config()
            if config_overrides:
                config = dict(config)
                config.update(config_overrides)
            user_message = eve.create_message(
                sender="user",
                recipient="eve",
                subject=subject,
                body=body,
                kind="user_message",
                thread_id=thread_id,
                status="sent",
                metadata=message_metadata or {},
            )
            attachment_records = record_attachments_for_message(
                raw_attachments,
                user_message,
                client_request_id=client_request_id,
            )
            if attachment_records:
                user_message = eve.update_message_record(
                    str(user_message["id"]),
                    body=message_body_with_attachment_evidence(body, attachment_records),
                    metadata=attachment_metadata(attachment_records),
                )
            reply = eve.generate_eve_reply(config, user_message, client_request_id=client_request_id)
            thread = eve.read_messages(thread_id=str(user_message["thread_id"]))
            return {
                "thread_id": user_message["thread_id"],
                "reply": message_to_json(reply),
                "messages": [message_to_json(item) for item in thread],
            }

        return self._run_mutation(operation)

    def initiate_personal_message(self, allow_none: bool = False, notify: bool = True) -> Dict[str, object]:
        if not isinstance(allow_none, bool) or not isinstance(notify, bool):
            raise ValueError("allow_none and notify must be Booleans")

        def operation() -> Dict[str, object]:
            config = eve.load_config()
            record = eve.create_eve_outreach_message(
                config,
                source="monitor_personal",
                notify=notify,
                allow_none=allow_none,
            )
            if record is None:
                return {
                    "thread_id": None,
                    "reply": None,
                    "messages": [],
                }
            thread = eve.read_messages(thread_id=str(record["thread_id"]))
            return {
                "thread_id": record["thread_id"],
                "reply": message_to_json(record),
                "messages": [message_to_json(item) for item in thread],
            }

        return self._run_mutation(operation)

    def reply(
        self,
        message_id: str,
        body: str,
        subject: Optional[str] = None,
        client_request_id: Optional[str] = None,
        attachments: Optional[list[Dict[str, object]]] = None,
    ) -> Dict[str, object]:
        message_id = eve_http_json.require_text_value(
            message_id,
            label="message_id",
            maximum_characters=512,
            required=True,
        )
        body = eve_http_json.require_text_value(
            body,
            label="Message body",
            maximum_characters=MAX_CONVERSATION_BODY_CHARACTERS,
            multiline=True,
        )
        normalized_subject = eve_http_json.require_text_value(
            subject,
            label="Message subject",
            maximum_characters=MAX_CONVERSATION_SUBJECT_CHARACTERS,
        ) or None
        client_request_id = eve_http_json.require_text_value(
            client_request_id,
            label="client_request_id",
            maximum_characters=MAX_CLIENT_REQUEST_ID_CHARACTERS,
        ) or None
        raw_attachments = eve_http_json.object_list_value(
            attachments,
            label="attachments",
            maximum_items=eve_attachments.MAX_ATTACHMENTS_PER_MESSAGE,
        )
        if not body and raw_attachments:
            body = "Please inspect the attached file{}.".format("" if len(raw_attachments) == 1 else "s")
        if not body:
            raise ValueError("message_id and body are required")

        def operation() -> Dict[str, object]:
            _, target = self._find_message(message_id)
            config = eve.load_config()
            reply_subject = eve_http_json.require_text_value(
                normalized_subject or f"Re: {target.get('subject') or 'Conversation'}",
                label="Message subject",
                maximum_characters=MAX_CONVERSATION_SUBJECT_CHARACTERS,
                required=True,
            )
            user_message = eve.create_message(
                sender="user",
                recipient="eve",
                subject=reply_subject,
                body=body,
                kind="user_reply",
                thread_id=str(target["thread_id"]),
                reply_to=str(target["id"]),
                status="sent",
            )
            attachment_records = record_attachments_for_message(
                raw_attachments,
                user_message,
                client_request_id=client_request_id,
            )
            if attachment_records:
                user_message = eve.update_message_record(
                    str(user_message["id"]),
                    body=message_body_with_attachment_evidence(body, attachment_records),
                    metadata=attachment_metadata(attachment_records),
                )
            reply = eve.generate_eve_reply(config, user_message, client_request_id=client_request_id)
            thread = eve.read_messages(thread_id=str(target["thread_id"]))
            return {
                "thread_id": target["thread_id"],
                "reply": message_to_json(reply),
                "messages": [message_to_json(item) for item in thread],
            }

        return self._run_mutation(operation)

    def attachments(
        self,
        thread_id: Optional[str] = None,
        message_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[Dict[str, object]]:
        return read_attachment_records(thread_id=thread_id, message_id=message_id, limit=limit)

    def upload_attachment(self, payload: Dict[str, object]) -> Dict[str, object]:
        return upload_attachment_from_json(payload)

    def openai_models(self) -> Dict[str, object]:
        return {
            "object": "list",
            "data": [openai_model_record()],
        }

    def openai_model(self, model_id: str) -> Dict[str, object]:
        model_id = str(model_id or "").strip() or OPENAI_COMPAT_MODEL_ID
        if model_id not in OPENAI_COMPAT_MODEL_ALIASES:
            raise LookupError(f"Unknown Eve Chat model: {model_id}")
        return openai_model_record(OPENAI_COMPAT_MODEL_ID)

    def eve_chat_followups(
        self,
        *,
        status: Optional[str] = None,
        surface: Optional[str] = None,
        include_seen: bool = False,
        limit: int = 50,
    ) -> Dict[str, object]:
        return self._eve_chat_followup_service.eve_chat_followups(
            status=status,
            surface=surface,
            include_seen=include_seen,
            limit=limit,
        )

    def mark_eve_chat_followup_seen(self, followup_id: str) -> Dict[str, object]:
        return self._eve_chat_followup_service.mark_eve_chat_followup_seen(followup_id)

    def queue_eve_chat_followup(
        self,
        *,
        messages: list[Dict[str, str]],
        result: Dict[str, object],
        client_request_id: str,
        transport: Dict[str, str],
        evaluation_metadata: Optional[Dict[str, object]] = None,
    ) -> Dict[str, object]:
        return self._eve_chat_followup_service.queue_eve_chat_followup(
            messages=messages,
            result=result,
            client_request_id=client_request_id,
            transport=transport,
            evaluation_metadata=evaluation_metadata,
        )

    def start_eve_chat_followup_worker(self, followup_id: str) -> None:
        self._eve_chat_followup_service.start_eve_chat_followup_worker(followup_id)

    def resume_eve_chat_followups(self) -> Dict[str, object]:
        return self._eve_chat_followup_service.resume_eve_chat_followups()

    def _existing_eve_chat_followup_delivery(
        self,
        followup_id: str,
        thread_id: str,
    ) -> Dict[str, object]:
        return self._eve_chat_followup_service._existing_eve_chat_followup_delivery(
            followup_id,
            thread_id,
        )

    def _complete_eve_chat_followup_cycle(
        self,
        *,
        record: Dict[str, object],
        action: str,
        result: Dict[str, object],
        delivery_message_id: str,
        opened_state: Dict[str, object],
    ) -> Dict[str, object]:
        return self._eve_chat_followup_service._complete_eve_chat_followup_cycle(
            record=record,
            action=action,
            result=result,
            delivery_message_id=delivery_message_id,
            opened_state=opened_state,
        )

    def run_eve_chat_followup_worker(self, followup_id: str) -> None:
        self._eve_chat_followup_service.run_eve_chat_followup_worker(followup_id)

    def openai_chat_completion(self, payload: Dict[str, object]) -> Dict[str, object]:
        requested_model = normalize_openai_identifier(
            payload.get("model"),
            label="model",
            maximum_characters=80,
        ) or OPENAI_COMPAT_MODEL_ID
        if requested_model not in OPENAI_COMPAT_MODEL_ALIASES:
            raise ValueError(f"Unsupported Eve Chat model: {requested_model}")
        messages = normalize_openai_chat_messages(payload.get("messages"))
        exact_literal_reply = openai_compat_exact_literal_reply(messages)
        if exact_literal_reply is not None:
            return openai_chat_completion_payload(
                exact_literal_reply,
                model_id=OPENAI_COMPAT_MODEL_ID,
                prompt_text=latest_openai_user_content(messages),
                extra_eve={
                    "exact_literal_reply": True,
                    "conversation_recorded": False,
                },
            )
        auxiliary_reply = openai_compat_auxiliary_ui_reply(messages)
        if auxiliary_reply:
            auxiliary_prompt = latest_openai_user_content(messages)
            return openai_chat_completion_payload(
                auxiliary_reply["body"],
                model_id=OPENAI_COMPAT_MODEL_ID,
                prompt_text=auxiliary_prompt,
                extra_eve={
                    "auxiliary_ui_task": auxiliary_reply["kind"],
                    "conversation_recorded": False,
                },
            )
        transport = openai_chat_transport_metadata(payload)
        evaluation_metadata = openai_chat_evaluation_metadata(payload)
        followup_requested = eve_chat_followup_requested(messages)
        should_queue_followup = bool(
            followup_requested and not evaluation_metadata.get("synthetic")
        )
        thread_id = openai_chat_thread_id(transport)
        eve_body = openai_messages_to_eve_body(messages)
        client_request_id = normalize_openai_identifier(
            first_transport_value(
                payload.get("user"),
                payload.get("client_request_id"),
                payload.get("id"),
                transport.get("openwebui_assistant_message_id"),
                transport.get("openwebui_user_message_id"),
            ),
            label="client request id",
        )
        if not client_request_id:
            client_request_id = f"eve-chat-{uuid.uuid4().hex}"
        result = self.ask(
            eve_body,
            subject="Eve Chat conversation",
            client_request_id=client_request_id,
            config_overrides=OPENAI_COMPAT_REPLY_CONFIG_OVERRIDES,
            message_metadata={
                **eve.self_operational_message_metadata(
                    direction="eve_chat_ui_to_eve",
                    surface="eve_chat_ui",
                    authority="ui_adapter_only",
                    openwebui_chat_id=transport.get("openwebui_chat_id", ""),
                    openwebui_thread_id=thread_id or "",
                ),
                **evaluation_metadata,
            },
            thread_id=thread_id,
        )
        followup: Optional[Dict[str, object]] = None
        if should_queue_followup:
            followup = self.queue_eve_chat_followup(
                messages=messages,
                result=result,
                client_request_id=client_request_id,
                transport=transport,
                evaluation_metadata=evaluation_metadata,
            )
        reply = result.get("reply") if isinstance(result.get("reply"), dict) else {}
        reply_text = str(reply.get("body") or "")
        extra_eve: Dict[str, object] = {}
        if followup:
            reply_text = str(followup.get("ack_text") or reply_text)
            extra_eve = {
                "eve_chat_followup_queued": True,
                "eve_chat_followup_id": str(followup.get("id") or ""),
                "eve_chat_followup_action": str(followup.get("requested_action") or ""),
                "eve_chat_followup_delivery": "polling_api",
            }
        elif followup_requested and evaluation_metadata.get("synthetic"):
            extra_eve = {
                "eve_chat_followup_queued": False,
                "eve_chat_followup_suppressed": "synthetic_evaluator_isolation",
            }
        return openai_chat_completion_payload(
            reply_text,
            model_id=OPENAI_COMPAT_MODEL_ID,
            prompt_text=eve_body,
            thread_id=str(result.get("thread_id") or ""),
            reply_message_id=str(reply.get("id") or ""),
            extra_eve=extra_eve,
        )

    def mark_message(self, message_id: str, status: str) -> Dict[str, object]:
        message_id = eve_http_json.require_text_value(
            message_id,
            label="message_id",
            maximum_characters=512,
            required=True,
        )
        status = eve_http_json.require_text_value(
            status,
            label="Message status",
            maximum_characters=64,
            required=True,
        )
        if status not in {"unread", "read", "archived", "sent"}:
            raise ValueError("Invalid message status")

        def operation() -> Dict[str, object]:
            try:
                message = eve.update_message_record(message_id, status=status)
            except SystemExit as exc:
                raise LookupError(str(exc)) from exc
            return message_to_json(message)

        return self._run_mutation(operation)

    def update_proposal_status(self, proposal_id: str, status: str) -> Dict[str, object]:
        proposal_id = eve_http_json.require_text_value(
            proposal_id,
            label="proposal_id",
            maximum_characters=512,
            required=True,
        )
        status = eve_http_json.require_text_value(
            status,
            label="Proposal status",
            maximum_characters=64,
            required=True,
        )
        if status not in {"draft", "approved", "rejected", "applied", "archived"}:
            raise ValueError("Invalid proposal status")

        def operation() -> Dict[str, object]:
            try:
                proposal = eve.update_proposal_record(proposal_id, status=status)
            except SystemExit as exc:
                raise LookupError(str(exc)) from exc
            eve.append_entry(
                "proposal_updated",
                f"{proposal['title']} -> {proposal['status']}",
                metadata={"proposal_id": proposal["id"], "status": proposal["status"], "source": "web"},
            )
            return proposal_to_json(proposal)

        return self._run_mutation(operation)

    def think(self) -> Dict[str, object]:
        def operation() -> Dict[str, object]:
            config = eve.load_config()
            result = eve.generate_continuous_thought(
                config,
                context_limit=int(config["thought_context_limit"]),
                thought_history_limit=int(config["thought_history_limit"]),
                max_tokens=int(config["thought_max_tokens"]),
            )
            entry = eve.append_entry(
                "thought",
                str(result["response"]),
                metadata={
                    "model": result["model"],
                    "source_entries": result["source_entries"],
                    "source_thoughts": result["source_thoughts"],
                    "source_threads": result["source_threads"],
                    "source_messages": result["source_messages"],
                    "source": "web",
                },
            )
            state = eve.load_state()
            state["last_thought_at"] = eve.utc_now()
            state["current_focus"] = " ".join(str(result["response"]).split())[:160]
            eve.save_state(state)
            return {"thought": entry_to_json(entry)}

        return self._run_mutation(operation)

    def reflect(self) -> Dict[str, object]:
        def operation() -> Dict[str, object]:
            config = eve.load_config()
            result = eve.generate_reflection(
                config,
                days=int(config["reflection_days"]),
                context_limit=int(config["reflection_context_limit"]),
                max_tokens=int(config["reflection_max_tokens"]),
            )
            entry = eve.append_entry(
                "reflection",
                str(result["response"]),
                metadata={"days": int(config["reflection_days"]), "model": result["model"], "source": "web"},
            )
            return {"reflection": entry_to_json(entry)}

        try:
            return self._run_mutation(operation)
        except SystemExit as exc:
            raise ValueError(str(exc)) from exc

    def suggest_proposal(self) -> Dict[str, object]:
        def operation() -> Dict[str, object]:
            config = eve.load_config()
            proposal = eve.suggest_proposal(
                config,
                source="web",
                max_tokens=int(config["proposal_max_tokens"]),
            )
            return proposal_to_json(proposal)

        try:
            return self._run_mutation(operation)
        except SystemExit as exc:
            raise ValueError(str(exc)) from exc

    def capture(self, kind: str, text: str, raw_tags: object) -> Dict[str, object]:
        kind = eve_http_json.require_text_value(
            kind,
            label="Capture kind",
            maximum_characters=64,
        ) or "note"
        text = eve_http_json.require_text_value(
            text,
            label="Capture text",
            maximum_characters=MAX_CONVERSATION_BODY_CHARACTERS,
            required=True,
            multiline=True,
        )
        if kind not in CAPTURE_KINDS:
            raise ValueError("Invalid capture kind")
        tags = eve_http_json.string_list_value(
            raw_tags,
            label="tags",
            maximum_items=MAX_CAPTURE_TAGS,
            maximum_item_characters=64,
            allow_space_separated_string=True,
        )

        def operation() -> Dict[str, object]:
            entry = eve.append_entry(kind, text, tags=tags, metadata={"source": "web"})
            return {"entry": entry_to_json(entry)}

        return self._run_mutation(operation)

    def daemon_start(self) -> Dict[str, object]:
        def operation() -> Dict[str, object]:
            eve.start_launch_agent()
            return self.latest_state(force=True)

        try:
            return self._run_mutation(operation)
        except SystemExit as exc:
            raise ValueError(str(exc)) from exc

    def daemon_stop(self) -> Dict[str, object]:
        def operation() -> Dict[str, object]:
            eve.stop_launch_agent()
            return self.latest_state(force=True)

        try:
            return self._run_mutation(operation)
        except SystemExit as exc:
            raise ValueError(str(exc)) from exc


_DEFAULT_SERVICE: Optional[EveRuntimeService] = None
_DEFAULT_SERVICE_LOCK = threading.Lock()


def get_runtime_service() -> EveRuntimeService:
    global _DEFAULT_SERVICE
    with _DEFAULT_SERVICE_LOCK:
        if _DEFAULT_SERVICE is None:
            _DEFAULT_SERVICE = EveRuntimeService()
        return _DEFAULT_SERVICE


def ordered_thread_summaries(limit: Optional[int] = None, status: Optional[str] = None) -> list[Dict[str, object]]:
    return get_runtime_service().ordered_thread_summaries(limit=limit, status=status)


def model_health_payload(limit: int = 5) -> Dict[str, object]:
    return get_runtime_service().model_health_payload(limit=limit)


def latest_state() -> Dict[str, object]:
    return get_runtime_service().latest_state()


def activity_entries(limit: int) -> list[Dict[str, object]]:
    return get_runtime_service().activity_entries(limit=limit)


def wake_eve_if_needed() -> Dict[str, object]:
    return get_runtime_service().wake_eve_if_needed()


class EveHTTPServer(eve_http_server.EveBoundedThreadingHTTPServer):
    internal_error_surface = "eve-runtime"

    def __init__(
        self,
        server_address: tuple[str, int],
        request_handler_class: type[BaseHTTPRequestHandler],
        *,
        service: Optional[EveRuntimeService] = None,
        static_dir: Path = WEB_DIR,
        advertised_host: Optional[str] = None,
        bind_and_activate: bool = True,
    ):
        self.service = service or get_runtime_service()
        self.static_dir = static_dir
        self.advertised_host = eve_http_security.advertised_host_for_bind(
            server_address[0],
            advertised_host,
        )
        super().__init__(server_address, request_handler_class, bind_and_activate=bind_and_activate)
        if not bind_and_activate:
            self.server_name = server_address[0]
            self.server_port = server_address[1]

    def handle_error(self, request, client_address) -> None:
        exc_type, _, _ = sys.exc_info()
        if exc_type in {BrokenPipeError, ConnectionResetError, ConnectionAbortedError}:
            return
        super().handle_error(request, client_address)


class EveAppHandler(eve_http_server.EveBoundedHTTPRequestHandler):
    server_version = "EveWeb/3.0"

    @property
    def service(self) -> EveRuntimeService:
        return self.server.service  # type: ignore[attr-defined]

    @property
    def static_dir(self) -> Path:
        return self.server.static_dir  # type: ignore[attr-defined]

    def advertised_endpoint(self) -> tuple[str, int]:
        return trusted_installer_endpoint(
            self.server.advertised_host,  # type: ignore[attr-defined]
            self.server.server_port,
        )

    def do_GET(self) -> None:
        try:
            self._do_get()
        except LookupError as exc:
            self.send_exception_json(HTTPStatus.NOT_FOUND, str(exc))
        except ValueError as exc:
            self.send_exception_json(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            error_id = self.record_internal_error(exc, operation="GET")
            self.send_exception_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "Eve could not complete this request.",
                error_type="server_error",
                error_id=error_id,
            )

    def _do_get(self) -> None:
        target = eve_http_path.parse_request_target(self.path)
        path = target.path
        query = eve_http_query.BoundedQuery.parse(target.query)
        openai_model_id = eve_http_path.match_route_segment(
            path,
            prefix="/v1/models/",
            label="Model id",
            maximum_characters=128,
        )
        message_id = eve_http_path.match_route_segment(
            path,
            prefix="/api/messages/",
            label="Message id",
        )
        thread_id = eve_http_path.match_route_segment(
            path,
            prefix="/api/thread/",
            label="Thread id",
        )
        if path == "/v1/models":
            return self.handle_get_openai_models()
        if openai_model_id is not None:
            return self.handle_get_openai_model(openai_model_id)
        if path == "/":
            return self.serve_static("index.html", "text/html; charset=utf-8")
        if path == "/monitor":
            return self.serve_static("monitor.html", "text/html; charset=utf-8")
        if path == "/install":
            return self.handle_get_install_page()
        if path == "/install/windows":
            return self.handle_get_windows_install_page()
        if path == "/app.js":
            return self.serve_static("app.js", "application/javascript; charset=utf-8")
        if path == "/styles.css":
            return self.serve_static("styles.css", "text/css; charset=utf-8")
        if path == "/monitor.js":
            return self.serve_static("monitor.js", "application/javascript; charset=utf-8")
        if path == "/monitor.css":
            return self.serve_static("monitor.css", "text/css; charset=utf-8")
        if path == "/downloads/EveSetup.exe":
            return self.handle_get_windows_installer_exe()
        if path in {"/downloads/EveMacInstaller.zip", f"/downloads/{MAC_INSTALLER_FILENAME}"}:
            return self.handle_get_macos_installer_app_bundle()
        if path == "/downloads/EveWindowsAppPackage.zip":
            return self.handle_get_windows_app_package_download()
        if path == "/downloads/EveMacSetup.zip":
            return self.handle_get_macos_installer_bundle()
        if path == "/downloads/EveLinuxSetup.tar.gz":
            return self.handle_get_linux_installer_bundle()
        if path == "/downloads/install_windows_eve.cmd":
            return self.handle_get_windows_launcher("install_windows_eve.cmd")
        if path == "/downloads/update_windows_eve.cmd":
            return self.handle_get_windows_launcher("update_windows_eve.cmd")
        if path == "/downloads/install_windows_eve.ps1":
            return self.handle_get_windows_script("install_windows_eve.ps1")
        if path == "/downloads/update_windows_eve.ps1":
            return self.handle_get_windows_script("update_windows_eve.ps1")
        if path == "/downloads/bootstrap_bundle.json":
            return self.handle_get_bootstrap_download()
        if path == "/downloads/code-bundle.zip":
            return self.handle_get_code_bundle_download()
        if path == "/api/code-bundle":
            return self.handle_get_code_bundle()
        if path == "/api/windows-app-package":
            return self.handle_get_windows_app_package()
        if path == "/api/update-manifest":
            return self.handle_get_update_manifest(query)
        if path == "/api/bootstrap":
            return self.handle_get_bootstrap(query)
        if path == "/api/status":
            return self.send_json({"ok": True, "data": self.service.latest_state()})
        if path == "/api/monitor":
            compact = query.boolean("compact", default=False)
            return self.send_json({"ok": True, "data": self.service.monitor_payload(compact=compact)})
        if path == "/api/monitor/stream":
            return self.handle_get_monitor_stream(query)
        if path == "/api/reply-progress":
            return self.handle_get_reply_progress(query)
        if path == "/api/reply-turns":
            return self.handle_get_reply_turns(query)
        if path == "/api/reply-council-turns":
            return self.handle_get_reply_council_turns(query)
        if path == "/api/attachments":
            return self.handle_get_attachments(query)
        if path == "/api/conversation-spine":
            return self.handle_get_conversation_spine(query)
        if path == "/api/threads":
            return self.handle_get_threads(query)
        if path == "/api/messages":
            return self.handle_get_messages(query)
        if path == "/api/eve-app/snapshot":
            return self.send_json({"ok": True, "data": self.service.eve_app_snapshot()})
        if path == "/api/personal-conversation/status":
            return self.send_json({"ok": True, "data": self.service.personal_conversation_status()})
        if message_id is not None:
            return self.handle_get_message(message_id)
        if thread_id is not None:
            return self.handle_get_thread(thread_id)
        if path == "/api/proposals":
            return self.handle_get_proposals(query)
        if path == "/api/governance":
            return self.handle_get_governance(query)
        if path == "/api/thoughts":
            return self.handle_get_thoughts(query)
        if path == "/api/reflections":
            return self.handle_get_reflections(query)
        if path == "/api/tensions":
            return self.handle_get_tensions(query)
        if path == "/api/experiments":
            return self.handle_get_experiments(query)
        if path == "/api/evaluations":
            return self.handle_get_evaluations(query)
        if path == "/api/outcomes":
            return self.handle_get_outcomes(query)
        if path == "/api/failure-clusters":
            return self.handle_get_failure_clusters(query)
        if path == "/api/model-health":
            return self.handle_get_model_health(query)
        if path == "/api/activity":
            return self.handle_get_activity(query)
        if path == "/api/eve-chat/followups":
            return self.handle_get_eve_chat_followups(query)
        if path == "/api/sensory/status":
            return self.send_json({"ok": True, "data": self.service.sensory_status()})
        self.send_error_json(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        try:
            self._do_post()
        except LookupError as exc:
            self.send_exception_json(HTTPStatus.NOT_FOUND, str(exc))
        except ValueError as exc:
            self.send_exception_json(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            error_id = self.record_internal_error(exc, operation="POST")
            self.send_exception_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "Eve could not complete this request.",
                error_type="server_error",
                error_id=error_id,
            )

    def do_OPTIONS(self) -> None:
        try:
            target = eve_http_path.parse_request_target(self.path)
            eve_http_query.BoundedQuery.parse(target.query)
            requested_origin = eve_http_headers.optional_ascii_header(
                self.headers,
                "Origin",
                maximum_characters=512,
            )
        except ValueError as exc:
            self.close_connection = True
            self.send_exception_json(HTTPStatus.BAD_REQUEST, str(exc))
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_cors_headers(origin=requested_origin)
        self.send_eve_private_response_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def _do_post(self) -> None:
        try:
            target = eve_http_path.parse_request_target(self.path)
            path = target.path
            eve_http_query.BoundedQuery.parse(target.query)
            message_id = eve_http_path.match_route_segment(
                path,
                prefix="/api/messages/",
                suffix="/mark",
                label="Message id",
            )
            proposal_id = eve_http_path.match_route_segment(
                path,
                prefix="/api/proposals/",
                suffix="/status",
                label="Proposal id",
            )
            followup_id = eve_http_path.match_route_segment(
                path,
                prefix="/api/eve-chat/followups/",
                suffix="/seen",
                label="Follow-up id",
            )
        except ValueError:
            # A rejected route/query still has an unread body. Do not let it
            # become a second request on this persistent connection.
            self.close_connection = True
            raise
        if not self.enforce_json_mutation_request():
            return
        if path == "/v1/chat/completions":
            return self.handle_post_openai_chat_completions()
        if path in {"/api/eve-chat/ag-ui", "/api/copilotkit/ag-ui"}:
            return self.handle_post_copilotkit_agui()
        if path == "/api/attachments/upload":
            return self.handle_post_attachment_upload()
        if path == "/api/message/ask":
            return self.handle_post_ask()
        if path == "/api/message/initiate":
            return self.handle_post_initiate()
        if path == "/api/message/reply":
            return self.handle_post_reply()
        if message_id is not None:
            return self.handle_post_mark_message(message_id)
        if proposal_id is not None:
            return self.handle_post_proposal_status(proposal_id)
        if path == "/api/actions/think":
            return self.handle_post_think()
        if path == "/api/actions/wake":
            return self.handle_post_wake()
        if path == "/api/actions/reflect":
            return self.handle_post_reflect()
        if path == "/api/actions/proposal":
            return self.handle_post_suggest_proposal()
        if path == "/api/capture":
            return self.handle_post_capture()
        if path == "/api/daemon/start":
            return self.handle_post_daemon_start()
        if path == "/api/daemon/stop":
            return self.handle_post_daemon_stop()
        if followup_id is not None:
            return self.handle_post_eve_chat_followup_seen(followup_id)
        if path == "/api/sensory/session":
            origin = canonical_eve_chat_local_origin(
                getattr(self, "_validated_mutation_origin", "")
            )
            if not origin:
                return self.send_error_json(
                    HTTPStatus.FORBIDDEN,
                    "Sensory control is restricted to the local Eve app origin.",
                )
            payload = self.read_json_body(maximum_bytes=SENSORY_REQUEST_MAX_BYTES)
            action = str(payload.get("action") or "start").strip().lower()
            if action == "start":
                return self.send_json({"ok": True, "data": self.service.start_sensory_session(payload)})
            if action == "stop":
                return self.send_json({"ok": True, "data": self.service.stop_sensory_session(payload)})
            raise ValueError("sensory session action must be start or stop")
        if path == "/api/sensory/events":
            origin = canonical_eve_chat_local_origin(
                getattr(self, "_validated_mutation_origin", "")
            )
            if not origin:
                return self.send_error_json(
                    HTTPStatus.FORBIDDEN,
                    "Sensory control is restricted to the local Eve app origin.",
                )
            payload = self.read_json_body(maximum_bytes=SENSORY_REQUEST_MAX_BYTES)
            return self.send_json({"ok": True, "data": self.service.ingest_sensory_events(payload)})
        self.close_connection = True
        self.send_error_json(HTTPStatus.NOT_FOUND, "Not found")

    def enforce_json_mutation_request(self) -> bool:
        server_port = int(getattr(self.server, "server_port", self.server.server_address[1]))
        try:
            origin = eve_http_headers.optional_ascii_header(
                self.headers,
                "Origin",
                maximum_characters=512,
            )
            sec_fetch_site = eve_http_headers.optional_ascii_header(
                self.headers,
                "Sec-Fetch-Site",
                maximum_characters=32,
            )
            content_type = eve_http_headers.optional_ascii_header(
                self.headers,
                "Content-Type",
                maximum_characters=256,
            )
        except eve_http_headers.RequestHeaderError as exc:
            self.close_connection = True
            self.send_exception_json(HTTPStatus.BAD_REQUEST, str(exc))
            return False
        decision = eve_http_security.evaluate_json_mutation_request(
            origin=origin,
            sec_fetch_site=sec_fetch_site,
            content_type=content_type,
            server_port=server_port,
            extra_origins=EVE_CHAT_FOLLOWUP_POLL_ORIGINS,
        )
        if decision.allowed:
            self._validated_mutation_origin = origin
            return True
        # Do not consume an untrusted body. Closing prevents unread bytes from
        # becoming a second request on a persistent HTTP/1.1 connection.
        self.close_connection = True
        self.send_exception_json(
            HTTPStatus(decision.status),
            decision.message,
            error_type="invalid_request_error",
        )
        return False

    def log_message(self, format: str, *args: object) -> None:
        return

    def record_internal_error(self, error: BaseException, *, operation: str) -> str:
        return eve_http_server.record_http_internal_error(
            error,
            surface="eve-runtime",
            operation=operation,
        )

    def serve_static(self, filename: str, content_type: str) -> None:
        path = self.static_dir / filename
        if not path.exists():
            self.send_error_json(HTTPStatus.NOT_FOUND, f"Missing asset: {filename}")
            return
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_cors_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_eve_document_security_headers(allow_sensory=False)
        self.end_headers()
        self.wfile.write(data)

    def read_json_body(
        self,
        *,
        maximum_bytes: int = MAX_JSON_REQUEST_BYTES,
    ) -> Dict[str, object]:
        try:
            raw = eve_http_body.read_bounded_request_body(
                self.rfile,
                self.headers,
                maximum_bytes=maximum_bytes,
                allow_empty=True,
            )
        except eve_http_body.RequestBodyFramingError:
            # A rejected framing boundary may leave bytes unread. Never let
            # them become another request on this HTTP/1.1 connection.
            self.close_connection = True
            raise
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise ValueError("Invalid JSON body") from exc
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def send_json(self, payload: Dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json_bytes(payload)
        self.send_response(status)
        self.send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_eve_private_response_headers()
        self.end_headers()
        self.wfile.write(data)

    def send_bytes(self, payload: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_cors_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_eve_private_response_headers()
        self.end_headers()
        self.wfile.write(payload)

    def send_download(self, payload: bytes, content_type: str, filename: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_cors_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_eve_private_response_headers()
        self.end_headers()
        self.wfile.write(payload)

    def send_cors_headers(self, *, origin: Optional[str] = None) -> None:
        if origin is None:
            try:
                origin = eve_http_headers.optional_ascii_header(
                    self.headers,
                    "Origin",
                    maximum_characters=512,
                )
            except eve_http_headers.RequestHeaderError:
                return
        canonical_origin = canonical_eve_chat_local_origin(origin)
        if canonical_origin:
            self.send_header("Access-Control-Allow-Origin", canonical_origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.send_header("Vary", "Origin")

    def openai_chat_transport_headers(
        self,
        *,
        fallback_chat_id: object = "",
    ) -> Dict[str, str]:
        chat_id = eve_http_headers.optional_ascii_header(
            self.headers,
            "X-OpenWebUI-Chat-Id",
            maximum_characters=160,
        )
        user_message_id = eve_http_headers.optional_ascii_header(
            self.headers,
            "X-OpenWebUI-User-Message-Id",
            maximum_characters=160,
        )
        primary_assistant_id = eve_http_headers.optional_ascii_header(
            self.headers,
            "X-OpenWebUI-Message-Id",
            maximum_characters=160,
        )
        alternate_assistant_id = eve_http_headers.optional_ascii_header(
            self.headers,
            "X-OpenWebUI-Assistant-Message-Id",
            maximum_characters=160,
        )
        if (
            primary_assistant_id
            and alternate_assistant_id
            and primary_assistant_id != alternate_assistant_id
        ):
            raise ValueError("Conflicting OpenWebUI assistant message id headers")
        if not chat_id:
            chat_id = normalize_openai_identifier(
                fallback_chat_id,
                label="OpenWebUI chat id",
            )
        return {
            "openwebui_chat_id": chat_id,
            "openwebui_user_message_id": user_message_id,
            "openwebui_assistant_message_id": (
                primary_assistant_id or alternate_assistant_id
            ),
            "origin": str(getattr(self, "_validated_mutation_origin", "")),
        }

    def send_error_json(
        self,
        status: HTTPStatus,
        message: str,
        *,
        error_id: Optional[str] = None,
    ) -> None:
        payload: Dict[str, object] = {"ok": False, "error": message}
        if error_id:
            payload["error_id"] = error_id
        self.send_json(payload, status=status)

    def send_exception_json(
        self,
        status: HTTPStatus,
        message: str,
        error_type: str = "invalid_request_error",
        error_id: Optional[str] = None,
    ) -> None:
        if self.is_openai_compat_request():
            self.send_openai_error_json(
                status,
                message,
                error_type=error_type,
                error_id=error_id,
            )
            return
        self.send_error_json(status, message, error_id=error_id)

    def is_openai_compat_request(self) -> bool:
        try:
            return eve_http_path.parse_request_target(self.path).path.startswith("/v1/")
        except ValueError:
            return False

    def send_openai_error_json(
        self,
        status: HTTPStatus,
        message: str,
        error_type: str = "invalid_request_error",
        error_id: Optional[str] = None,
    ) -> None:
        error_payload: Dict[str, object] = {
            "message": message,
            "type": error_type,
            "param": None,
            "code": None,
        }
        if error_id:
            error_payload["eve_error_id"] = error_id
        self.send_json(
            {
                "error": error_payload,
            },
            status=status,
        )

    def handle_get_openai_models(self) -> None:
        self.send_json(self.service.openai_models())

    def handle_get_openai_model(self, model_id: str) -> None:
        self.send_json(self.service.openai_model(model_id))

    def handle_post_openai_chat_completions(self) -> None:
        payload = self.read_json_body()
        stream = eve_http_json.boolean_field(payload, "stream", default=False)
        payload["stream"] = stream
        payload["_eve_chat_transport"] = self.openai_chat_transport_headers()
        completion = self.service.openai_chat_completion(payload)
        if stream:
            return self.send_openai_chat_completion_stream(completion)
        self.send_json(completion)

    def handle_post_copilotkit_agui(self) -> None:
        payload = self.read_json_body()
        context = copilotkit_agui_context(payload)
        openai_payload = context["openai_payload"]
        if isinstance(openai_payload, dict):
            openai_payload["_eve_chat_transport"] = self.openai_chat_transport_headers(
                fallback_chat_id=payload.get("chat_id"),
            )

        thread_id = str(context["thread_id"])
        run_id = str(context["run_id"])
        client_request_id = str(context["client_request_id"])
        activity_message_id = str(context["activity_message_id"])
        text_message_id = str(context["text_message_id"])

        self.send_response(HTTPStatus.OK)
        self.send_cors_headers()
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_eve_private_response_headers()
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        def emit(event: Dict[str, object]) -> bool:
            try:
                data = json.dumps(event, ensure_ascii=True).encode("utf-8")
                self.wfile.write(b"data: " + data + b"\n\n")
                self.wfile.flush()
                return True
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return False

        if not emit(
            agui_event(
                "RUN_STARTED",
                threadId=thread_id,
                runId=run_id,
                input={
                    "messages": context["messages"],
                    "source": "eve_chat",
                    "protocol": COPILOTKIT_AGUI_PROTOCOL,
                },
            )
        ):
            return
        if not emit(
            agui_event(
                "STATE_SNAPSHOT",
                snapshot={
                    "adapter": COPILOTKIT_AGUI_PROTOCOL,
                    "provider": "eve_local_runtime",
                    "providerDependency": "none",
                    "authority": "ui_adapter_only",
                    "threadId": thread_id,
                    "runId": run_id,
                    "clientRequestId": client_request_id,
                },
            )
        ):
            return
        if not emit(
            agui_event(
                "ACTIVITY_SNAPSHOT",
                messageId=activity_message_id,
                activityType=COPILOTKIT_AGUI_ACTIVITY_TYPE,
                content=copilotkit_agui_progress_content(None, status="queued"),
                replace=True,
            )
        ):
            return

        result_box: Dict[str, object] = {}

        def run_completion() -> None:
            try:
                result_box["completion"] = self.service.openai_chat_completion(openai_payload)  # type: ignore[arg-type]
            except Exception as exc:
                result_box["error"] = exc

        worker = threading.Thread(
            target=run_completion,
            daemon=True,
            name=f"eve-chat-agui-{run_id[:12]}",
        )
        worker.start()

        last_progress_key = ""
        last_step = ""
        while worker.is_alive():
            try:
                progress_payload = self.service.reply_progress(
                    client_request_id=client_request_id,
                    active_only=False,
                )
                job = progress_payload.get("job") if isinstance(progress_payload, dict) else None
                if isinstance(job, dict):
                    content = copilotkit_agui_progress_content(job, status="running")
                    progress_key = json.dumps(content, ensure_ascii=True, sort_keys=True)
                    step_name = str(content.get("phase") or content.get("status") or "reply_progress")
                    if step_name and step_name != last_step:
                        if last_step:
                            if not emit(agui_event("STEP_FINISHED", stepName=last_step)):
                                return
                        if not emit(agui_event("STEP_STARTED", stepName=step_name)):
                            return
                        last_step = step_name
                    if progress_key != last_progress_key:
                        if not emit(
                            agui_event(
                                "ACTIVITY_DELTA",
                                messageId=activity_message_id,
                                activityType=COPILOTKIT_AGUI_ACTIVITY_TYPE,
                                patch=[
                                    {"op": "replace", "path": "/status", "value": content.get("status")},
                                    {"op": "replace", "path": "/phase", "value": content.get("phase")},
                                    {"op": "replace", "path": "/title", "value": content.get("title")},
                                    {"op": "replace", "path": "/detail", "value": content.get("detail")},
                                    {"op": "replace", "path": "/current_model", "value": content.get("current_model")},
                                    {"op": "replace", "path": "/notes", "value": content.get("notes")},
                                ],
                            )
                        ):
                            return
                        last_progress_key = progress_key
            except Exception:
                # Progress polling is best-effort; the run result remains authoritative.
                pass
            worker.join(0.25)

        worker.join()
        if last_step:
            if not emit(agui_event("STEP_FINISHED", stepName=last_step)):
                return

        error = result_box.get("error")
        if error is not None:
            error_id = self.record_internal_error(
                error if isinstance(error, BaseException) else RuntimeError("unknown AG-UI error"),
                operation="agui_completion",
            )
            emit(
                agui_event(
                    "RUN_ERROR",
                    message="Eve could not complete this run.",
                    code="eve_agui_completion_error",
                    errorId=error_id,
                )
            )
            self.close_connection = True
            return

        completion = result_box.get("completion") if isinstance(result_box.get("completion"), dict) else {}
        reply_text, reply_message_id, eve_metadata = copilotkit_agui_completion_reply(completion)
        final_progress = copilotkit_agui_progress_content(
            {
                "status": "completed",
                "phase": "reply_ready",
                "title": "Reply ready",
                "detail": "Eve returned the local runtime answer through the AG-UI adapter.",
                "reply_message_id": reply_message_id,
                "notes": [],
            },
            status="completed",
        )
        if not emit(
            agui_event(
                "ACTIVITY_DELTA",
                messageId=activity_message_id,
                activityType=COPILOTKIT_AGUI_ACTIVITY_TYPE,
                patch=[
                    {"op": "replace", "path": "/status", "value": final_progress.get("status")},
                    {"op": "replace", "path": "/phase", "value": final_progress.get("phase")},
                    {"op": "replace", "path": "/title", "value": final_progress.get("title")},
                    {"op": "replace", "path": "/detail", "value": final_progress.get("detail")},
                    {"op": "replace", "path": "/reply_message_id", "value": reply_message_id},
                ],
            )
        ):
            return
        if not emit(agui_event("TEXT_MESSAGE_START", messageId=reply_message_id or text_message_id, role="assistant")):
            return
        if reply_text:
            if not emit(agui_event("TEXT_MESSAGE_CONTENT", messageId=reply_message_id or text_message_id, delta=reply_text)):
                return
        if not emit(agui_event("TEXT_MESSAGE_END", messageId=reply_message_id or text_message_id)):
            return
        emit(
            agui_event(
                "RUN_FINISHED",
                threadId=thread_id,
                runId=run_id,
                result={
                    "messageId": reply_message_id or text_message_id,
                    "protocol": COPILOTKIT_AGUI_PROTOCOL,
                    "eve": eve_metadata,
                },
            )
        )
        self.close_connection = True

    def send_openai_chat_completion_stream(self, completion: Dict[str, object]) -> None:
        choices = completion.get("choices") if isinstance(completion.get("choices"), list) else []
        first_choice = choices[0] if choices and isinstance(choices[0], dict) else {}
        message = first_choice.get("message") if isinstance(first_choice.get("message"), dict) else {}
        content = str(message.get("content") or "")
        completion_id = str(completion.get("id") or f"chatcmpl-eve-{uuid.uuid4().hex}")
        model_id = str(completion.get("model") or OPENAI_COMPAT_MODEL_ID)
        created = int(completion.get("created") or openai_compat_created_at())

        def chunk(delta: Dict[str, object], finish_reason: Optional[str] = None) -> Dict[str, object]:
            return {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model_id,
                "choices": [
                    {
                        "index": 0,
                        "delta": delta,
                        "finish_reason": finish_reason,
                    }
                ],
            }

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_eve_private_response_headers()
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        for item in [
            chunk({"role": "assistant"}),
            chunk({"content": content}),
            chunk({}, finish_reason="stop"),
        ]:
            data = json.dumps(item, ensure_ascii=True).encode("utf-8")
            self.wfile.write(b"data: " + data + b"\n\n")
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
        self.close_connection = True

    def handle_get_eve_chat_followups(self, query: eve_http_query.BoundedQuery) -> None:
        limit = query.integer("limit", default=20, minimum=1, maximum=200)
        status = query.value("status", maximum_characters=128)
        surface = query.value(
            "surface",
            default="eve_chat_ui",
            maximum_characters=128,
        )
        include_seen = query.boolean("include_seen", default=False)
        self.send_json(
            {
                "ok": True,
                "data": self.service.eve_chat_followups(
                    status=status,
                    surface=surface,
                    include_seen=include_seen,
                    limit=limit,
                ),
            }
        )

    def handle_post_eve_chat_followup_seen(self, followup_id: str) -> None:
        self.send_json({"ok": True, "data": self.service.mark_eve_chat_followup_seen(followup_id)})

    def handle_get_monitor_stream(self, query: eve_http_query.BoundedQuery) -> None:
        interval_ms = query.integer(
            "interval_ms",
            default=1000,
            minimum=250,
            maximum=10_000,
        )
        interval_seconds = interval_ms / 1000
        compact = query.boolean("compact", default=False)

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_eve_private_response_headers()
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        last_fingerprint = ""
        while True:
            try:
                monitor_payload = self.service.monitor_payload(compact=compact)
                fingerprint_payload = dict(monitor_payload)
                fingerprint = json.dumps(fingerprint_payload, ensure_ascii=True, sort_keys=True)
                payload = json_bytes({"ok": True, "data": monitor_payload}).decode("utf-8")
                if fingerprint != last_fingerprint:
                    self.wfile.write(b"event: monitor\n")
                    for line in payload.splitlines() or [""]:
                        self.wfile.write(f"data: {line}\n".encode("utf-8"))
                    self.wfile.write(b"\n")
                    last_fingerprint = fingerprint
                else:
                    self.wfile.write(b": heartbeat\n\n")
                self.wfile.flush()
                time.sleep(interval_seconds)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return
            except Exception as exc:
                error_id = self.record_internal_error(
                    exc,
                    operation="monitor_stream",
                )
                try:
                    payload = json_bytes(
                        {
                            "ok": False,
                            "error": "Eve's monitor update is temporarily unavailable.",
                            "error_id": error_id,
                        }
                    ).decode("utf-8")
                    self.wfile.write(b"event: error\n")
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    return
                return

    def handle_get_threads(self, query: eve_http_query.BoundedQuery) -> None:
        limit = query.integer("limit", default=30, minimum=1, maximum=500)
        status = query.value("status", maximum_characters=128)
        audience = query.value("audience", maximum_characters=128)
        self.send_json({"ok": True, "data": self.service.threads(limit=limit, status=status, audience=audience)})

    def handle_get_bootstrap(self, query: eve_http_query.BoundedQuery) -> None:
        default_host, default_api_port = self.advertised_endpoint()
        primary_host, api_port, ollama_port = advertised_endpoint_query(
            query,
            default_host=default_host,
            default_api_port=default_api_port,
        )
        self.send_json(
            {
                "ok": True,
                "data": self.service.bootstrap_payload(
                    primary_host=primary_host,
                    api_port=api_port,
                    ollama_port=ollama_port,
                ),
            }
        )

    def handle_get_code_bundle(self) -> None:
        self.send_bytes(self.service.code_bundle_archive(), "application/zip")

    def handle_get_update_manifest(self, query: eve_http_query.BoundedQuery) -> None:
        default_host, default_api_port = self.advertised_endpoint()
        primary_host, api_port, ollama_port = advertised_endpoint_query(
            query,
            default_host=default_host,
            default_api_port=default_api_port,
        )
        self.send_json(
            {
                "ok": True,
                "data": self.service.update_manifest(
                    primary_host=primary_host,
                    api_port=api_port,
                    ollama_port=ollama_port,
                ),
            }
        )

    def handle_get_windows_app_package(self) -> None:
        host, port = self.advertised_endpoint()
        payload = self.service.windows_app_package_archive(host, port)
        self.send_bytes(payload, "application/zip")

    def handle_get_windows_install_page(self) -> None:
        host, port = self.advertised_endpoint()
        base_url = f"http://{eve_http_security.http_authority(host, port)}"
        self.send_bytes(
            render_windows_install_page(base_url, host, port),
            "text/html; charset=utf-8",
        )

    def handle_get_install_page(self) -> None:
        host, port = self.advertised_endpoint()
        base_url = f"http://{eve_http_security.http_authority(host, port)}"
        self.send_bytes(
            render_install_page(base_url, host, port),
            "text/html; charset=utf-8",
        )

    def handle_get_windows_script(self, filename: str) -> None:
        host, port = self.advertised_endpoint()
        payload = customized_windows_script(filename, host, port)
        self.send_download(payload, "text/plain; charset=utf-8", filename)

    def handle_get_windows_launcher(self, filename: str) -> None:
        host, port = self.advertised_endpoint()
        payload = customized_windows_launcher(filename, host, port)
        self.send_download(payload, "text/plain; charset=utf-8", filename)

    def handle_get_windows_installer_exe(self) -> None:
        host, port = self.advertised_endpoint()
        payload = build_windows_installer_exe(host, port)
        self.send_download(payload, "application/vnd.microsoft.portable-executable", "EveSetup.exe")

    def handle_get_windows_app_package_download(self) -> None:
        host, port = self.advertised_endpoint()
        payload = self.service.windows_app_package_archive(host, port)
        self.send_download(payload, "application/zip", "EveWindowsAppPackage.zip")

    def handle_get_macos_installer_bundle(self) -> None:
        host, port = self.advertised_endpoint()
        payload = build_macos_installer_bundle(host, port)
        self.send_download(payload, "application/zip", "EveMacSetup.zip")

    def handle_get_macos_installer_app_bundle(self) -> None:
        host, port = self.advertised_endpoint()
        payload = build_macos_installer_app_bundle(host, port)
        self.send_download(payload, "application/zip", MAC_INSTALLER_FILENAME)

    def handle_get_linux_installer_bundle(self) -> None:
        host, port = self.advertised_endpoint()
        payload = build_linux_installer_bundle(host, port)
        self.send_download(payload, "application/gzip", "EveLinuxSetup.tar.gz")

    def handle_get_bootstrap_download(self) -> None:
        host, port = self.advertised_endpoint()
        payload = self.service.bootstrap_payload(primary_host=host, api_port=port, ollama_port=11434)
        self.send_download(json_bytes(payload), "application/json; charset=utf-8", "bootstrap_bundle.json")

    def handle_get_code_bundle_download(self) -> None:
        self.send_download(self.service.code_bundle_archive(), "application/zip", "eve_code_bundle.zip")

    def handle_get_reply_progress(self, query: eve_http_query.BoundedQuery) -> None:
        client_request_id = query.value("client_request_id", maximum_characters=512)
        thread_id = query.value("thread_id", maximum_characters=512)
        active_only = query.boolean("active_only", default=True)
        self.send_json(
            {
                "ok": True,
                "data": self.service.reply_progress(
                    client_request_id=client_request_id,
                    thread_id=thread_id,
                    active_only=active_only,
                ),
            }
        )

    def handle_get_reply_turns(self, query: eve_http_query.BoundedQuery) -> None:
        limit = query.integer("limit", default=20, minimum=1, maximum=200)
        thread_id = query.value("thread_id", maximum_characters=512)
        reply_message_id = query.value("reply_message_id", maximum_characters=512)
        self.send_json(
            {
                "ok": True,
                "data": self.service.reply_turn_replays(
                    limit=limit,
                    thread_id=thread_id,
                    reply_message_id=reply_message_id,
                ),
            }
        )

    def handle_get_reply_council_turns(self, query: eve_http_query.BoundedQuery) -> None:
        limit = query.integer("limit", default=20, minimum=1, maximum=200)
        thread_id = query.value("thread_id", maximum_characters=512)
        reply_message_id = query.value("reply_message_id", maximum_characters=512)
        self.send_json(
            {
                "ok": True,
                "data": self.service.reply_council_turns(
                    limit=limit,
                    thread_id=thread_id,
                    reply_message_id=reply_message_id,
                ),
            }
        )

    def handle_get_conversation_spine(self, query: eve_http_query.BoundedQuery) -> None:
        limit = query.integer("limit", default=20, minimum=1, maximum=500)
        thread_id = query.value("thread_id", maximum_characters=512)
        role = query.value("role", maximum_characters=64)
        direction = query.value("direction", maximum_characters=64)
        include_synthetic = query.boolean("include_synthetic", default=True)
        self.send_json(
            {
                "ok": True,
                "data": self.service.conversation_spine(
                    limit=limit,
                    thread_id=thread_id,
                    role=role,
                    direction=direction,
                    include_synthetic=include_synthetic,
                ),
            }
        )

    def handle_get_messages(self, query: eve_http_query.BoundedQuery) -> None:
        limit = query.integer("limit", default=30, minimum=1, maximum=500)
        sender = query.value("sender", maximum_characters=128)
        recipient = query.value("recipient", maximum_characters=128)
        status = query.value("status", maximum_characters=128)
        thread_id = query.value("thread", maximum_characters=512)
        initiated = query.boolean("initiated", default=False)
        personal = query.boolean("personal", default=False)
        self.send_json(
            {
                "ok": True,
                "data": self.service.messages(
                    limit=limit,
                    sender=sender,
                    recipient=recipient,
                    status=status,
                    thread_id=thread_id,
                    initiated=initiated,
                    personal=personal,
                ),
            }
        )

    def handle_get_message(self, message_id: str) -> None:
        self.send_json({"ok": True, "data": self.service.open_message(message_id)})

    def handle_get_thread(self, thread_id: str) -> None:
        self.send_json({"ok": True, "data": self.service.thread_messages(thread_id)})

    def handle_get_proposals(self, query: eve_http_query.BoundedQuery) -> None:
        limit = query.integer("limit", default=20, minimum=1, maximum=500)
        status = query.value("status", maximum_characters=128)
        self.send_json({"ok": True, "data": self.service.proposals(limit=limit, status=status)})

    def handle_get_governance(self, query: eve_http_query.BoundedQuery) -> None:
        limit = query.integer("limit", default=20, minimum=1, maximum=500)
        runtime = query.boolean("runtime", default=True)
        self.send_json({"ok": True, "data": self.service.governance(limit=limit, runtime=runtime)})

    def handle_get_reflections(self, query: eve_http_query.BoundedQuery) -> None:
        limit = query.integer("limit", default=10, minimum=1, maximum=500)
        self.send_json({"ok": True, "data": self.service.reflections(limit=limit)})

    def handle_get_thoughts(self, query: eve_http_query.BoundedQuery) -> None:
        limit = query.integer("limit", default=10, minimum=1, maximum=500)
        self.send_json({"ok": True, "data": self.service.thoughts(limit=limit)})

    def handle_get_tensions(self, query: eve_http_query.BoundedQuery) -> None:
        limit = query.integer("limit", default=10, minimum=1, maximum=500)
        status = query.value("status", maximum_characters=128)
        self.send_json({"ok": True, "data": self.service.tensions(limit=limit, status=status)})

    def handle_get_experiments(self, query: eve_http_query.BoundedQuery) -> None:
        limit = query.integer("limit", default=10, minimum=1, maximum=500)
        status = query.value("status", maximum_characters=128)
        self.send_json({"ok": True, "data": self.service.experiments(limit=limit, status=status)})

    def handle_get_evaluations(self, query: eve_http_query.BoundedQuery) -> None:
        limit = query.integer("limit", default=20, minimum=1, maximum=500)
        target_kind = query.value("target_kind", maximum_characters=128)
        target_id = query.value("target_id", maximum_characters=512)
        evaluator = query.value("evaluator", maximum_characters=256)
        thread_id = query.value("thread", maximum_characters=512)
        days = query.integer("days", minimum=1, maximum=3650)
        self.send_json(
            {
                "ok": True,
                "data": self.service.evaluations(
                    limit=limit,
                    target_kind=target_kind,
                    target_id=target_id,
                    evaluator=evaluator,
                    thread_id=thread_id,
                    since_days=days,
                ),
            }
        )

    def handle_get_outcomes(self, query: eve_http_query.BoundedQuery) -> None:
        limit = query.integer("limit", default=20, minimum=1, maximum=500)
        target_kind = query.value("target_kind", maximum_characters=128)
        target_id = query.value("target_id", maximum_characters=512)
        direction = query.value("direction", maximum_characters=64)
        thread_id = query.value("thread", maximum_characters=512)
        days = query.integer("days", minimum=1, maximum=3650)
        self.send_json(
            {
                "ok": True,
                "data": self.service.outcomes(
                    limit=limit,
                    target_kind=target_kind,
                    target_id=target_id,
                    direction=direction,
                    thread_id=thread_id,
                    since_days=days,
                ),
            }
        )

    def handle_get_failure_clusters(self, query: eve_http_query.BoundedQuery) -> None:
        limit = query.integer("limit", default=20, minimum=1, maximum=500)
        status = query.value("status", maximum_characters=128)
        days = query.integer("days", minimum=1, maximum=3650)
        self.send_json(
            {
                "ok": True,
                "data": self.service.failure_clusters(limit=limit, status=status, since_days=days),
            }
        )

    def handle_get_model_health(self, query: eve_http_query.BoundedQuery) -> None:
        limit = query.integer("limit", default=5, minimum=1, maximum=100)
        self.send_json({"ok": True, "data": self.service.model_health_payload(limit=limit)})

    def handle_get_activity(self, query: eve_http_query.BoundedQuery) -> None:
        limit = query.integer("limit", default=20, minimum=1, maximum=500)
        self.send_json({"ok": True, "data": self.service.activity(limit=limit)})

    def handle_get_attachments(self, query: eve_http_query.BoundedQuery) -> None:
        limit = query.integer("limit", default=100, minimum=1, maximum=500)
        thread_id = query.value("thread_id", maximum_characters=512)
        message_id = query.value("message_id", maximum_characters=512)
        self.send_json(
            {
                "ok": True,
                "data": self.service.attachments(
                    thread_id=thread_id,
                    message_id=message_id,
                    limit=limit,
                ),
            }
        )

    def handle_post_attachment_upload(self) -> None:
        payload = self.read_json_body(maximum_bytes=MAX_ATTACHMENT_JSON_REQUEST_BYTES)
        self.send_json({"ok": True, "data": self.service.upload_attachment(payload)})

    def handle_post_ask(self) -> None:
        payload = self.read_json_body()
        body = eve_http_json.text_field(
            payload,
            "body",
            label="Message body",
            maximum_characters=MAX_CONVERSATION_BODY_CHARACTERS,
            multiline=True,
        )
        subject = eve_http_json.text_field(
            payload,
            "subject",
            label="Message subject",
            maximum_characters=MAX_CONVERSATION_SUBJECT_CHARACTERS,
            default="Question from user",
        ) or "Question from user"
        client_request_id = eve_http_json.text_field(
            payload,
            "client_request_id",
            maximum_characters=MAX_CLIENT_REQUEST_ID_CHARACTERS,
        ) or None
        attachments = eve_http_json.object_list_field(
            payload,
            "attachments",
            maximum_items=eve_attachments.MAX_ATTACHMENTS_PER_MESSAGE,
        )
        self.send_json(
            {
                "ok": True,
                "data": self.service.ask(
                    body,
                    subject=subject,
                    client_request_id=client_request_id,
                    attachments=attachments,
                ),
            }
        )

    def handle_post_initiate(self) -> None:
        payload = self.read_json_body()
        allow_none = eve_http_json.boolean_field(payload, "allow_none", default=False)
        notify = eve_http_json.boolean_field(payload, "notify", default=True)
        self.send_json(
            {
                "ok": True,
                "data": self.service.initiate_personal_message(
                    allow_none=allow_none,
                    notify=notify,
                ),
            }
        )

    def handle_post_reply(self) -> None:
        payload = self.read_json_body()
        message_id = eve_http_json.text_field(
            payload,
            "message_id",
            maximum_characters=512,
            required=True,
        )
        body = eve_http_json.text_field(
            payload,
            "body",
            label="Message body",
            maximum_characters=MAX_CONVERSATION_BODY_CHARACTERS,
            multiline=True,
        )
        subject = eve_http_json.text_field(
            payload,
            "subject",
            label="Message subject",
            maximum_characters=MAX_CONVERSATION_SUBJECT_CHARACTERS,
        ) or None
        client_request_id = eve_http_json.text_field(
            payload,
            "client_request_id",
            maximum_characters=MAX_CLIENT_REQUEST_ID_CHARACTERS,
        ) or None
        attachments = eve_http_json.object_list_field(
            payload,
            "attachments",
            maximum_items=eve_attachments.MAX_ATTACHMENTS_PER_MESSAGE,
        )
        self.send_json(
            {
                "ok": True,
                "data": self.service.reply(
                    message_id=message_id,
                    body=body,
                    subject=subject,
                    client_request_id=client_request_id,
                    attachments=attachments,
                ),
            }
        )

    def handle_post_mark_message(self, message_id: str) -> None:
        payload = self.read_json_body()
        status = eve_http_json.text_field(
            payload,
            "status",
            maximum_characters=64,
            required=True,
        )
        self.send_json({"ok": True, "data": self.service.mark_message(message_id, status=status)})

    def handle_post_proposal_status(self, proposal_id: str) -> None:
        payload = self.read_json_body()
        status = eve_http_json.text_field(
            payload,
            "status",
            maximum_characters=64,
            required=True,
        )
        self.send_json({"ok": True, "data": self.service.update_proposal_status(proposal_id, status=status)})

    def handle_post_think(self) -> None:
        self.read_json_body()
        self.send_json({"ok": True, "data": self.service.think()})

    def handle_post_wake(self) -> None:
        self.read_json_body()
        self.send_json({"ok": True, "data": self.service.wake_eve_if_needed()})

    def handle_post_reflect(self) -> None:
        self.read_json_body()
        self.send_json({"ok": True, "data": self.service.reflect()})

    def handle_post_suggest_proposal(self) -> None:
        self.read_json_body()
        self.send_json({"ok": True, "data": self.service.suggest_proposal()})

    def handle_post_capture(self) -> None:
        payload = self.read_json_body()
        kind = eve_http_json.text_field(
            payload,
            "kind",
            label="Capture kind",
            maximum_characters=64,
            default="note",
        ) or "note"
        raw_text = payload.get("text")
        if raw_text is None or (isinstance(raw_text, str) and not raw_text.strip()):
            raw_text = payload.get("body")
        text = eve_http_json.require_text_value(
            raw_text,
            label="Capture text",
            maximum_characters=MAX_CONVERSATION_BODY_CHARACTERS,
            required=True,
            multiline=True,
        )
        tags = eve_http_json.string_list_field(
            payload,
            "tags",
            maximum_items=MAX_CAPTURE_TAGS,
            maximum_item_characters=64,
            allow_space_separated_string=True,
        )
        self.send_json({"ok": True, "data": self.service.capture(kind, text, tags)})

    def handle_post_daemon_start(self) -> None:
        self.read_json_body()
        self.send_json({"ok": True, "data": self.service.daemon_start()})

    def handle_post_daemon_stop(self) -> None:
        self.read_json_body()
        self.send_json({"ok": True, "data": self.service.daemon_stop()})


def create_server(
    host: str = "127.0.0.1",
    port: int = 8787,
    *,
    service: Optional[EveRuntimeService] = None,
    static_dir: Path = WEB_DIR,
    advertised_host: Optional[str] = None,
    bind_and_activate: bool = True,
) -> EveHTTPServer:
    return EveHTTPServer(
        (host, port),
        EveAppHandler,
        service=service,
        static_dir=static_dir,
        advertised_host=advertised_host,
        bind_and_activate=bind_and_activate,
    )


def main(
    host: str = "127.0.0.1",
    port: int = 8787,
    open_browser: bool = False,
    advertised_host: Optional[str] = None,
) -> int:
    configured_advertised_host = advertised_host
    if configured_advertised_host is None:
        configured_advertised_host = os.environ.get("EVE_ADVERTISED_HOST") or None
    server = create_server(
        host=host,
        port=port,
        advertised_host=configured_advertised_host,
    )
    recovery = server.service.resume_eve_chat_followups()
    url = f"http://{eve_http_security.http_authority(server.advertised_host, server.server_port)}"
    print(
        f"Eve app running at {url}; durable follow-ups resumed: "
        f"{recovery.get('recoverable_count') or 0}"
    )
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
