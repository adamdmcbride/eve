"""Source integration tests for the optional local fly workspace, no live IO."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from eve_embodiment import EmbodiedContinuity


FLY_ROOT = Path(os.environ.get("EVE_FLY_ROOT", Path.home() / "Documents" / "eve-fly"))


def load_source(name):
    spec = importlib.util.spec_from_file_location(f"test_fly_{name}", FLY_ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    with patch.object(sys, "path", [str(FLY_ROOT), *sys.path]), patch("os.makedirs"):
        spec.loader.exec_module(module)
    return module


@unittest.skipUnless((FLY_ROOT / "fly_mind.py").is_file(), "Optional fly source workspace absent")
class FlyAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = 1789236000.0
        self.store = EmbodiedContinuity(Path(self.tmp.name) / "state.sqlite3", clock=lambda: self.now)
        self.fly = load_source("fly_mind")
        self.fly.MIND_DRIVE = str(Path(self.tmp.name) / "drive.json")
        self.patchers = [patch.object(self.fly, "continuity_store", return_value=self.store),
                         patch.object(self.fly, "habituated", return_value=[]),
                         patch("eve_embodiment.time.time", side_effect=lambda: self.now)]
        for p in self.patchers:
            p.start()
            self.addCleanup(p.stop)

    def sensor(self, step=100, x=0):
        return {"epoch": "body-process-1", "organ_epoch": "organ-process-1", "episode": 1, "step": step, "sim_time_s": self.now,
                "ts": self.now, "fly_xy": [x, 0]}

    def act(self, ack=None):
        with patch.object(self.fly, "read_json", return_value=self.sensor()), patch.object(
            self.fly, "post_drive", side_effect=lambda *args, **kwargs: ack if ack is not None else {
                "ok": True, "tick": 120, "organ_epoch": "organ-process-1", "revision": 1,
                "source": "mind", "source_epoch": self.fly.SOURCE_EPOCH,
                "command_id": kwargs["command_id"], "replayed": False}
        ) as post:
            result = self.fly.act({"intention": "explore", "duration_s": 10})
        return result, post

    def test_live_adapter_records_measurement_but_not_learning_credit(self):
        result, post = self.act()
        self.assertEqual("explore", result[0])
        self.assertEqual(({"octopamine": 0.6, "dopamine": 0.3},), post.call_args.args)
        self.assertEqual("mind", post.call_args.kwargs["source"])
        self.assertEqual("organ-process-1", post.call_args.kwargs["expected_epoch"])
        self.assertEqual(10, post.call_args.kwargs["ttl_s"])
        self.assertEqual(1, len(self.store.records("planned")))
        self.assertEqual(1, len(self.store.records("dispatched")))
        self.assertEqual({"channels": {"octopamine": 0.6, "dopamine": 0.3}, "hold_ticks": 200},
                         self.store.records("planned")[0]["actuation"])
        self.now += 2
        row = self.fly.settle_body_episode(self.sensor(101, x=3))
        self.assertAlmostEqual(1.5, row["measured_speed_cm_s"])
        self.assertTrue(row["confounded"])
        self.assertFalse(row["learning_eligible"])
        self.assertEqual(0, self.store.predictions(["explore"])["explore"]["sample_count"])
        self.assertTrue(self.store.memory_items("fly body"))
        self.fly.settle_body_episode(self.sensor(101, x=3))
        self.assertEqual(1, len(self.store.records()))

    def test_stale_sensor_prevents_unverifiable_action(self):
        stale = dict(self.sensor(), ts=self.now - 60)
        with patch.object(self.fly, "read_json", return_value=stale), patch.object(self.fly, "post_drive") as post:
            with self.assertRaisesRegex(ValueError, "stale"):
                self.fly.act({"intention": "explore"})
        post.assert_not_called()
        self.assertFalse(Path(self.fly.MIND_DRIVE).exists())

    def test_unsettled_action_cannot_be_overwritten(self):
        self.act()
        with self.assertRaisesRegex(RuntimeError, "previous body episode"):
            self.act()
        self.assertEqual(1, len(self.store.records("planned")))

    def test_missing_acknowledgement_is_interrupted_without_replay(self):
        for ack in ({"ok": False, "tick": 1}, {"ok": True}, {"ok": "true", "tick": 1}):
            with self.subTest(ack=ack), self.assertRaises(ValueError):
                self.act(ack)
        self.assertTrue(all(r["status"] == "interrupted" for r in self.store.records()))
        self.assertEqual([], self.store.records("dispatched"))
        self.assertFalse(Path(self.fly.MIND_DRIVE).exists())

    def test_stale_outcome_closes_attempt_without_claiming_success(self):
        self.act()
        old = self.sensor(101, x=4)
        self.now += 20
        result = self.fly.settle_body_episode(old)
        self.assertEqual("interrupted", result["status"])
        self.assertEqual([], self.store.memory_items("fly"))
        self.assertIsNone(self.fly.PENDING_EPISODE)

    def test_hold_is_not_claimed_as_executed_motor_command(self):
        with patch.object(self.fly, "post_drive") as post:
            self.fly.act({"intention": "hold"})
        post.assert_called_once_with({}, source="mind", ttl_s=1)
        self.assertEqual("not_dispatched", self.fly.LAST_DISPATCH["status"])
        self.assertEqual([], self.store.records("planned"))

    def test_organ_reset_interrupts_pending_episode(self):
        self.act()
        self.now += 2
        sample = dict(self.sensor(101, 3), organ_epoch="organ-process-2")
        self.assertEqual("interrupted", self.fly.settle_body_episode(sample)["status"])

    def test_body_restart_interrupts_pending_episode(self):
        self.act()
        self.now += 2
        sample = dict(self.sensor(101, 3), epoch="body-process-2")
        self.assertEqual("interrupted", self.fly.settle_body_episode(sample)["status"])

    def test_legacy_sensor_cannot_start_live_action(self):
        sample = dict(self.sensor(), organ_epoch=None)
        with patch.object(self.fly, "read_json", return_value=sample), patch.object(self.fly, "post_drive") as post:
            with self.assertRaisesRegex(ValueError, "epochs"):
                self.fly.act({"intention": "explore"})
        post.assert_not_called()

    def test_generated_narration_is_output_not_observation(self):
        import eve
        with patch.object(eve, "append_eve_event_ledger_event") as append:
            self.fly.ledger_event("fly_mind_tick", {"notice": "A model claim"})
            event = append.call_args.args[0]
            self.assertEqual("InterpretationEvent", event["type"])
            self.assertEqual(["self_output"], event["payload"]["tags"])
            self.fly.ledger_event("fly_mind_reflection", {"reflection": "Another model claim"})
            self.assertEqual("ReflectionEvent", append.call_args.args[0]["type"])

    def test_pressure_bridge_distinguishes_historical_state_and_operator_override(self):
        bridge = load_source("eve_pressure_bridge")
        for timestamp in (None, "2026-08-26T18:08:49+00:00"):
            channels, meta = bridge.current_pressure_channels({"resource_safety": 95}, {"updated_at": timestamp}, now=self.now)
            self.assertTrue(all(v == 0 for v in channels.values()))
            self.assertEqual("historical_not_driving", meta["input_state"])
        channels, meta = bridge.current_pressure_channels({"resource_safety": 95}, {"source": "override"}, now=self.now)
        self.assertEqual(0.95, channels["octopamine"])
        self.assertEqual("explicit_operator_override", meta["input_state"])

    def test_bridge_main_uses_expiring_input(self):
        bridge = load_source("eve_pressure_bridge")
        bridge.LOG = str(Path(self.tmp.name) / "bridge.jsonl")
        bridge.HERE = self.tmp.name
        with patch.object(sys, "argv", ["bridge", "--once"]), patch.object(
            bridge, "read_eve_pressures", return_value=({"resource_safety": 90}, {})
        ), patch.object(bridge, "post_drive", return_value={"ok": True}) as post, patch.object(
            bridge, "organ_status", return_value={"mode": "signed", "signals": {}}
        ), patch.object(bridge.time, "sleep"), patch("builtins.print"):
            bridge.main()
        self.assertEqual(100, post.call_args.kwargs["hold_ticks"])
        self.assertTrue(all(v == 0 for v in post.call_args.args[0].values()))
        self.assertEqual("historical_not_driving", json.loads(Path(bridge.LOG).read_text())["meta"]["input_state"])

@unittest.skipUnless((FLY_ROOT / 'pressure_map.py').is_file(), 'Optional fly workspace absent')
class FlySourceLeaseTests(unittest.TestCase):
    def test_kernel_lease_excludes_competitor_and_releases(self):
        pressure = load_source('pressure_map')
        with tempfile.TemporaryDirectory() as directory, patch.object(pressure, '__file__', str(Path(directory) / 'pressure_map.py')):
            with pressure.source_lease('mind'):
                with self.assertRaisesRegex(RuntimeError, 'owns the lease'):
                    with pressure.source_lease('mind'): pass
            with pressure.source_lease('mind'): pass

    def test_named_payload_carries_process_and_observation_epochs(self):
        pressure = load_source('pressure_map')
        payload = pressure.drive_payload({'dopamine': .2}, 20, source='mind',
            command_id='action-1', ttl_s=1, expected_epoch='organ-1')
        self.assertEqual('organ-1', payload['expected_epoch'])
        self.assertEqual(pressure.SOURCE_EPOCH, payload['source_epoch'])
        self.assertEqual('action-1', payload['command_id'])

    def test_missing_coherence_is_unknown_not_a_settled_measurement(self):
        pressure = load_source('pressure_map')
        self.assertEqual(0, pressure.channels_from_pressures({'resource_safety': 90})['serotonin'])


if __name__ == "__main__":
    unittest.main()
