"""Public mechanistic controls; no live Eve state, model, or organ calls."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from eve_synaptic_memory import PlasticSynapses, conditioned_motor_reference, measured_reinforcement

try:
    import numpy as np
except ImportError:
    np = None


@unittest.skipIf(np is None, "Optional fly numpy environment required")
class SynapticMemoryTests(unittest.TestCase):
    def model(self):
        return PlasticSynapses(np.ones(40, dtype=np.float32), np.tile(np.arange(20), 2),
            np.array([True]*20 + [False]*20), np.array([False]*20 + [True]*20), cell_count=20)

    def cue(self, cell=0):
        a = np.zeros(20, dtype=np.float32)
        a[cell] = 0.8
        return a

    def teach(self, model, *, punishment=0, reward=0, start=0, delay=1, cell=0, learn=True):
        model.clear_trace()
        model.step(self.cue(cell), now=start, learn=learn)
        model.step(self.cue()*0, now=start+delay, punishment=punishment, reward=reward, learn=learn)

    def test_delayed_outcome_changes_only_preceding_cue_synapses(self):
        m = self.model()
        self.teach(m, punishment=1)
        self.assertLess(m.readout(self.cue())["learned_valence"], -0.03)
        self.assertEqual(0, m.readout(self.cue(1))["learned_valence"])
        np.testing.assert_array_equal(m.weights()[:20], np.ones(20))
        self.assertEqual([20], np.flatnonzero(m.factors != 1).tolist())

    def test_identical_cues_without_outcomes_do_not_learn(self):
        m = self.model()
        for t in range(30): m.step(self.cue(), now=t)
        self.assertEqual(0, m.updates)
        np.testing.assert_array_equal(m.factors, np.ones(40))

    def test_eligibility_decays_and_expires(self):
        early, late, expired = self.model(), self.model(), self.model()
        self.teach(early, reward=1, delay=1)
        self.teach(late, reward=1, delay=5)
        self.teach(expired, reward=1, delay=11)
        self.assertGreater(early.readout(self.cue())["learned_valence"], late.readout(self.cue())["learned_valence"])
        self.assertEqual(0, expired.updates)

    def test_eligibility_expires_during_continuous_quiet_ticks(self):
        m = self.model()
        m.step(self.cue(), now=0)
        for t in range(1, 12): m.step(self.cue()*0, now=t)
        m.step(self.cue()*0, now=12, reward=1)
        self.assertEqual(0, m.updates)

    def test_opposite_matched_feedback_restores_instead_of_saturating_both_sides(self):
        m = self.model()
        self.teach(m, punishment=1)
        self.teach(m, reward=1, start=2)
        value = m.readout(self.cue())
        self.assertEqual(0, value["learned_avoidance"])
        self.assertGreater(value["learned_approach"], 0.03)

    def test_outcome_before_cue_does_not_learn_backward(self):
        m = self.model()
        m.step(self.cue()*0, now=0, reward=1)
        m.step(self.cue(), now=1)
        self.assertEqual(0, m.updates)

    def test_outcome_does_not_reinforce_newly_active_cells(self):
        m = self.model()
        m.step(self.cue(), now=0)
        m.step(self.cue(1), now=1, reward=1)
        self.assertEqual(0, m.readout(self.cue(1))["learned_approach"])
        self.assertGreater(m.readout(self.cue())["learned_approach"], 0)

    def test_competing_outcomes_cancel_instead_of_double_depression(self):
        m = self.model()
        self.teach(m, reward=0.8, punishment=0.8)
        self.assertEqual(0, m.updates)

    def test_feedback_reversal_changes_later_behavior(self):
        m = self.model()
        self.teach(m, punishment=1)
        self.assertEqual("conditioned_aversion", conditioned_motor_reference(m.readout(self.cue()))["name"])
        for j in range(8): self.teach(m, reward=1, start=2+j*2)
        self.assertEqual("conditioned_appetitive_search", conditioned_motor_reference(m.readout(self.cue()))["name"])

    def test_frozen_learning_preserves_retrieval_and_inhibition(self):
        m = self.model()
        self.teach(m, punishment=1)
        old = m.factors.copy()
        for j in range(5): self.teach(m, reward=1, start=2+j*2, learn=False)
        np.testing.assert_array_equal(old, m.factors)
        self.assertEqual(1, np.count_nonzero(m.sparse_activity(np.ones(20))))
        self.assertLess(m.readout(self.cue())["learned_valence"], 0)

    def test_sparse_competition_caps_tied_cells(self):
        m = self.model()
        self.assertEqual([0], np.flatnonzero(m.sparse_activity(np.ones(20))).tolist())
        self.assertEqual(0, np.count_nonzero(m.sparse_activity(np.zeros(20))))

    def test_subthreshold_rates_survive_competition_without_teaching(self):
        m = self.model()
        weak = self.cue()*0.01
        self.assertGreater(float(m.sparse_activity(weak)[0]), 0)
        m.step(weak, now=0)
        m.step(weak, now=1, reward=1)
        self.assertEqual(0, m.updates)
        self.assertEqual(0, np.count_nonzero(m.trace))

    def test_weight_signs_and_bounds_survive_repeated_learning(self):
        m = self.model()
        for t in range(500): m.step(self.cue(), now=t*0.1, reward=1)
        self.assertTrue(np.all(m.factors >= m.MIN_FACTOR))
        self.assertTrue(np.all(m.factors <= 1))
        self.assertTrue(np.all(m.weights() > 0))

    def test_invalid_input_does_not_mutate_weights_or_trace(self):
        m = self.model()
        m.step(self.cue(), now=1)
        old = m.trace.copy()
        for args in ({"now": 0}, {"now": 2, "reward": "1"}, {"now": 2, "punishment": True}, {"now": 2, "learn": "false"}):
            with self.assertRaises(ValueError): m.step(self.cue(), **args)
        with self.assertRaises(ValueError): m.step(np.full(20, np.nan), now=2)
        np.testing.assert_array_equal(old, m.trace)
        self.assertEqual(0, m.updates)

    def test_restart_retains_weights_but_not_unfinished_eligibility(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/"weights.npz"
            m = self.model()
            self.teach(m, reward=1)
            m.save(path)
            restored = self.model()
            self.assertTrue(restored.restore(path))
            np.testing.assert_array_equal(m.factors, restored.factors)
            self.assertEqual(m.readout(self.cue()), restored.readout(self.cue()))
            self.assertEqual(0, np.count_nonzero(restored.trace))
            before = restored.factors.copy()
            restored.step(self.cue()*0, now=500, punishment=1)
            np.testing.assert_array_equal(before, restored.factors)

    def test_atomic_write_failure_preserves_previous_checkpoint(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/"weights.npz"
            m = self.model(); m.save(path); before = path.read_bytes()
            self.teach(m, reward=1)
            with patch("eve_synaptic_memory.os.replace", side_effect=OSError("disk")):
                with self.assertRaises(OSError): m.save(path)
            self.assertEqual(before, path.read_bytes())
            self.assertEqual([path], list(Path(d).iterdir()))
            self.assertTrue(m.changed)

    def test_corrupt_incompatible_and_oversized_checkpoints_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/"weights.npz"
            path.write_bytes(b"broken")
            m = self.model(); self.assertFalse(m.restore(path))
            source = self.model(); source.save(path)
            m.fingerprint = "other-graph"
            self.assertFalse(m.restore(path))
            path.write_bytes(b"x"*8_000_001)
            self.assertFalse(m.restore(path))
            self.assertEqual(0, m.updates)
            self.assertEqual("rejected", m.checkpoint_state)

    def test_payload_modification_fails_checkpoint_digest(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/"weights.npz"
            m = self.model(); m.save(path)
            with np.load(path) as data:
                metadata = str(data["metadata"]); factors = data["factors"].copy()
            factors[0] = 0.5
            np.savez(path, factors=factors, metadata=metadata)
            self.assertFalse(m.restore(path))
            self.assertEqual(1, m.factors[0])

    def test_non_object_checkpoint_metadata_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/"weights.npz"
            m = self.model()
            np.savez(path, factors=m.factors, metadata="[]")
            self.assertFalse(m.restore(path))

    def test_restore_and_forget_are_explicit_and_durable(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/"weights.npz"
            m = self.model(); self.assertFalse(m.restore(path))
            self.teach(m, reward=1); m.forget(); m.save(path)
            other = self.model(); self.assertTrue(other.restore(path))
            self.assertEqual(0, other.readout(self.cue())["learned_valence"])

    def test_tick_rate_not_number_of_updates_controls_learning(self):
        def run(dt):
            m = self.model()
            for t in range(round(5/dt)+1): m.step(self.cue(), now=t*dt, reward=0.8)
            return m.readout(self.cue())["learned_valence"]
        self.assertAlmostEqual(run(0.05), run(0.025), delta=0.01)


class SynapticInterfaceTests(unittest.TestCase):
    def test_only_measured_outcomes_supply_reinforcement(self):
        self.assertEqual({"dopamine_reward": 0.8, "dopamine_punish": 0.0}, measured_reinforcement(0.1, 0.45, None))
        self.assertEqual({"dopamine_reward": 0.0, "dopamine_punish": 0.8}, measured_reinforcement(3, 0.45, 0.9))
        self.assertEqual({"dopamine_reward": 0.0, "dopamine_punish": 0.0}, measured_reinforcement(None, 0.45, None))
        self.assertNotIn("dopamine", measured_reinforcement(0, 0.45, 1))

    def test_unlearned_and_invalid_values_cannot_select_motor_behavior(self):
        for val in (0, 0.01, float("nan"), True, "-0.9", -2):
            self.assertIsNone(conditioned_motor_reference({"learned_valence": val}))


if __name__ == "__main__":
    unittest.main()
