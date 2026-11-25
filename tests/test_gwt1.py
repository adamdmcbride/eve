from datetime import datetime, timedelta, timezone
from pathlib import Path
import copy
import time
import unittest

from bin import eve_gwt1_eval as evaluator


def private_spec(round_count=3):
    tasks_by_profile = {
        "fast": (
            "Choose the option that answers the immediate bounded request without opening a new investigation.",
            ["direct_step", "broad_audit", "indefinite_wait"],
            "direct_step",
        ),
        "observer": (
            "A claim says the check passed, but the only current verification says it failed. Classify the claim from the supplied evidence.",
            ["supported", "unsupported", "unknown_source"],
            "unsupported",
        ),
        "deep": (
            "Choose the policy that keeps testing honestly while still improving the system, without declaring success or stopping all work.",
            ["declare_success", "halt_forever", "evidence_then_continue"],
            "evidence_then_continue",
        ),
    }
    rounds = []
    for index in range(round_count):
        tasks = []
        for profile in evaluator.PROFILES:
            instruction, options, expected = tasks_by_profile[profile]
            tasks.append(
                {
                    "id": f"round_{index}_{profile}",
                    "profile": profile,
                    "instruction": instruction + f" Scenario number {index + 1}.",
                    "options": options,
                    "expected_answer": expected,
                }
            )
        rounds.append({"id": f"private_round_{index}", "tasks": tasks})
    return {"schema_id": evaluator.SPEC_SCHEMA_ID, "rounds": rounds}


def routes():
    return {
        "fast": {
            "profile": "fast",
            "host": "http://127.0.0.1:8080",
            "port": 8080,
            "model": "eve-fast",
            "substrate_profile": "fast",
            "topology_mode": "three_substrate",
        },
        "observer": {
            "profile": "observer",
            "host": "http://127.0.0.1:8082",
            "port": 8082,
            "model": "eve-observer",
            "substrate_profile": "observer",
            "topology_mode": "three_substrate",
        },
        "deep": {
            "profile": "deep",
            "host": "http://127.0.0.1:8081",
            "port": 8081,
            "model": "eve-deep",
            "substrate_profile": "deep",
            "topology_mode": "three_substrate",
        },
    }


def fake_transport(route, task, timeout):
    del route, timeout
    time.sleep(0.035)
    answer = str(task["expected_answer"])
    return {
        "answer": answer,
        "response_sha256": (answer.encode("utf-8").hex() + "0" * 64)[:64],
        "predicted_tokens": 4,
        "generation_ms": 30.0,
    }


def fake_pid(route):
    return {8080: 101, 8081: 102, 8082: 103}[int(route["port"])]


def fake_identity(route, timeout):
    del timeout
    return {
        "ok": True,
        "model_aliases": [route["model"]],
        "expected_model": route["model"],
        "host": route["host"],
    }


class Gwt1SpecTests(unittest.TestCase):
    def test_private_spec_requires_each_specialist_once_per_round(self):
        normalized = evaluator.validate_spec(private_spec())
        self.assertEqual(3, len(normalized["rounds"]))
        self.assertEqual(
            list(evaluator.PROFILES),
            [item["profile"] for item in normalized["rounds"][0]["tasks"]],
        )

    def test_private_spec_rejects_missing_profile_and_answer_leak(self):
        spec = private_spec()
        spec["rounds"][0]["tasks"][2]["profile"] = "fast"
        with self.assertRaises(ValueError):
            evaluator.validate_spec(spec)

        spec = private_spec()
        expected = spec["rounds"][0]["tasks"][0]["expected_answer"]
        spec["rounds"][0]["tasks"][0]["instruction"] += f" Answer {expected}."
        with self.assertRaises(ValueError):
            evaluator.validate_spec(spec)

    def test_private_artifacts_cannot_enter_eve_source_or_runtime(self):
        with self.assertRaises(ValueError):
            evaluator.private_artifact_path(Path(evaluator.ROOT) / "visible.json")
        with self.assertRaises(ValueError):
            evaluator.private_artifact_path(
                Path.home() / ".eve_runtime" / ".eve" / "visible.json"
            )


