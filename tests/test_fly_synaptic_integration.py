"""Optional local fly integration; no network or incumbent state writes.

Uses the real anatomical edge map, with a controlled KC activity fixture to
isolate the organ update contract. The separate canary drives sensory neurons.
"""
import ast
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from eve_synaptic_memory import conditioned_motor_reference

try:
    import numpy as np
    import pandas
    import scipy
except ImportError:
    np = None

ROOT = Path(os.environ.get("EVE_FLY_ROOT", Path.home()/"Documents/eve-fly"))


def body_decoder():
    # Execute the exact production function without starting TF, rendering,
    # opening windows or importing body_loop's heavyweight policy loader.
    tree = ast.parse((ROOT/"body_loop.py").read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "behavior_from_signals")
    namespace = {"np": np, "conditioned_motor_reference": conditioned_motor_reference}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(ROOT/"body_loop.py"), "exec"), namespace)
    return namespace[fn.name]


@unittest.skipUnless(np is not None and (ROOT/"graph/W_signed.npz").exists(), "Optional fly data/environment absent")
class FlySynapticIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.now = 0.0
        with patch.object(sys, "path", [str(ROOT), *sys.path]):
            spec = importlib.util.spec_from_file_location("synaptic_test_organ", ROOT/"fly_organ.py")
            mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
            cls.organ = mod.FlyOrgan(state_dir=cls.tmp.name, clock=lambda: cls.now)
        if cls.organ.synaptic_error:
            raise AssertionError(cls.organ.synaptic_error)
        # Choose a KC represented in both opponent output compartments.
        syn = cls.organ.synapses
        cls.cell = int(np.intersect1d(syn.pre[syn.reward_mask], syn.pre[syn.punish_mask])[0])
        cls.decode = staticmethod(body_decoder())

    @classmethod
    def tearDownClass(cls):
        cls.organ.ledger.close()
        cls.tmp.cleanup()

    def setUp(self):
        self.organ.set_mode("signed"); self.organ.reset(); self.organ.forget(); self.organ.set_plasticity(True)
        type(self).now += 20

    def source(self, channels, source="body_senses", ttl=5):
        return self.organ.set_channels(channels, source=source, source_epoch="fixture",
            command_id=str(type(self).now), ttl_s=ttl, expected_epoch=self.organ.arbiter.epoch)

    def tick(self, active=True, delay=1):
        type(self).now += delay
        def step(_drive):
            self.organ.fs.state[:] = 0
            if active: self.organ.fs.state[self.organ.kc[self.cell]] = 0.8
        with patch.object(self.organ.fs, "step", side_effect=step): self.organ.step()

    def test_real_edge_update_and_body_decoder_use_the_same_learned_value(self):
        baseline = self.organ.fs.W.data.copy()
        self.tick(); self.source({"dopamine_punish": 1}); self.tick(active=False)
        self.assertGreater(self.organ.synapses.updates, 0)
        changed = np.flatnonzero(baseline != self.organ.fs.W.data)
        self.assertTrue(set(changed).issubset(set(self.organ.kc_mbon_pos)))
        self.source({}); self.tick()
        signals = self.organ.status()["signals"]
        self.assertEqual("conditioned_aversion", self.decode(signals)["name"])
        self.organ.forget()
        self.assertNotEqual("conditioned_aversion", self.decode(self.organ.status()["signals"])["name"])

    def test_novelty_and_model_generated_rewards_do_not_train(self):
        self.tick(); self.source({"dopamine": 1}); self.tick()
        self.assertEqual(0, self.organ.synapses.updates)
        self.source({"dopamine_punish": 1}, source="mind"); self.tick()
        self.assertEqual(0, self.organ.synapses.updates)

    def test_fresh_organ_restores_weights_without_pending_eligibility(self):
        self.tick(); self.source({"dopamine_punish": 1}); self.tick(active=False)
        self.organ.checkpoint_synapses()
        factors = self.organ.synapses.factors.copy()
        fresh = type(self.organ)(state_dir=self.tmp.name, clock=lambda: type(self).now)
        try:
            self.assertIsNone(fresh.synaptic_error)
            self.assertEqual("restored", fresh.synapses.checkpoint_state)
            np.testing.assert_array_equal(factors, fresh.synapses.factors)
            np.testing.assert_array_equal(fresh.synapses.weights(), fresh.fs.W.data[fresh.kc_mbon_pos])
            self.assertFalse(fresh.synapses.trace.any())
            self.assertEqual({}, fresh.arbiter.snapshot()["contributors"])
            fresh.fs.state[fresh.kc[self.cell]] = 0.8
            self.assertEqual("conditioned_aversion", self.decode(fresh.status()["signals"])["name"])
        finally:
            fresh.ledger.close()

    def test_expired_arena_outcomes_cannot_teach(self):
        self.tick(); self.source({"dopamine_punish": 1}, ttl=0.5); self.tick(delay=1)
        self.assertEqual(0, self.organ.synapses.updates)

    def test_reset_and_lesion_clear_pending_eligibility(self):
        for reset in (self.organ.reset, lambda: self.organ.set_mode("no_edges")):
            self.organ.set_mode("signed"); self.tick(); reset()
            self.source({"dopamine_punish": 1}); self.tick(active=False)
            self.assertEqual(0, self.organ.synapses.updates)
            self.assertEqual(0, self.organ.status()["signals"]["learned_valence"])

    def test_frozen_learning_does_not_disable_sparse_competition(self):
        self.organ.set_plasticity(False)
        self.organ.fs.state[self.organ.kc] = 0.8
        with patch.object(self.organ.fs, "step"):
            type(self).now += 1; self.organ.step()
        self.assertEqual(int(len(self.organ.kc)*0.05), np.count_nonzero(self.organ.fs.state[self.organ.kc]))
        with self.assertRaises(ValueError): self.organ.set_plasticity("false")

    def test_current_reflex_overrides_learned_behavior(self):
        sig = {"escape": 0, "feeding": 0, "turn_bias": 0, "learned_valence": -0.5}
        self.assertEqual("escape_run", self.decode(dict(sig, escape=0.3))["name"])
        self.assertEqual("rest_feed", self.decode(dict(sig, feeding=0.1))["name"])

    def test_frozen_readout_is_not_available_in_lesioned_mode(self):
        self.tick(); self.source({"dopamine_punish": 1}); self.tick(active=False)
        self.organ.set_mode("no_edges"); self.tick()
        self.assertEqual(0, self.organ.status()["signals"]["learned_valence"])

    def test_body_producer_calls_measured_reward_helper(self):
        tree = ast.parse((ROOT/"body_live.py").read_text())
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
        self.assertTrue(any(n.func.id == "measured_reinforcement" for n in calls))
        self.assertNotIn('drives["dopamine"]', (ROOT/"body_live.py").read_text())

    def test_transient_checkpoint_failure_can_recover_without_erasing_weights(self):
        self.tick(); self.source({"dopamine_punish": 1}); self.tick(active=False)
        old = self.organ.synapses.factors.copy()
        self.organ.synaptic_error = "checkpoint_write_OSError"
        self.organ.checkpoint_synapses()
        self.assertIsNone(self.organ.synaptic_error)
        np.testing.assert_array_equal(old, self.organ.synapses.factors)


if __name__ == "__main__":
    unittest.main()
