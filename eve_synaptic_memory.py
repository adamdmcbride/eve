"""Fly-inspired, local three-factor plasticity for the existing body organ.

This is an engineered rate-model rule, not a reconstruction of synaptic
biochemistry or a consciousness measure. Fixed anatomical connections provide
the sparse features; only the nominated KC->MBON weights may change. Numpy is
loaded on construction so ordinary Eve imports acquire no new dependency.
"""

import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import zipfile


SCHEMA = "eve.fly_synapses.v1"


def _finite(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Expected a numeric measurement")
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError("Measurement outside bounds")
    return float(value)


def measured_reinforcement(food_distance, food_radius, attack_progress):
    """Arena measurements, never novelty, narration, or a model's intention.

    The thresholds are simulator interface choices, not fly physiology. A
    missing/invalid observation contributes no reward or punishment.
    """
    result = {"dopamine_reward": 0.0, "dopamine_punish": 0.0}
    try:
        distance = _finite(food_distance, 0, 1e6)
        radius = _finite(food_radius, 1e-6, 100)
        if distance < radius:
            result["dopamine_reward"] = 0.8
    except ValueError:
        pass
    try:
        if _finite(attack_progress, 0, 2) >= 0.85:
            result["dopamine_punish"] = 0.8
    except ValueError:
        pass
    return result


def conditioned_motor_reference(signals):
    """Learned approach/avoid contrast into the existing walking controller.

    No directional food localization is claimed. Positive valence means
    appetitive search; negative valence means aversive locomotion. Call only
    after current escape, feeding, and courtship reflexes have had priority.
    This fixed decoder is an interface policy; the cue/value association is
    learned, not a cue-specific if-statement.
    """
    try:
        value = _finite(signals.get("learned_valence", 0.0), -1, 1)
    except ValueError:
        return None
    if value < -0.03:
        return {"name": "conditioned_aversion", "speed": 2.5, "yaw": 0.0}
    if value > 0.03:
        return {"name": "conditioned_appetitive_search", "speed": 1.2, "yaw": 0.0}
    return None


class PlasticSynapses:
    """Local eligibility x outcome x synapse update with bounded weights.

    Reward/punishment select disjoint anatomical output compartments. A cue
    leaves a decaying eligibility trace, allowing reinforcement after the cue
    has disappeared. Opposite reinforcement restores the opposing association
    toward baseline, allowing reversal without inexorable weight collapse.
    Reset/restart clears eligibility; persisted weights are not autobiographical
    facts. All time constants below are engineering parameters in wall seconds.
    """

    TAU = 2.0
    MAX_GAP = 10.0
    RATE = 0.4
    MIN_FACTOR = 0.2

    def __init__(self, baseline, pre, reward_mask, punish_mask, *, cell_count, topology_id="isolated_fixture"):
        import numpy as np
        self.np = np
        if isinstance(cell_count, bool) or not isinstance(cell_count, int) or not 1 <= cell_count <= 1000000:
            raise ValueError("Invalid cell count")
        self.cell_count = cell_count
        if not isinstance(topology_id, str) or not 1 <= len(topology_id) <= 128:
            raise ValueError("Invalid topology identity")
        self.baseline = np.asarray(baseline, dtype=np.float32).copy()
        self.pre = np.asarray(pre)
        self.reward_mask = np.asarray(reward_mask)
        self.punish_mask = np.asarray(punish_mask)
        if (self.baseline.ndim != 1 or not 1 <= self.baseline.size <= 1000000
                or not np.isfinite(self.baseline).all()
                or not np.any(self.baseline)
                or self.pre.shape != self.baseline.shape or self.pre.dtype.kind not in "iu"
                or np.any(self.pre < 0) or np.any(self.pre >= cell_count)):
            raise ValueError("Invalid synapse topology")
        for mask in (self.reward_mask, self.punish_mask):
            if mask.shape != self.baseline.shape or mask.dtype.kind != "b":
                raise ValueError("Expected Boolean compartment masks")
        if np.any(self.reward_mask & self.punish_mask) or not self.reward_mask.any() or not self.punish_mask.any():
            raise ValueError("Reward and punishment compartments must be disjoint and nonempty")
        self.pre = self.pre.astype(np.int64, copy=True)
        self.reward_mask = self.reward_mask.copy()
        self.punish_mask = self.punish_mask.copy()
        self.factors = np.ones_like(self.baseline)
        self.trace = np.zeros(cell_count, dtype=np.float32)
        self.trace_age = np.zeros(cell_count, dtype=np.float32)
        self.last_at = None
        self.updates = 0
        self.changed = False
        self.checkpoint_state = "new_unpersisted"
        digest = hashlib.sha256()
        for array in (self.baseline, self.pre, self.reward_mask, self.punish_mask):
            digest.update(array.tobytes())
        digest.update(json.dumps([SCHEMA, cell_count, topology_id, self.TAU, self.MAX_GAP, self.RATE, self.MIN_FACTOR]).encode())
        self.fingerprint = digest.hexdigest()

    def sparse_activity(self, activity):
        """Exact top-k competition, including ties; inhibition is not learning."""
        np = self.np
        values = np.asarray(activity, dtype=np.float32)
        if values.shape != (self.cell_count,) or not np.isfinite(values).all() or np.any(values < 0) or np.any(values > 1):
            raise ValueError("Invalid measured cell activity")
        result = np.zeros_like(values)
        # Inhibition chooses competitors; it must not erase subthreshold
        # rates before the recurrent integrator can accumulate them. The
        # plasticity threshold is applied separately to the eligibility trace.
        positive = np.flatnonzero(values > 0)
        keep = max(1, int(0.05 * self.cell_count))
        winners = positive[np.argsort(-values[positive], kind="stable")[:keep]]
        result[winners] = values[winners]
        return result

    def clear_trace(self):
        self.trace[:] = 0
        self.trace_age[:] = 0
        self.last_at = None

    def step(self, activity, *, now, reward=0.0, punishment=0.0, learn=True):
        now = _finite(now, 0, 1e15)
        reward = _finite(reward, 0, 1)
        punishment = _finite(punishment, 0, 1)
        if not isinstance(learn, bool):
            raise ValueError("learn must be Boolean")
        sparse = self.sparse_activity(activity)
        np = self.np
        elapsed = 0.0 if self.last_at is None else now - self.last_at
        if elapsed < 0:
            raise ValueError("Clock moved backwards")
        gap = elapsed > self.MAX_GAP
        if not learn or gap:
            self.clear_trace()
        elif self.last_at is not None:
            self.trace *= math.exp(-elapsed / self.TAU)
            self.trace_age += elapsed
            self.trace[self.trace_age > self.MAX_GAP] = 0
        self.last_at = now
        # Reinforcement first consumes the preceding cue trace. It must not
        # reinforce neurons that only became active because of this outcome.
        if learn and not gap and elapsed > 0 and (reward or punishment):
            net = reward - punishment
            amount = 1.0 - np.exp(-self.RATE * min(elapsed, 1.0) * abs(net) * self.trace[self.pre])
            depress, restore = ((self.reward_mask, self.punish_mask) if net >= 0
                                else (self.punish_mask, self.reward_mask))
            old = self.factors.copy()
            # Symmetric bounded LTD/LTP: restoring a weak association must not
            # be arbitrarily slower just because its factor is near baseline.
            self.factors[depress] -= amount[depress] * (1.0 - self.MIN_FACTOR)
            self.factors[restore] += amount[restore] * (1.0 - self.MIN_FACTOR)
            np.clip(self.factors, self.MIN_FACTOR, 1.0, out=self.factors)
            if np.any(old != self.factors):
                self.updates += 1
                self.changed = True
        if learn:
            self.trace = np.maximum(self.trace, np.where(sparse > 0.02, sparse, 0.0))
            self.trace_age[sparse > 0.02] = 0
        return sparse

    def weights(self):
        return self.baseline * self.factors

    def readout(self, activity):
        """Current cue retrieves learned weight changes, not the recent trace."""
        np = self.np
        sparse = self.sparse_activity(activity)
        drive = sparse[self.pre] * np.abs(self.baseline)
        def score(mask):
            total = float(drive[mask].sum())
            return float((drive[mask] * (1.0 - self.factors[mask])).sum() / total) if total > 1e-9 else 0.0
        approach, avoid = score(self.reward_mask), score(self.punish_mask)
        return {"learned_approach": approach, "learned_avoidance": avoid,
                "learned_valence": approach - avoid}

    def forget(self):
        self.factors[:] = 1
        self.clear_trace()
        self.updates = 0
        self.changed = True

    def save(self, path):
        """Atomic auxiliary weight checkpoint; never persist eligibility."""
        np = self.np
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        metadata = {"schema": SCHEMA, "fingerprint": self.fingerprint, "updates": self.updates,
                    "factors_sha256": hashlib.sha256(self.factors.tobytes()).hexdigest()}
        fd, temp = tempfile.mkstemp(prefix=".synapses-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                np.savez_compressed(handle, factors=self.factors, metadata=json.dumps(metadata))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
            self.changed = False
            self.checkpoint_state = "saved"
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def restore(self, path):
        """Validate the whole checkpoint before applying any weight."""
        np = self.np
        path = Path(path)
        if not path.exists():
            self.checkpoint_state = "absent"
            return False
        try:
            if path.stat().st_size > 8_000_000:
                raise ValueError("Checkpoint too large")
            # Bound decompression as well as the outer file size.
            with zipfile.ZipFile(path) as archive:
                if sum(i.file_size for i in archive.infolist()) > 8_100_000:
                    raise ValueError("Expanded checkpoint too large")
            with np.load(path, allow_pickle=False) as data:
                if set(data.files) != {"metadata", "factors"}:
                    raise ValueError("Unknown checkpoint fields")
                metadata = json.loads(str(data["metadata"]))
                factors = data["factors"].copy()
            if (not isinstance(metadata, dict)
                    or set(metadata) != {"schema", "fingerprint", "updates", "factors_sha256"}
                    or metadata.get("schema") != SCHEMA or metadata.get("fingerprint") != self.fingerprint
                    or type(metadata.get("updates")) is not int or metadata["updates"] < 0
                    or factors.shape != self.factors.shape or factors.dtype != self.factors.dtype
                    or not np.isfinite(factors).all() or np.any(factors < self.MIN_FACTOR) or np.any(factors > 1)
                    or metadata.get("factors_sha256") != hashlib.sha256(factors.tobytes()).hexdigest()):
                raise ValueError("Incompatible or invalid checkpoint")
        except (OSError, ValueError, KeyError, TypeError, EOFError, zipfile.BadZipFile):
            self.checkpoint_state = "rejected"
            return False
        self.factors[:] = factors
        self.updates = metadata["updates"]
        self.clear_trace()
        self.changed = False
        self.checkpoint_state = "restored"
        return True
