#!/usr/bin/env python3
"""Private sensory-session authorization and durable feature ingestion.

The service owns session tokens, restart rehydration, cross-process event
budgets, and feature-only integration. It receives its database path and policy
from the composition root, and it owns no HTTP route or ambient capture toggle.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, Optional

import eve
import eve_db
import eve_sensory


@dataclass(frozen=True)
class SensorySessionPolicy:
    min_seconds: int
    max_seconds: int
    max_batches_per_10_seconds: int
    max_events: int
    max_active: int
    modalities: frozenset[str]


class SensorySessionService:
    def __init__(
        self,
        *,
        database_path_provider: Callable[[], Path],
        policy_provider: Callable[[], SensorySessionPolicy],
    ) -> None:
        self._database_path_provider = database_path_provider
        self._policy_provider = policy_provider
        self._sensory_sessions_lock = threading.RLock()
        self._sensory_sessions: Dict[str, Dict[str, object]] = {}

    def _database_path(self) -> Path:
        return Path(self._database_path_provider())

    def _policy(self) -> SensorySessionPolicy:
        return self._policy_provider()

    def _sensory_session_observation_stats(self, session_id: str) -> tuple[int, Optional[str]]:
        """Read durable count/last time without trusting process-local counters.

        Browser observations add a short binding suffix to the session
        correlation id, while hardware adapters use the exact session id. The
        generated session id cannot contain wildcard characters, but using a
        prefix comparison rather than ``LIKE`` keeps the accounting literal.
        """
        prefix = f"{session_id}:"
        with eve_db.connect_database(self._database_path()) as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS event_count, MAX(created_at) AS last_event_at
                  FROM events
                 WHERE stream = 'sensory'
                   AND kind = 'sensory.observed'
                   AND (correlation_id = ? OR substr(correlation_id, 1, ?) = ?)
                """,
                (session_id, len(prefix), prefix),
            ).fetchone()
        return (
            int(row["event_count"] if row is not None else 0),
            str(row["last_event_at"]) if row is not None and row["last_event_at"] else None,
        )

    def _sensory_session_observation_count(self, session_id: str) -> int:
        return self._sensory_session_observation_stats(session_id)[0]

    def _write_sensory_observations(
        self,
        record: Dict[str, object],
        events: list[Dict[str, object]],
    ) -> tuple[list[Dict[str, object]], int]:
        """Atomically enforce the durable session budget and append a batch.

        The Go hardware adapter uses the same ``.lock`` file and count query.
        Keeping the count and inserts under that cross-process writer lock
        prevents browser and hardware observations from racing past the shared
        5,000-feature session budget.
        """
        db_path = self._database_path()
        eve_db.initialize_database(db_path)
        session_id = str(record.get("session_id") or "")
        prefix = f"{session_id}:"
        written: list[Dict[str, object]] = []
        with eve_db.single_writer_lock(db_path):
            with eve_db.connect_database(db_path) as conn:
                stopped = conn.execute(
                    "SELECT COUNT(*) AS stop_count FROM events "
                    "WHERE correlation_id = ? AND kind = 'sensory.session.stopped'",
                    (session_id,),
                ).fetchone()
                expires_at = eve.parse_iso_datetime(record.get("expires_at"))
                if (
                    (stopped is not None and int(stopped["stop_count"] or 0) > 0)
                    or expires_at is None
                    or expires_at <= datetime.now(timezone.utc)
                ):
                    raise ValueError("sensory session is not active")
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS event_count
                      FROM events
                     WHERE stream = 'sensory'
                       AND kind = 'sensory.observed'
                       AND (correlation_id = ? OR substr(correlation_id, 1, ?) = ?)
                    """,
                    (session_id, len(prefix), prefix),
                ).fetchone()
                existing = int(row["event_count"] if row is not None else 0)
                if existing + len(events) > self._policy().max_events:
                    raise ValueError("sensory session event budget exceeded")
                for event in events:
                    stored = eve_db.normalize_event_record(
                        {
                            "id": str(uuid.uuid4()),
                            "created_at": eve_db.utc_now(),
                            "source": str(event.get("source") or "private_device_adapter"),
                            "actor": "eve-sensory-adapter",
                            "kind": "sensory.observed",
                            "stream": "sensory",
                            "subject": str(event.get("subject") or "local_scene"),
                            "correlation_id": str(event.get("correlation_id") or session_id),
                            "payload": {"event": event},
                            "metadata": {
                                "session_id": session_id,
                                "persistence": "features_only",
                                "raw_device_capture_persisted": False,
                                "authority": "observation_only",
                            },
                        }
                    )
                    conn.execute(
                        """
                        INSERT INTO events
                            (id, created_at, source, actor, kind, stream, subject, correlation_id,
                             causation_id, schema_version, payload_json, metadata_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            stored["id"],
                            stored["created_at"],
                            stored["source"],
                            stored["actor"],
                            stored["kind"],
                            stored["stream"],
                            stored["subject"],
                            stored["correlation_id"],
                            stored["causation_id"],
                            stored["schema_version"],
                            json.dumps(stored["payload"], ensure_ascii=True, sort_keys=True),
                            json.dumps(stored["metadata"], ensure_ascii=True, sort_keys=True),
                        ),
                    )
                    written.append(stored)
                conn.commit()
        return written, existing + len(written)

    def _prune_sensory_sessions(self, *, now: Optional[datetime] = None) -> None:
        current = now or datetime.now(timezone.utc)
        expired: list[str] = []
        for session_id, record in self._sensory_sessions.items():
            expires_at = eve.parse_iso_datetime(record.get("expires_at"))
            if record.get("status") != "active" or expires_at is None or expires_at <= current:
                expired.append(session_id)
        for session_id in expired:
            self._sensory_sessions.pop(session_id, None)

    def _rehydrate_sensory_session(self, session_id: str) -> Optional[Dict[str, object]]:
        """Recover an authorized session after a local backend restart.

        Only a one-way token hash is durable. The browser still has to present
        the original high-entropy token, and a later stop event closes the
        session. Raw sensor material is never part of this recovery record.
        """
        if not session_id:
            return None
        records = eve_db.read_events(
            self._database_path(),
            limit=12,
            stream="sensory",
            correlation_id=session_id,
        )
        if any(item.get("kind") == "sensory.session.stopped" for item in records):
            return None
        boundary = next((item for item in records if item.get("kind") == "sensory.session.started"), None)
        if not isinstance(boundary, dict):
            return None
        payload = boundary.get("payload") if isinstance(boundary.get("payload"), dict) else {}
        metadata = boundary.get("metadata") if isinstance(boundary.get("metadata"), dict) else {}
        public = payload.get("session") if isinstance(payload.get("session"), dict) else {}
        expires_at = eve.parse_iso_datetime(public.get("expires_at"))
        token_hash = str(metadata.get("session_token_hash") or "")
        modalities = [
            str(item)
            for item in (public.get("modalities") or [])
            if str(item) in self._policy().modalities
        ]
        if expires_at is None or expires_at <= datetime.now(timezone.utc) or not token_hash or not modalities:
            return None
        accepted_events, last_event_at = self._sensory_session_observation_stats(session_id)
        return {
            "session_id": session_id,
            "token_hash": token_hash,
            "created_at": public.get("created_at") or boundary.get("created_at"),
            "expires_at": expires_at.replace(microsecond=0).isoformat(),
            "status": "active",
            "modalities": modalities,
            "purpose": public.get("purpose") or "Recovered bounded local sensory session.",
            "accepted_events": accepted_events,
            "last_event_at": last_event_at,
            "batch_times": [],
            "last_integrated_monotonic": 0.0,
        }

    @staticmethod
    def _public_sensory_session(record: Dict[str, object]) -> Dict[str, object]:
        return {
            "schema_version": "eve.sensory_session.v1",
            "session_id": record.get("session_id"),
            "created_at": record.get("created_at"),
            "expires_at": record.get("expires_at"),
            "status": record.get("status"),
            "modalities": list(record.get("modalities") or []),
            "purpose": record.get("purpose"),
            "accepted_events": int(record.get("accepted_events") or 0),
            "last_event_at": record.get("last_event_at"),
            "privacy": {
                "persistence": "features_only",
                "raw_audio_retained": False,
                "raw_images_retained": False,
                "raw_screen_retained": False,
                "transcripts_retained": False,
                "keystrokes_retained": False,
            },
            "authority": "observation_only",
        }

    def sensory_status(self) -> Dict[str, object]:
        with self._sensory_sessions_lock:
            self._prune_sensory_sessions()
            active_records = [
                item for item in self._sensory_sessions.values() if item.get("status") == "active"
            ]
        # Hardware adapters write through the same durable event spine but do
        # not share this Python process's counters. Refresh public truth before
        # reporting status so Go observations are not hidden until a browser
        # batch happens to arrive.
        for item in active_records:
            count, last_event_at = self._sensory_session_observation_stats(
                str(item.get("session_id") or "")
            )
            with self._sensory_sessions_lock:
                item["accepted_events"] = count
                if last_event_at:
                    item["last_event_at"] = last_event_at
        sessions = [self._public_sensory_session(item) for item in active_records]
        frame = eve.load_sensory_frame(prefer_runtime=True)
        return {
            "schema_version": "eve.sensory_adapter_status.v1",
            "generated_at": eve.utc_now(),
            "active_sessions": sessions,
            "active_session_count": len(sessions),
            "latest_frame": frame,
            "capture_default": "off",
            "boundary": eve_sensory.BOUNDARY,
        }

    def start_sensory_session(self, payload: Dict[str, object]) -> Dict[str, object]:
        if payload.get("operator_confirmed") is not True:
            raise ValueError("operator_confirmed=true is required to start private sensors")
        raw_modalities = payload.get("modalities")
        if not isinstance(raw_modalities, list) or not raw_modalities:
            raise ValueError("modalities must be a non-empty array")
        modalities: list[str] = []
        for item in raw_modalities:
            modality = str(item or "").strip().lower()
            if modality == "touch":
                modality = "proprioceptive"
            if modality not in self._policy().modalities:
                raise ValueError(f"unsupported sensory modality: {modality or 'missing'}")
            if modality not in modalities:
                modalities.append(modality)
        purpose = " ".join(str(payload.get("purpose") or "").split())[:240]
        if not purpose:
            raise ValueError("a bounded sensory purpose is required")
        try:
            requested_duration = int(payload.get("duration_seconds") or 600)
        except (TypeError, ValueError) as exc:
            raise ValueError("duration_seconds must be an integer") from exc
        duration_seconds = max(
            self._policy().min_seconds,
            min(self._policy().max_seconds, requested_duration),
        )
        now = datetime.now(timezone.utc).replace(microsecond=0)
        session_id = f"sensory-{uuid.uuid4()}"
        token = secrets.token_urlsafe(32)
        record: Dict[str, object] = {
            "session_id": session_id,
            "token_hash": hashlib.sha256(token.encode("utf-8")).hexdigest(),
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=duration_seconds)).isoformat(),
            "status": "active",
            "modalities": modalities,
            "purpose": purpose,
            "accepted_events": 0,
            "last_event_at": None,
            "batch_times": [],
            "last_integrated_monotonic": 0.0,
        }
        with self._sensory_sessions_lock:
            self._prune_sensory_sessions(now=now)
            active_count = sum(
                1 for item in self._sensory_sessions.values() if item.get("status") == "active"
            )
            if active_count >= self._policy().max_active:
                raise ValueError("too many active sensory sessions")
            self._sensory_sessions[session_id] = record
        eve_db.record_event(
            self._database_path(),
            kind="sensory.session.started",
            source="eve_chat_sensor_control",
            actor="user",
            stream="sensory",
            subject="private_device_session",
            correlation_id=session_id,
            payload={"session": self._public_sensory_session(record)},
            metadata={
                "operator_confirmed": True,
                "session_token_hash": record["token_hash"],
                "session_expires_at": record["expires_at"],
                "admitted_modalities": modalities,
                "persistence": "features_only",
                "raw_device_capture_persisted": False,
                "authority": "observation_only",
            },
        )
        result = self._public_sensory_session(record)
        result["session_token"] = token
        return result

    def _authorized_sensory_session(self, session_id: object, token: object) -> Dict[str, object]:
        normalized_id = str(session_id or "").strip()
        supplied_token = str(token or "").strip()
        if not normalized_id or not supplied_token:
            raise ValueError("session_id and session_token are required")
        with self._sensory_sessions_lock:
            self._prune_sensory_sessions()
            record = self._sensory_sessions.get(normalized_id)
        if not isinstance(record, dict):
            record = self._rehydrate_sensory_session(normalized_id)
            if isinstance(record, dict):
                with self._sensory_sessions_lock:
                    self._sensory_sessions[normalized_id] = record
        if not isinstance(record, dict) or record.get("status") != "active":
            raise ValueError("sensory session is not active")
        with self._sensory_sessions_lock:
            expected = str(record.get("token_hash") or "")
            actual = hashlib.sha256(supplied_token.encode("utf-8")).hexdigest()
            if not expected or not secrets.compare_digest(expected, actual):
                raise ValueError("sensory session token is invalid")
            return record

    def stop_sensory_session(self, payload: Dict[str, object]) -> Dict[str, object]:
        record = self._authorized_sensory_session(
            payload.get("session_id"),
            payload.get("session_token"),
        )
        public = self._public_sensory_session({**record, "status": "stopped"})
        with self._sensory_sessions_lock:
            self._sensory_sessions.pop(str(record.get("session_id")), None)
        eve_db.record_event(
            self._database_path(),
            kind="sensory.session.stopped",
            source="eve_chat_sensor_control",
            actor="user",
            stream="sensory",
            subject="private_device_session",
            correlation_id=str(record.get("session_id") or ""),
            payload={"session": public},
            metadata={"persistence": "features_only", "raw_device_capture_persisted": False},
        )
        return public

    def ingest_sensory_events(self, payload: Dict[str, object]) -> Dict[str, object]:
        record = self._authorized_sensory_session(
            payload.get("session_id"),
            payload.get("session_token"),
        )
        now = datetime.now(timezone.utc).replace(microsecond=0)
        monotonic_now = time.monotonic()
        with self._sensory_sessions_lock:
            recent_batches = [
                float(item)
                for item in (record.get("batch_times") or [])
                if monotonic_now - float(item) <= 10.0
            ]
            if len(recent_batches) >= self._policy().max_batches_per_10_seconds:
                raise ValueError("sensory adapter rate limit exceeded")
            recent_batches.append(monotonic_now)
            record["batch_times"] = recent_batches

        events = eve_sensory.normalize_adapter_batch(
            payload.get("events"),
            allowed_modalities=record.get("modalities") or [],
            session_id=str(record.get("session_id") or ""),
            now=now,
        )
        created_at = eve.parse_iso_datetime(record.get("created_at"))
        expires_at = eve.parse_iso_datetime(record.get("expires_at"))
        if created_at is None or expires_at is None:
            raise ValueError("sensory session timing evidence is invalid")
        for event in events:
            observed_at = eve.parse_iso_datetime(event.get("observed_at"))
            if (
                observed_at is None
                or observed_at < created_at - timedelta(seconds=5)
                or observed_at > now + timedelta(seconds=5)
                or observed_at > expires_at
            ):
                raise ValueError("sensory event timestamp is outside the current session")
        written, durable_count = self._write_sensory_observations(record, events)
        with self._sensory_sessions_lock:
            record["accepted_events"] = durable_count

        last_integrated = float(record.get("last_integrated_monotonic") or 0.0)
        should_integrate = bool(
            (last_integrated <= 0.0 or monotonic_now - last_integrated >= 3.0)
            and any(
                max(
                    float(item.get("change") or 0),
                    float(item.get("novelty") or 0),
                    float(item.get("urgency") or 0),
                )
                >= 65
                for item in events
            )
        )
        integrated_cycle_id = ""
        if should_integrate:
            state = eve.load_state(prefer_runtime=True)
            frame = eve.run_sensory_attention_tick(
                eve.load_config(),
                state,
                source="sensory_adapter_ingest",
                prefer_runtime=True,
                now=now,
            )
            eve.save_state(state)
            conscious = eve.build_recurrent_conscious_state(
                source="chat_sensory_adapter",
                sensory_frame_override=frame,
            )
            integrated_cycle_id = str(conscious.get("cycle_id") or "")
            record["last_integrated_monotonic"] = monotonic_now

        with self._sensory_sessions_lock:
            record["last_event_at"] = now.isoformat()
        return {
            "schema_version": "eve.sensory_ingest_result.v1",
            "accepted": len(events),
            "event_ids": [item.get("id") for item in written],
            "integrated": bool(integrated_cycle_id),
            "conscious_cycle_id": integrated_cycle_id,
            "persistence": "features_only",
            "raw_content_retained": False,
        }
