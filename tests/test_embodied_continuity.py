import concurrent.futures
from datetime import datetime, timezone
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import eve
from eve_embodiment import EmbodiedContinuity, body_observation, flybody_sample, fresh_homeostasis_channels


class EmbodiedContinuityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "operational_state.sqlite3"
        self.now = 1789236000.0
        self.store = EmbodiedContinuity(self.db, clock=lambda: self.now)
        self.index = 0

    def sample(self, *, x=0, epoch="body-1", sim=None):
        self.index += 1
        return {"id": f"sample-{self.index}", "epoch": epoch, "source": "flybody_sensor",
                "observed_at": self.now, "sim_time_s": self.now if sim is None else sim,
                "xy_cm": [x, 0]}

    def episode(self, action="explore", speed=2, *, confounded=False, store=None):
        store = store or self.store
        before = self.sample()
        p = store.plan(action, before, producer="test_controller")
        store.dispatched(p["action_id"], receipt_id="dispatch-1", backend="test_adapter")
        self.now += 2
        return store.observe(p["action_id"], self.sample(x=speed * 2), confounded=confounded)

    def test_read_only_projection_does_not_create_database(self):
        self.assertEqual([], self.store.records())
        self.assertEqual([], self.store.memory_items("fly"))
        self.assertFalse(self.db.exists())

    def test_predict_measure_restart_and_shared_memory(self):
        for _ in range(2):
            self.episode(speed=2)
            self.episode("rest", speed=0.2)
        restarted = EmbodiedContinuity(self.db, clock=lambda: self.now)
        choice = restarted.choose(0.3, allowed_actions=["explore", "rest"], proposed_action="explore")
        self.assertEqual("rest", choice["action"])
        self.assertEqual("learned_consequence_prediction", choice["basis"])
        self.assertAlmostEqual(2, restarted.predictions(["explore"])["explore"]["expected_speed_cm_s"])
        with patch.object(eve, "OPERATIONAL_DB_PATH", self.db), patch.object(
            eve, "load_memory_retrieval_payload", return_value={"notes": []}
        ):
            memory = eve.select_conscious_memory_items("fly body walking", prefer_runtime=False)
            unrelated = eve.select_conscious_memory_items("hello", prefer_runtime=False)
        self.assertTrue(memory)
        self.assertIn("Recorded simulated-body", memory[0]["title"])
        self.assertEqual([], unrelated)
        self.assertIn("not current health", memory[0]["text"])

    def test_changed_dynamics_change_learned_choice_without_code_change(self):
        for _ in range(3):
            self.episode("explore", speed=2)
            self.episode("rest", speed=0.2)
        choose = lambda: self.store.choose(0.25, allowed_actions=["explore", "rest"], proposed_action="rest")["action"]
        self.assertEqual("rest", choose())
        for _ in range(8):
            self.episode("explore", speed=0.2)
            self.episode("rest", speed=2)
        self.assertEqual("explore", choose())

    def test_first_outcome_has_no_retrospectively_invented_prediction(self):
        a = self.episode(speed=2)
        b = self.episode(speed=3)
        self.assertIsNone(a["prediction_error_cm_s"])
        self.assertEqual(1, b["prediction_error_cm_s"])
        self.assertEqual(2, b["prediction"]["expected_speed_cm_s"])

    def test_confounded_observation_is_visible_but_never_trains(self):
        self.episode(speed=8, confounded=True)
        self.assertEqual(0, self.store.predictions(["explore"])["explore"]["sample_count"])
        self.assertIn("Confounded=True", self.store.memory_items("fly")[0]["text"])

    def test_synthetic_data_never_enters_live_memory_or_predictions(self):
        synthetic = EmbodiedContinuity(self.db, synthetic=True, clock=lambda: self.now)
        self.episode(store=synthetic)
        self.assertEqual([], self.store.memory_items("fly"))
        self.assertEqual([], synthetic.memory_items("fly"))
        self.assertEqual(0, self.store.predictions(["explore"])["explore"]["sample_count"])
        self.assertEqual(1, synthetic.predictions(["explore"])["explore"]["sample_count"])

    def test_provenance_cannot_be_changed_after_planning(self):
        p = self.store.plan("rest", self.sample(), producer="test")
        synthetic = EmbodiedContinuity(self.db, synthetic=True, clock=lambda: self.now)
        with self.assertRaisesRegex(ValueError, "provenance"):
            synthetic.dispatched(p["action_id"], receipt_id="r", backend="b")

    def test_provenance_is_filtered_before_limit(self):
        live = self.episode()
        synthetic = EmbodiedContinuity(self.db, synthetic=True, clock=lambda: self.now)
        self.episode(store=synthetic)
        self.assertEqual([live], self.store.records(limit=1))

    def test_sensor_adapter_uses_pose_not_commanded_speed(self):
        raw = {"episode": 2, "step": 100, "ts": self.now, "sim_time_s": 5,
               "fly_xy": [1, 2], "behavior": {"speed": 999}}
        sample = flybody_sample(raw, now=self.now)
        self.assertEqual([1, 2], sample["xy_cm"])
        self.assertEqual("legacy-episode-2", sample["epoch"])
        self.assertNotIn("behavior", sample)
        self.assertEqual("body-uuid", flybody_sample(dict(raw, epoch="body-uuid"), now=self.now)["epoch"])
        for changes in ({"step": 1.5}, {"episode": True}, {"ts": self.now - 11}):
            with self.assertRaises(ValueError):
                flybody_sample(dict(raw, **changes), now=self.now)

    def test_legacy_sensor_cannot_be_admitted_as_learning(self):
        p = self.store.plan("rest", self.sample(epoch="legacy-episode-0"), producer="test")
        self.store.dispatched(p["action_id"], receipt_id="r", backend="b")
        self.now += 1
        after = self.sample(epoch="legacy-episode-0")
        with self.assertRaisesRegex(ValueError, "Legacy"):
            self.store.observe(p["action_id"], after, confounded=False)
        self.assertFalse(self.store.observe(p["action_id"], after)["learning_eligible"])

    def test_old_unknown_or_future_homeostasis_is_not_motor_input(self):
        channels = {"dopamine": 0.8, "serotonin": 0.3}
        iso = lambda seconds: datetime.fromtimestamp(seconds, timezone.utc).isoformat()
        for stamp in (None, "bad", "2026-09-12T12:00:00", iso(self.now - 181), iso(self.now + 3)):
            filtered, meta = fresh_homeostasis_channels(channels, stamp, now=self.now)
            self.assertEqual({"dopamine": 0, "serotonin": 0}, filtered)
            self.assertEqual("historical_not_driving", meta["input_state"])
        filtered, meta = fresh_homeostasis_channels(channels, iso(self.now - 10), now=self.now)
        self.assertEqual(channels, filtered)
        self.assertEqual("current", meta["input_state"])

    def test_no_success_without_dispatch(self):
        p = self.store.plan("rest", self.sample(), producer="test")
        self.now += 1
        with self.assertRaisesRegex(ValueError, "dispatch"):
            self.store.observe(p["action_id"], self.sample())

    def test_restart_interrupts_pending_without_executing_or_learning(self):
        p = self.store.plan("rest", self.sample(), producer="test")
        self.store.dispatched(p["action_id"], receipt_id="r", backend="b")
        restarted = EmbodiedContinuity(self.db, clock=lambda: self.now)
        self.assertEqual(1, len(restarted.recover_pending()))
        self.assertEqual([], restarted.recover_pending())
        self.assertEqual("interrupted", restarted.records()[0]["status"])
        self.assertEqual(0, restarted.predictions(["rest"])["rest"]["sample_count"])
        self.assertEqual([], restarted.memory_items("fly"))

    def test_duplicate_outcome_is_idempotent_across_threads(self):
        p = self.store.plan("rest", self.sample(), producer="test")
        self.store.dispatched(p["action_id"], receipt_id="r", backend="b")
        self.now += 1
        after = self.sample(x=1)
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: self.store.observe(p["action_id"], after, confounded=False), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(1, len(self.store.records()))
        self.assertEqual(1, self.store.predictions(["rest"])["rest"]["sample_count"])

    def test_one_observation_cannot_credit_two_actions(self):
        before = self.sample()
        ids = [self.store.plan(a, before, producer="test")["action_id"] for a in ("rest", "explore")]
        for i in ids:
            self.store.dispatched(i, receipt_id="r", backend="b")
        self.now += 1
        after = self.sample(x=1)
        self.store.observe(ids[0], after)
        with self.assertRaisesRegex(ValueError, "already attributed"):
            self.store.observe(ids[1], after)

    def test_epoch_restart_time_reversal_and_same_sample_are_rejected(self):
        before = self.sample()
        p = self.store.plan("rest", before, producer="test")
        self.store.dispatched(p["action_id"], receipt_id="r", backend="b")
        self.now += 1
        for after in [self.sample(epoch="body-2"), self.sample(sim=before["sim_time_s"]),
                      dict(self.sample(), id=before["id"])]:
            with self.subTest(after=after), self.assertRaises(ValueError):
                self.store.observe(p["action_id"], after)
        self.assertEqual([], self.store.records())

    def test_invalid_sensor_data_is_rejected(self):
        base = self.sample()
        for changes in [{"source": "llm"}, {"observed_at": self.now-11}, {"observed_at": self.now+3},
                        {"sim_time_s": float("nan")}, {"xy_cm": [False, 0]}, {"xy_cm": [0]},
                        {"id": "unbounded prompt text"}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                body_observation(dict(base, **changes), now=self.now)

    def test_conflicting_identity_or_receipt_is_rejected(self):
        before = self.sample()
        p = self.store.plan("rest", before, producer="test", action_id="action-1")
        self.assertEqual(p, self.store.plan("rest", before, producer="test", action_id="action-1"))
        with self.assertRaises(ValueError):
            self.store.plan("explore", before, producer="test", action_id="action-1")
        self.store.dispatched(p["action_id"], receipt_id="r", backend="b")
        with self.assertRaises(ValueError):
            self.store.dispatched(p["action_id"], receipt_id="other", backend="b")


if __name__ == "__main__":
    unittest.main()
