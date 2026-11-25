"""Verified sensorimotor episodes in Eve's existing operational event store.

No identity, model, scheduler, task queue, or second autobiographical store lives
here. Predictions are fitted from measured consequences, not model narration.
Synthetic trials are isolated by provenance; numerical prediction is not a
consciousness measure or proof of causal identification.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import time
import uuid

import eve_db
import eve_predictive_dynamics


STREAM = "embodiment"
SCHEMA = "eve.embodied_episode.v1"
_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")


def _identifier(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("Expected a bounded identifier")
    return value


def _number(value, *, low=-1e12, high=1e12):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError("Expected a finite number")
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError("Number outside measurement bounds")
    return float(value)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def body_observation(payload, *, now=None):
    """Validate measured pose/time, never the controller's requested speed."""
    now = time.time() if now is None else now
    if not isinstance(payload, dict) or payload.get("source") != "flybody_sensor":
        raise ValueError("A body sensor observation is required")
    observed_at = _number(payload.get("observed_at"), low=0)
    if not -2 <= now - observed_at <= 10:
        raise ValueError("Body observation is stale or future dated")
    xy = payload.get("xy_cm")
    if not isinstance(xy, list) or len(xy) != 2:
        raise ValueError("Two measured position coordinates are required")
    return {
        "id": _identifier(payload.get("id")),
        "epoch": _identifier(payload.get("epoch")),
        "organ_epoch": _identifier(payload["organ_epoch"]) if payload.get("organ_epoch") is not None else None,
        "source": "flybody_sensor",
        "observed_at": observed_at,
        "sim_time_s": _number(payload.get("sim_time_s"), low=0),
        "xy_cm": [_number(v) for v in xy],
    }


def flybody_sample(payload, *, now=None):
    """Adapt the existing flybody sensor, excluding requested motor setpoints.

    Legacy producers lack a restart epoch. They may supply confounded
    observations only; the live adapter must not train from them.
    """
    if not isinstance(payload, dict):
        raise ValueError("Missing flybody status")
    episode = _number(payload.get("episode"), low=0)
    step = _number(payload.get("step"), low=0)
    if not episode.is_integer() or not step.is_integer():
        raise ValueError("Body episode and step must be integers")
    epoch = payload.get("epoch") or f"legacy-episode-{int(episode)}"
    return body_observation({
        "id": f"sample-{int(step)}", "epoch": epoch, "organ_epoch": payload.get("organ_epoch"), "source": "flybody_sensor",
        "observed_at": payload.get("ts"), "sim_time_s": payload.get("sim_time_s"),
        "xy_cm": payload.get("fly_xy"),
    }, now=now)


def fresh_homeostasis_channels(channels, updated_at, *, now=None):
    """Historical/unknown-age pressures are context, never motor input."""
    now = time.time() if now is None else now
    try:
        date = datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
        if date.tzinfo is None:
            raise ValueError("Timezone is required")
        age = now - date.timestamp()
        fresh = -2 <= age <= 180
    except (TypeError, ValueError, OverflowError):
        fresh, age = False, None
    return ({k: _number(v, low=0, high=1) if fresh else 0.0 for k, v in channels.items()},
            {"input_state": "current" if fresh else "historical_not_driving", "age_seconds": age})


