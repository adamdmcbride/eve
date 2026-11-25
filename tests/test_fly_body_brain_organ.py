import unittest
from unittest.mock import patch

import eve


def organ_status(*, live=True, mode="signed", escape=0.0, feeding=0.0, song=0.0, novelty=0.0, stale=0.0):
    payload = {
        "live": live,
        "stale_seconds": stale,
        "mode": mode,
        "tick": 1200,
        "hz": 20.0,
        "ms_per_step": 24.0,
        "active_fraction": 0.003 if escape else 0.0,
        "state_rms": 0.01,
        "neurons": 166700,
        "edges": 25582938,
        "signals": {"escape": escape, "feeding": feeding, "legs": 0.0, "wings": 0.0, "turn_bias": 0.0, "song_pIP10": song, "kenyon_cells": novelty, "descending_all": 0.0},
        "url": "http://127.0.0.1:8790/status",
        "path": "/tmp/status.json",
    }
    return payload


class FlyBodyBrainOrganTests(unittest.TestCase):
    def test_registry_keeps_the_organ_lesionable_and_voiceless(self):
        spec = eve.ORGAN_ASSIMILATION_REGISTRY["fly_body_brain"]
        self.assertIn("fly_body_brain", eve.ORGAN_ASSIMILATION_ORDER)
        self.assertIn("never speaks", spec["authority_boundary"].lower())
        self.assertIn("lesionable", spec["authority_boundary"])

    def test_calm_live_signed_substrate_is_healthy_and_quiet(self):
        with patch.object(eve, "load_fly_body_brain_status", return_value=organ_status()):
            signal = eve.fly_body_brain_organ_signal(dict(eve.DEFAULT_CONFIG))
        self.assertEqual("healthy", signal["status"])
        self.assertEqual("ready", signal["operational_status"])
        self.assertLess(signal["pressure"], 70)

    def test_looming_escape_state_raises_pressure_into_live_thread_range(self):
        with patch.object(eve, "load_fly_body_brain_status", return_value=organ_status(escape=0.31)):
            signal = eve.fly_body_brain_organ_signal(dict(eve.DEFAULT_CONFIG))
        self.assertEqual("healthy", signal["status"])
        self.assertGreaterEqual(signal["pressure"], 70)
        self.assertIn("escape 0.310", signal["summary"])

    def test_lesioned_substrate_is_partial_and_does_not_claim_body_state(self):
        with patch.object(eve, "load_fly_body_brain_status", return_value=organ_status(mode="no_edges", escape=0.0)):
            signal = eve.fly_body_brain_organ_signal(dict(eve.DEFAULT_CONFIG))
        self.assertEqual("partial", signal["status"])
        self.assertIn("lesioned", signal["summary"])
        self.assertLess(signal["pressure"], 70)

    def test_offline_substrate_is_a_lab_organ_not_a_failure(self):
        with patch.object(eve, "load_fly_body_brain_status", return_value={"live": False, "stale_seconds": None}):
            signal = eve.fly_body_brain_organ_signal(dict(eve.DEFAULT_CONFIG))
        self.assertEqual("lab_available", signal["status"])
        self.assertEqual("lab_ready", signal["operational_status"])
        self.assertFalse(signal["observation_complete"])

    def test_report_includes_the_organ_and_matched_lesion_changes_the_signal(self):
        common = dict(
            build_specialist_substrate_report=lambda *a, **k: {"substrates": []},
            load_model_watchdog_status=lambda *a, **k: {"updated_at": eve.utc_now()},
            model_lane_records=lambda *a, **k: [
                {"lane": lane, "model": f"eve-{lane}", "loaded": True, "probe_ok": True} for lane in eve.MODEL_LANE_ORDER
            ],
            governance_watcher_report=lambda *a, **k: {"generated_at": eve.utc_now(), "status": "clean", "total_warnings": 0, "blocking_warnings": 0},
            load_capability_intelligence=lambda *a, **k: {},
        )
        results = {}
        for label, status in [("intact", organ_status(escape=0.31)), ("lesioned", organ_status(mode="no_edges", escape=0.0))]:
            with patch.multiple(eve, load_fly_body_brain_status=lambda *a, _s=status, **k: _s, **common):
                report = eve.build_organ_assimilation_report(dict(eve.DEFAULT_CONFIG), prefer_runtime=False)
            results[label] = {item["id"]: item for item in report["organs"]}["fly_body_brain"]
        self.assertGreaterEqual(results["intact"]["pressure"], 70)
        self.assertLess(results["lesioned"]["pressure"], 70)
        self.assertNotEqual(results["intact"]["summary"], results["lesioned"]["summary"])

    def test_matched_replay_only_intact_organ_becomes_active_mind_thread(self):
        threads = {}
        for label, status in [("intact", organ_status(escape=0.31)), ("lesioned", organ_status(mode="no_edges", escape=0.0))]:
            with patch.object(eve, "load_fly_body_brain_status", return_value=status):
                signal = eve.fly_body_brain_organ_signal(dict(eve.DEFAULT_CONFIG))
            mind = {"organ_signals": [signal], "updated_at": eve.utc_now()}
            derived = eve.build_active_mind_live_threads(mind)
            threads[label] = [t for t in derived if str(t.get("source_id") or "") == "organ:fly_body_brain"]
        self.assertEqual(1, len(threads["intact"]))
        self.assertEqual([], threads["lesioned"])
        self.assertIn("Fly body-brain", threads["intact"][0]["title"])

    def test_rest_and_courtship_states_stay_background_but_are_named(self):
        with patch.object(eve, "load_fly_body_brain_status", return_value=organ_status(feeding=0.018)):
            rest = eve.fly_body_brain_organ_signal(dict(eve.DEFAULT_CONFIG))
        with patch.object(eve, "load_fly_body_brain_status", return_value=organ_status(song=0.075)):
            court = eve.fly_body_brain_organ_signal(dict(eve.DEFAULT_CONFIG))
        with patch.object(eve, "load_fly_body_brain_status", return_value=organ_status(novelty=0.15)):
            novel = eve.fly_body_brain_organ_signal(dict(eve.DEFAULT_CONFIG))
        self.assertIn("body mode rest", rest["summary"]); self.assertLess(rest["pressure"], 40)
        self.assertIn("body mode courtship", court["summary"]); self.assertLess(court["pressure"], 70); self.assertGreater(court["pressure"], 40)
        self.assertIn("body mode novelty", novel["summary"]); self.assertLess(novel["pressure"], 70)

    def test_active_mind_merge_keeps_current_organ_signal_not_stale_previous(self):
        with patch.object(eve, "load_fly_body_brain_status", return_value=organ_status(escape=0.31)):
            stale = eve.fly_body_brain_organ_signal(dict(eve.DEFAULT_CONFIG))
        with patch.object(eve, "load_fly_body_brain_status", return_value=organ_status()):
            current = eve.fly_body_brain_organ_signal(dict(eve.DEFAULT_CONFIG))
        previous = {"organ_signals": [stale], "updated_at": eve.utc_now()}
        now = {"organ_signals": [current], "updated_at": eve.utc_now()}
        merged = eve.merge_active_mind(previous, now)
        fly = [s for s in merged["organ_signals"] if s["id"] == "fly_body_brain"]
        self.assertEqual(1, len(fly))
        self.assertLess(fly[0]["pressure"], 70)
        self.assertNotIn("escape 0.310", fly[0]["summary"])

    def test_fly_probe_actions_are_registered_as_bounded_free_run_actions(self):
        for action in eve.FLY_PROBE_ACTIONS:
            self.assertIn(action, eve.AUTONOMY_FREE_RUN_ACTIONS)
            self.assertIn(action, eve.AUTONOMY_FREE_RUN_SYSTEM_TOUCH_ACTIONS)
            self.assertEqual("fly", eve.AUTONOMY_FREE_RUN_ACTION_FAMILIES[action])
            self.assertIn(action, eve.DEVELOPMENTAL_CYCLE_SAFE_ACTIONS)

    def test_fly_probe_runner_parses_probe_json_and_verifies(self):
        import subprocess as sp, tempfile
        with tempfile.TemporaryDirectory() as lab:
            (eve.Path(lab) / "fly_probe.py").write_text("print('x')\n")
            fake = sp.CompletedProcess(args=[], returncode=0, stdout='{"ok": true, "summary": "Lesion probe: pass.", "evidence": {"signed": {"escape": 0.3}}, "artifact_path": ""}\n', stderr="")
            with patch.object(eve.subprocess, "run", return_value=fake):
                result = eve.run_bounded_fly_probe("fly_lesion_probe", {"fly_lab_path": lab}, source="test")
            self.assertTrue(result["executed"]); self.assertTrue(result["ok"]); self.assertEqual("lesion", result["probe"])
            self.assertEqual({"signed": {"escape": 0.3}}, result["evidence"])
            ok, detail = eve.operational_action_verification("fly_lesion_probe", result)
            self.assertTrue(ok); self.assertIn("Lesion probe", detail)
        missing = eve.run_bounded_fly_probe("fly_attack_probe", {"fly_lab_path": "/nonexistent"}, source="test")
        self.assertFalse(missing["executed"]); self.assertFalse(missing["ok"])


if __name__ == "__main__":
    unittest.main()
