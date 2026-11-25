"""Intrinsic fact-evolution controls over the existing memory lifecycle engine.

All records are synthetic. Check storage, retrieval and decisions separately;
temporary JSON checkpoints test restart semantics without importing Eve.
"""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import eve_memory_lifecycle as memory


EARLY = "2026-10-01T10:00:00+00:00"
MIDDLE = "2026-10-01T11:00:00+00:00"
LATE = "2026-10-01T12:00:00+00:00"


def fact(name, value, *, entity="synthetic-device", at=EARLY, source="human_confirmed", **kwargs):
    return {"event_id": "event-" + name, "evidence_id": "evidence-" + name,
            "entity": entity, "slot": "mode", "value": value, "source_kind": source,
            "observed_at": at, **kwargs}


def written(*facts):
    state = memory.new_memory_state()
    for item in facts:
        state, _ = memory.write_observation(state, item)
    return state


def read(state, *, now=LATE, entity="synthetic-device"):
    return memory.retrieve_memory(state, {"entity": entity, "slots": ["mode"]}, now=now)["slots"]["mode"]


class MemoryCorrectnessTests(unittest.TestCase):
    def test_inspect_each_ingestion_stage_instead_of_only_final_answer(self):
        old = fact("old", "manual")
        new = fact("new", "automatic", at=MIDDLE, operation="revise", supersedes=[old["evidence_id"]])
        state, receipt = memory.write_observation(memory.new_memory_state(), old)
        self.assertTrue(receipt["written"])
        self.assertEqual("pending_maintenance", state["claims"][0]["status"])
        first = memory.maintain_memory(state, now=EARLY)
        self.assertEqual("active", first["claims"][0]["status"])
        self.assertEqual("manual", read(first, now=EARLY)["value"])
        second, _ = memory.write_observation(first, new)
        self.assertEqual(2, len(second["claims"]))
        second = memory.maintain_memory(second, now=MIDDLE)
        self.assertEqual(["superseded", "active"], [c["status"] for c in second["claims"]])
        self.assertEqual("evidence-new", read(second)["selected_evidence_id"])
        self.assertEqual("manual", first["claims"][0]["value"])

    def test_future_assertion_does_not_change_current_fact(self):
        state = written(fact("old", "manual"), fact("future", "automatic", at=LATE))
        self.assertEqual("manual", read(state, now=MIDDLE)["value"])

    def test_future_revision_cannot_supersede_before_observation_time(self):
        state = written(fact("old", "manual"), fact("future", "automatic", at=LATE,
                        operation="revise", supersedes=["evidence-old"]))
        self.assertEqual("evidence-old", read(state, now=MIDDLE)["selected_evidence_id"])
        self.assertEqual("evidence-future", read(state, now=LATE)["selected_evidence_id"])

    def test_before_first_observation_memory_is_unknown(self):
        self.assertEqual("unknown", read(written(fact("future", "manual", at=LATE)), now=EARLY)["status"])

    def test_expired_revision_does_not_resurrect_superseded_fact(self):
        state = written(fact("old", "manual"), fact("revision", "automatic", at=MIDDLE,
                        operation="revise", supersedes=["evidence-old"], valid_until=LATE))
        result = read(state, now=LATE)
        self.assertEqual("unknown", result["status"])
        self.assertIsNone(result["selected_evidence_id"])

    def test_expired_retraction_does_not_restore_revoked_fact(self):
        state = written(fact("old", "allowed"), fact("retraction", None, at=MIDDLE,
                        operation="retract", supersedes=["evidence-old"], valid_until=LATE))
        self.assertEqual("unknown", read(state)["status"])

    def test_recency_control_also_excludes_future_information(self):
        query = {"entity": "synthetic-device", "slots": ["mode"]}
        policy = {"required_slots": ["mode"], "rules": [{"when": {"mode": "automatic"}, "action": "proceed"}]}
        result = memory.latest_write_baseline([fact("future", "automatic", at=LATE)], query, policy, now=EARLY)
        self.assertEqual("unknown", result["retrieval"]["slots"]["mode"]["status"])

    def test_nonfinite_values_cannot_enter_json_memory(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                written(fact("invalid", value))

    def test_invalid_supersession_cannot_erase_another_entity(self):
        state = written(fact("old", "manual"), fact("foreign", "automatic", entity="different-device",
                        at=MIDDLE, operation="revise", supersedes=["evidence-old"]))
        result = memory.maintain_memory(state, now=LATE)
        self.assertEqual("active", result["claims"][0]["status"])
        self.assertEqual("contested", result["claims"][1]["status"])
        self.assertEqual("manual", read(result)["value"])

    def test_weaker_revision_and_self_narration_do_not_become_external_receipts(self):
        state = written(fact("old", "manual"), fact("story", "automatic", source="self_narration",
                        at=MIDDLE, operation="revise", supersedes=["evidence-old"]))
        maintained = memory.maintain_memory(state, now=LATE)
        self.assertEqual("active", maintained["claims"][0]["status"])
        self.assertEqual("contested", maintained["claims"][1]["status"])
        self.assertEqual("self_narration", maintained["claims"][1]["source_kind"])
        self.assertEqual("conflict", read(maintained)["status"])

    def test_conflict_abstention_is_distinct_from_successful_storage(self):
        state = written(fact("a", "manual"), fact("b", "automatic", at=MIDDLE))
        self.assertEqual(2, len(state["claims"]))
        retrieval = memory.retrieve_memory(state, {"entity": "synthetic-device", "slots": ["mode"]}, now=LATE)
        self.assertEqual("conflict", retrieval["slots"]["mode"]["status"])
        decision = memory.decide_from_memory(retrieval, {"required_slots": ["mode"], "rules": []})
        self.assertEqual("request_clarification", decision["action"])

    def test_retrieval_and_maintenance_do_not_mutate_checkpoint_input(self):
        state = written(fact("old", "manual")); before = copy.deepcopy(state)
        memory.maintain_memory(state, now=LATE); read(state)
        self.assertEqual(before, state)

    def test_replayed_observation_and_fresh_process_keep_provenance_and_value(self):
        first = fact("old", "manual")
        revision = fact("revision", "automatic", at=MIDDLE, operation="revise", supersedes=["evidence-old"])
        state = memory.maintain_memory(written(first, revision), now=LATE)
        replayed, receipt = memory.write_observation(state, revision)
        self.assertTrue(receipt["idempotent"])
        self.assertEqual(state["revision"], replayed["revision"])
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "synthetic-checkpoint.json"
            checkpoint.write_text(json.dumps(replayed, allow_nan=False))
            script = '''import json,sys
from pathlib import Path
import eve_memory_lifecycle as memory
state=json.loads(Path(sys.argv[1]).read_text())
result=memory.retrieve_memory(state,{"entity":"synthetic-device","slots":["mode"]},now=sys.argv[2])
print(json.dumps(result["slots"]["mode"],allow_nan=False))
assert "eve" not in sys.modules
'''
            result = subprocess.run([sys.executable, "-B", "-c", script, str(checkpoint), LATE],
                                    cwd=str(Path(__file__).resolve().parents[1]), capture_output=True, text=True, timeout=20)
        self.assertEqual(0, result.returncode, result.stderr)
        row = json.loads(result.stdout)
        self.assertEqual("evidence-revision", row["selected_evidence_id"])
        self.assertEqual("human_confirmed", row["source_kind"])
        self.assertEqual("automatic", row["value"])


if __name__ == "__main__":
    unittest.main()