class EmbodiedContinuity:
    """One episode state machine over the existing SQLite events table.

    Construction/readback is read-only. Writes use Eve's writer lock and one
    transaction. Pending actions survive restart and must never be re-executed
    automatically: an uncertain dispatch is closed as interrupted instead.
    """

    def __init__(self, database, *, synthetic=False, clock=time.time):
        if not isinstance(synthetic, bool):
            raise ValueError("synthetic must be a Boolean")
        self.database = Path(database)
        self.synthetic = synthetic
        self.clock = clock

    @contextmanager
    def _transaction(self):
        eve_db.initialize_database(self.database)
        with eve_db.single_writer_lock(self.database):
            with eve_db.connect_database(self.database) as conn:
                conn.execute("BEGIN IMMEDIATE")
                yield conn
                conn.commit()

    def _get(self, conn, action_id, phase):
        row = conn.execute(
            "SELECT payload_json FROM events WHERE id = ? AND stream = ?",
            (f"embodied:{action_id}:{phase}", STREAM),
        ).fetchone()
        if row is None:
            return None
        data = json.loads(row[0])
        if data.get("schema_id") != SCHEMA or data.get("synthetic") is not self.synthetic:
            raise ValueError("Episode provenance mismatch")
        return data

    def _insert(self, conn, action_id, phase, payload):
        record = dict(payload, schema_id=SCHEMA, action_id=action_id,
                      synthetic=self.synthetic, recorded_at=self.clock())
        conn.execute(
            """INSERT INTO events (id,created_at,source,actor,kind,stream,subject,
            correlation_id,causation_id,schema_version,payload_json,metadata_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (f"embodied:{action_id}:{phase}",
             datetime.fromtimestamp(self.clock(), timezone.utc).isoformat(),
             "eve_embodiment", "eve", f"embodiment.{phase}", STREAM,
             "fly_body_brain", action_id, f"embodied:{action_id}:planned",
             1, _json(record), "{}"),
        )
        return record

    def records(self, phase="observed", *, limit=200):
        if phase not in {"planned", "dispatched", "observed"}:
            raise ValueError("Unknown episode phase")
        if not self.database.exists():
            return []
        # A read must not initialize, reconcile, mirror, or modify Eve state.
        with eve_db.connect_database(self.database, read_only=True) as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='events'").fetchone():
                return []
            rows = conn.execute(
                "SELECT payload_json FROM events WHERE stream=? AND kind=? "
                "AND json_valid(payload_json) "
                "AND json_extract(payload_json,'$.schema_id')=? "
                "AND json_type(payload_json,'$.synthetic')=? "
                "ORDER BY rowid DESC LIMIT ?",
                (STREAM, f"embodiment.{phase}", SCHEMA, "true" if self.synthetic else "false",
                 max(1, min(int(limit), 2000))),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def predictions(self, actions):
        actions = [_identifier(a) for a in actions]
        samples = {a: [] for a in actions}
        for row in self.records(limit=2000):
            a = row.get("action")
            if a in samples and row.get("learning_eligible") is True and len(samples[a]) < 8:
                samples[a].append(row["measured_speed_cm_s"])
        result = {}
        for action, values in samples.items():
            forecast = (eve_predictive_dynamics.forecast_numeric(list(reversed(values)), limit=100)
                        if len(values) >= 2 else None)
            result[action] = {
                "sample_count": len(values),
                "expected_speed_cm_s": (max(0.0, forecast["prediction"]) if forecast
                                         else values[0] if values else None),
                "range_cm_s": [min(values), max(values)] if values else None,
                "estimator": "eve_predictive_dynamics",
                "selected_expert": (forecast["selected_expert"] if forecast
                                    else "single_observation_persistence" if values else None),
            }
        return result

    def choose(self, target_speed_cm_s, *, allowed_actions, proposed_action):
        """Explicit exploration then goal-conditioned measured-outcome choice.

        This is a fitted controller, not an emergent preference or neural skill.
        The goal and admitted action set are supplied by Eve's caller.
        """
        target = _number(target_speed_cm_s, low=0, high=20)
        actions = list(dict.fromkeys(_identifier(a) for a in allowed_actions))
        if not actions or len(actions) > 20 or proposed_action not in actions:
            raise ValueError("An admitted proposed action is required")
        predicted = self.predictions(actions)
        unseen = [a for a in actions if predicted[a]["sample_count"] < 2]
        if unseen:
            chosen = min(unseen, key=lambda a: (predicted[a]["sample_count"], a != proposed_action, actions.index(a)))
            basis = "bounded_exploration"
        else:
            chosen = min(actions, key=lambda a: (abs(predicted[a]["expected_speed_cm_s"] - target), a != proposed_action))
            basis = "learned_consequence_prediction"
        return {"action": chosen, "proposed_action": proposed_action, "basis": basis,
                "target_speed_cm_s": target, "predictions": predicted}

    def plan(self, action, before, *, producer, target_speed_cm_s=None, action_id=None, actuation=None):
        action = _identifier(action)
        producer = _identifier(producer)
        action_id = _identifier(action_id or str(uuid.uuid4()))
        before = body_observation(before, now=self.clock())
        target = None if target_speed_cm_s is None else _number(target_speed_cm_s, low=0, high=20)
        if actuation is not None:
            if not isinstance(actuation, dict) or set(actuation) != {"channels", "hold_ticks"}:
                raise ValueError("Expected exact actuation fields")
            channels = actuation["channels"]
            ticks = _number(actuation["hold_ticks"], low=1, high=3600)
            if not isinstance(channels, dict) or len(channels) > 20 or not ticks.is_integer():
                raise ValueError("Invalid actuation vector")
            actuation = {"channels": {_identifier(k): _number(v, low=0, high=1) for k, v in channels.items()},
                         "hold_ticks": int(ticks)}
        payload = {"action": action, "before": before, "producer": producer,
                   "target_speed_cm_s": target, "prediction": self.predictions([action])[action],
                   "actuation": actuation}
        with self._transaction() as conn:
            prior = self._get(conn, action_id, "planned")
            if prior:
                if any(prior.get(k) != payload[k] for k in ("action", "before", "producer", "target_speed_cm_s", "actuation")):
                    raise ValueError("Conflicting action identity")
                return prior
            return self._insert(conn, action_id, "planned", payload)

    def dispatched(self, action_id, *, receipt_id, backend):
        action_id = _identifier(action_id)
        payload = {"receipt_id": _identifier(receipt_id), "backend": _identifier(backend)}
        with self._transaction() as conn:
            planned = self._get(conn, action_id, "planned")
            if not planned:
                raise ValueError("Prediction must precede dispatch")
            if self._get(conn, action_id, "observed"):
                raise ValueError("Episode is already closed")
            existing = self._get(conn, action_id, "dispatched")
            if existing:
                if any(existing[k] != v for k, v in payload.items()):
                    raise ValueError("Conflicting dispatch receipt")
                return existing
            return self._insert(conn, action_id, "dispatched", payload)

    def observe(self, action_id, after, *, confounded=True):
        action_id = _identifier(action_id)
        if not isinstance(confounded, bool):
            raise ValueError("confounded must be a Boolean")
        after = body_observation(after, now=self.clock())
        with self._transaction() as conn:
            existing = self._get(conn, action_id, "observed")
            if existing:
                if existing.get("after") != after or existing.get("confounded") is not confounded:
                    raise ValueError("Conflicting outcome for closed episode")
                return existing
            planned = self._get(conn, action_id, "planned")
            dispatch = self._get(conn, action_id, "dispatched")
            if not planned or not dispatch:
                raise ValueError("A matching dispatch receipt is required")
            before = planned["before"]
            if not confounded and before["epoch"].startswith("legacy-episode-"):
                raise ValueError("Legacy body epochs cannot provide learning evidence")
            elapsed = after["sim_time_s"] - before["sim_time_s"]
            if (after["epoch"] != before["epoch"] or after["id"] == before["id"]
                    or after.get("organ_epoch") != before.get("organ_epoch")
                    or after["observed_at"] <= dispatch["recorded_at"] or elapsed <= 0
                    or after["observed_at"] - before["observed_at"] > 180):
                raise ValueError("Observation does not close this action's time/epoch")
            # Same sensor sample cannot be used to award two actions credit.
            other = conn.execute(
                "SELECT 1 FROM events WHERE stream=? AND kind='embodiment.observed' "
                "AND json_extract(payload_json,'$.after.id')=? "
                "AND json_extract(payload_json,'$.after.epoch')=? "
                "AND json_type(payload_json,'$.synthetic')=? LIMIT 1",
                (STREAM, after["id"], after["epoch"], "true" if self.synthetic else "false"),
            ).fetchone()
            if other:
                raise ValueError("Body sample already attributed to another action")
            # Displacement speed is not path length (circling may net to zero).
            speed = math.dist(before["xy_cm"], after["xy_cm"]) / elapsed
            if speed > 100:
                raise ValueError("Implausible pose discontinuity")
            prediction = planned["prediction"]["expected_speed_cm_s"]
            payload = {
                "action": planned["action"], "producer": planned["producer"],
                "actuation": planned.get("actuation"), "backend": dispatch["backend"],
                "before": before, "after": after, "receipt_id": dispatch["receipt_id"],
                "status": "observed", "measurement": "net_displacement_per_sim_second",
                "measured_speed_cm_s": speed, "prediction": planned["prediction"],
                "prediction_error_cm_s": None if prediction is None else abs(speed - prediction),
                "confounded": confounded, "learning_eligible": not confounded,
                "target_speed_cm_s": planned["target_speed_cm_s"],
                "causal_identification": "not_established",
            }
            return self._insert(conn, action_id, "observed", payload)

    def interrupt(self, action_id, *, reason="restart_or_uncertain_dispatch"):
        action_id = _identifier(action_id)
        reason = _identifier(reason)
        with self._transaction() as conn:
            if not self._get(conn, action_id, "planned"):
                raise ValueError("Unknown action")
            existing = self._get(conn, action_id, "observed")
            if existing:
                return existing
            return self._insert(conn, action_id, "observed", {
                "status": "interrupted", "reason": reason, "learning_eligible": False,
            })

    def recover_pending(self):
        """Close uncertain prior attempts without repeating a physical action.

        Call only after acquiring the body's exclusive runner lease.
        """
        closed = []
        for row in self.records("planned", limit=2000):
            with eve_db.connect_database(self.database, read_only=True) as conn:
                terminal = self._get(conn, row["action_id"], "observed")
            if terminal is None:
                closed.append(self.interrupt(row["action_id"]))
        return closed

    def memory_items(self, query, *, limit=2):
        # Historical physical evidence stays quiet unless relevant. No "feel",
        # notice/reason prose, identity text, or hidden evaluator data is copied.
        if self.synthetic or not set(re.findall(r"[a-z]+", str(query).lower())) & {
            "fly", "body", "embodied", "embodiment", "movement", "walking", "walk", "motor",
        }:
            return []
        items = []
        for row in self.records():
            if row.get("status") != "observed":
                continue
            age = max(0, self.clock() - row["after"]["observed_at"])
            items.append({
                "id": f"embodied:{row['action_id']}", "source": "embodied_observation",
                "title": "Recorded simulated-body consequence",
                "text": (f"Historical body observation, {age:.0f} seconds old: action {row['action']} "
                         f"from {row['producer']}; measured net displacement speed "
                         f"{row['measured_speed_cm_s']:.3f} cm/s. "
                         f"Confounded={row['confounded']}; prediction error={row['prediction_error_cm_s']}. "
                         "This is measured simulation evidence, not current health or felt experience."),
                "confidence": 75, "relevance_score": 10.0,
            })
            if len(items) >= max(1, min(limit, 6)):
                break
        return items