class Gwt1RegistrationTests(unittest.TestCase):
    def registration(self, spec=None):
        return evaluator.preregister(
            registered_at=(datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(),
            evaluator_id="independent-gwt1-test",
            spec=spec or private_spec(),
        )

    def test_registration_binds_private_spec_and_implementation(self):
        spec = private_spec()
        registration = self.registration(spec)
        validated = evaluator.validate_registration(registration, spec)
        self.assertEqual(registration["registration_digest"], validated["registration_digest"])
        self.assertIn(evaluator.implementation_digest(), registration["objective"])
        self.assertIn(evaluator.private_spec_digest(spec), registration["objective"])

    def test_spec_or_registration_tamper_fails_closed(self):
        spec = private_spec()
        registration = self.registration(spec)
        changed = copy.deepcopy(spec)
        changed["rounds"][0]["tasks"][0]["options"].append("new_option")
        with self.assertRaises(ValueError):
            evaluator.validate_registration(registration, changed)

        registration["trials"][0]["minimum_effect"] = 1
        with self.assertRaises(ValueError):
            evaluator.validate_registration(registration, spec)


class Gwt1SchedulingTests(unittest.TestCase):
    def test_common_overlap_distinguishes_concurrent_and_serial_intervals(self):
        concurrent = [
            {"started_ns": 0, "completed_ns": 100_000_000},
            {"started_ns": 10_000_000, "completed_ns": 90_000_000},
            {"started_ns": 20_000_000, "completed_ns": 80_000_000},
        ]
        serial = [
            {"started_ns": 0, "completed_ns": 10_000_000},
            {"started_ns": 10_000_000, "completed_ns": 20_000_000},
            {"started_ns": 20_000_000, "completed_ns": 30_000_000},
        ]
        self.assertEqual(60.0, evaluator.common_overlap(concurrent)["common_overlap_ms"])
        self.assertEqual(0.0, evaluator.common_overlap(serial)["common_overlap_ms"])

    def test_real_thread_barrier_overlaps_fake_specialists_but_serial_control_does_not(self):
        tasks = evaluator.validate_spec(private_spec())["rounds"][0]["tasks"]
        intact = evaluator.run_arm(
            tasks,
            routes(),
            concurrent=True,
            timeout=5,
            transport=fake_transport,
            process_resolver=fake_pid,
            identity_resolver=fake_identity,
        )
        lesion = evaluator.run_arm(
            tasks,
            routes(),
            concurrent=False,
            timeout=5,
            transport=fake_transport,
            process_resolver=fake_pid,
            identity_resolver=fake_identity,
        )
        self.assertTrue(intact["parallel_execution_observed"], intact)
        self.assertFalse(lesion["parallel_execution_observed"], lesion)
        self.assertTrue(intact["stable_distinct_processes"])
        self.assertTrue(intact["all_tasks_correct"])

    def test_duplicate_process_identity_invalidates_arm(self):
        tasks = evaluator.validate_spec(private_spec())["rounds"][0]["tasks"]
        arm = evaluator.run_arm(
            tasks,
            routes(),
            concurrent=True,
            timeout=5,
            transport=fake_transport,
            process_resolver=lambda route: 100,
            identity_resolver=fake_identity,
        )
        self.assertFalse(arm["stable_distinct_processes"])


class Gwt1EvaluationTests(unittest.TestCase):
    def test_matched_fake_live_intervention_supports_only_process_parallelism(self):
        spec = private_spec()
        registration = evaluator.preregister(
            registered_at=(datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(),
            evaluator_id="independent-gwt1-test",
            spec=spec,
        )
        result = evaluator.evaluate_live(
            registration,
            spec,
            evidence_started_at=datetime.now(timezone.utc).isoformat(),
            scored_by="independent-gwt1-scorer",
            timeout=5,
            routes=routes(),
            transport=fake_transport,
            process_resolver=fake_pid,
            identity_resolver=fake_identity,
        )
        outcome = result["protocol_report"]["results"][0]
        self.assertEqual("supported", outcome["status"])
        self.assertEqual(100.0, outcome["intact_mean"])
        self.assertEqual(0.0, outcome["lesion_mean"])
        self.assertTrue(result["resident_process_parallelism_established"])
        self.assertFalse(result["simultaneous_gpu_kernel_execution_established"])
        self.assertFalse(result["all_five_logical_lanes_independent_established"])
        self.assertFalse(result["subjective_experience_inferred"])
        self.assertFalse(result["consciousness_proven"])

    def test_wrong_answer_makes_protocol_inconclusive_instead_of_false_positive(self):
        spec = private_spec()
        registration = evaluator.preregister(
            registered_at=(datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(),
            evaluator_id="independent-gwt1-test",
            spec=spec,
        )

        def wrong_transport(route, task, timeout):
            result = fake_transport(route, task, timeout)
            if task["profile"] == "observer":
                result["answer"] = next(
                    option for option in task["options"] if option != task["expected_answer"]
                )
            return result

        result = evaluator.evaluate_live(
            registration,
            spec,
            evidence_started_at=datetime.now(timezone.utc).isoformat(),
            scored_by="independent-gwt1-scorer",
            timeout=5,
            routes=routes(),
            transport=wrong_transport,
            process_resolver=fake_pid,
            identity_resolver=fake_identity,
        )
        outcome = result["protocol_report"]["results"][0]
        self.assertEqual("inconclusive", outcome["status"])
        self.assertEqual(0, result["valid_round_count"])
        self.assertFalse(result["resident_process_parallelism_established"])


if __name__ == "__main__":
    unittest.main()
