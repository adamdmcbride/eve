from datetime import datetime, timedelta, timezone
import copy
import hashlib
import json
import unittest

import eve_broadcast_access as access
import eve_consciousness


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def state(access_scope=None, content="inspect_current_evidence"):
    scope = list(access_scope if access_scope is not None else access.CONSUMER_IDS)
    selection_material = {
        "schema_version": "eve.global_broadcast.v1",
        "bottleneck_active": True,
        "candidate_count": 2,
        "selected_candidate_ids": ["coalition_current_evidence"],
        "content": content,
    }
    selection_digest = digest(selection_material)
    return {
        "cycle_id": "cycle-live-7",
        "cycle_index": 7,
        "updated_at": (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(),
        "broadcast": {
            "schema_version": "eve.global_broadcast.v1",
            "winner_id": "coalition_current_evidence",
            "content": content,
            "source_kinds": ["sensory_module", "memory_module"],
            "access_scope": scope,
            "bottleneck_active": True,
            "candidate_count": 2,
            "selected_candidate_ids": ["coalition_current_evidence"],
            "selection_digest": selection_digest,
            "delivery_digest": digest(
                {"selection_digest": selection_digest, "access_scope": scope}
            ),
        },
    }


class BroadcastEnvelopeTests(unittest.TestCase):
    def test_envelope_requires_named_access_and_binds_exact_content(self):
        envelope = access.broadcast_envelope(state(), "reply")
        self.assertEqual("cycle-live-7", envelope["cycle_id"])
        self.assertEqual(state()["broadcast"]["selection_digest"], envelope["selection_digest"])
        self.assertEqual("inspect_current_evidence", envelope["content"])
        self.assertEqual(64, len(envelope["content_sha256"]))
        self.assertEqual(64, len(envelope["envelope_sha256"]))

        with self.assertRaises(PermissionError):
            access.broadcast_envelope(state(["mind"]), "reply")

    def test_envelope_rejects_unknown_or_duplicate_access_scope(self):
        malformed = state()
        malformed["broadcast"]["access_scope"].append("reply")
        with self.assertRaisesRegex(ValueError, "duplicates"):
            access.broadcast_envelope(malformed, "reply")

        malformed = state()
        malformed["broadcast"]["access_scope"] = ["reply", "unknown"]
        with self.assertRaisesRegex(ValueError, "unknown"):
            access.broadcast_envelope(malformed, "reply")

    def test_envelope_recomputes_kernel_selection_and_delivery_digests(self):
        malformed = state()
        malformed["broadcast"]["content"] = "digest was not recomputed"
        with self.assertRaisesRegex(ValueError, "selection digest"):
            access.broadcast_envelope(malformed, "reply")

        malformed = state()
        malformed["broadcast"]["access_scope"] = ["reply"]
        with self.assertRaisesRegex(ValueError, "delivery digest"):
            access.broadcast_envelope(malformed, "reply")

    def test_envelope_accepts_real_conscious_state_kernel_output(self):
        from tests.test_conscious_state import fixture_inputs

        conscious_state = eve_consciousness.build_conscious_state(**fixture_inputs())
        envelope = access.broadcast_envelope(conscious_state, "reply")
        self.assertEqual(
            conscious_state["broadcast"]["selection_digest"],
            envelope["selection_digest"],
        )
        self.assertEqual(
            conscious_state["broadcast"]["selected_candidate_ids"][0],
            envelope["winner_id"],
        )


class BroadcastConsumptionTests(unittest.TestCase):
    def test_consumer_receives_detached_envelope_and_receipt_exposes_no_content(self):
        observed = {}
        current = state()

        def consumer(envelope):
            observed.update(envelope)
            envelope["content"] = "mutated_local_copy"
            return {"used": observed["selection_digest"], "decision": "answer"}

        output, receipt = access.consume_broadcast(
            current,
            "reply",
            consumer,
            purpose="reply.inner_state_brief",
        )
        self.assertEqual("answer", output["decision"])
        self.assertEqual("inspect_current_evidence", observed["content"])
        self.assertNotIn("content", receipt)
        self.assertNotIn("inspect_current_evidence", str(receipt))
        verified = access.verify_receipt(
            receipt,
            current,
            consumer_id="reply",
            expected_output=output,
            verify_output=True,
        )
        self.assertTrue(verified["valid"])
        self.assertFalse(verified["content_exposed_in_receipt"])
        self.assertFalse(verified["semantic_comprehension_established"])
        self.assertFalse(verified["consciousness_proven"])

    def test_consumer_failure_produces_no_returned_receipt(self):
        def broken(_envelope):
            raise RuntimeError("consumer failed")

        with self.assertRaisesRegex(RuntimeError, "failed"):
            access.consume_broadcast(
                state(), "mind", broken, purpose="mind.workspace_projection"
            )

    def test_receipt_fails_after_cycle_content_or_delivery_changes(self):
        current = state()
        output, receipt = access.consume_broadcast(
            current,
            "memory",
            lambda envelope: {"remember": envelope["content_sha256"]},
            purpose="memory.consolidation_input",
        )
        self.assertTrue(output)

        changed = copy.deepcopy(current)
        changed["broadcast"]["content"] = "different_broadcast"
        with self.assertRaisesRegex(ValueError, "selection digest"):
            access.verify_receipt(receipt, changed)

        changed = copy.deepcopy(current)
        changed["broadcast"]["delivery_digest"] = "c" * 64
        with self.assertRaisesRegex(ValueError, "delivery digest"):
            access.verify_receipt(receipt, changed)

    def test_receipt_digest_and_output_tampering_fail_closed(self):
        current = state()
        output, receipt = access.consume_broadcast(
            current,
            "action",
            lambda envelope: {"action": envelope["selection_digest"]},
            purpose="action.valuation",
        )
        tampered = copy.deepcopy(receipt)
        tampered["purpose"] = "action.other"
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            access.verify_receipt(tampered, current)

        with self.assertRaisesRegex(ValueError, "output"):
            access.verify_receipt(
                receipt,
                current,
                expected_output={"action": "wrong"},
                verify_output=True,
            )
        self.assertTrue(output)

    def test_consumption_cannot_predate_state(self):
        timestamp = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        with self.assertRaisesRegex(ValueError, "predate"):
            access.consume_broadcast(
                state(),
                "autonomy",
                lambda envelope: envelope["selection_digest"],
                purpose="autonomy.action_selection",
                consumed_at=timestamp,
            )


class BroadcastCoverageTests(unittest.TestCase):
    def receipts(self, current):
        result = []
        for consumer in access.CONSUMER_IDS:
            _output, receipt = access.consume_broadcast(
                current,
                consumer,
                lambda envelope, owner=consumer: {
                    "owner": owner,
                    "selection": envelope["selection_digest"],
                },
                purpose=f"{consumer}.canary",
            )
            result.append(receipt)
        return result

    def test_coverage_requires_one_exact_receipt_per_consumer(self):
        current = state()
        receipts = self.receipts(current)
        coverage = access.receipt_coverage(receipts, current)
        self.assertTrue(coverage["complete"])
        self.assertEqual(list(access.CONSUMER_IDS), coverage["verified_consumers"])
        self.assertFalse(coverage["semantic_comprehension_established"])
        self.assertFalse(coverage["consciousness_proven"])

        missing = access.receipt_coverage(receipts[:-1], current)
        self.assertFalse(missing["complete"])
        self.assertEqual(["learning"], missing["missing_consumers"])

    def test_duplicate_or_replayed_receipt_does_not_create_complete_coverage(self):
        current = state()
        receipts = self.receipts(current)
        receipts.append(copy.deepcopy(receipts[0]))
        coverage = access.receipt_coverage(receipts, current)
        self.assertFalse(coverage["complete"])
        self.assertEqual(["reply"], coverage["duplicate_consumers"])

        next_cycle = copy.deepcopy(current)
        next_cycle["cycle_id"] = "cycle-live-8"
        invalid = access.receipt_coverage(receipts[:1], next_cycle, required_consumers=["reply"])
        self.assertFalse(invalid["complete"])
        self.assertEqual(1, invalid["invalid_receipt_count"])


if __name__ == "__main__":
    unittest.main()
