import unittest
from unittest.mock import patch

import eve_capability_adoption as adoption


def capability(identifier, name, **extra):
    return {"id": identifier, "name": name, "category": "tool", "available": True, "callable": True,
            "verified": True, "needs_permission": False, "evidence": {"description": name}, **extra}


class CapabilityDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.matrix = {"capabilities": [capability("tool.web_search", "search public web"),
                        capability("tool.file_read", "read local files"),
                        capability("tool.send_email", "send email", needs_permission=True)]}

    def test_simple_objective_uses_one_existing_resolver(self):
        with patch.object(adoption, "resolve_capability_first", wraps=adoption.resolve_capability_first) as resolve:
            result = adoption.resolve_capability_needs("search public web", self.matrix)
        self.assertEqual(1, resolve.call_count)
        self.assertEqual("direct", result["strategy"])
        self.assertEqual(["tool.web_search"], result["selected_capability_ids"])
        self.assertFalse(result["automatic_execution"])

    def test_complex_objective_resolves_real_needs_separately(self):
        result = adoption.resolve_capability_needs("research and compare local evidence", self.matrix,
                  needs=["search public web", "read local files"])
        self.assertEqual("decomposed", result["strategy"])
        self.assertEqual(2, result["resolver_calls"])
        self.assertEqual(["tool.file_read", "tool.web_search"], result["selected_capability_ids"])
        self.assertEqual("discovery_only", result["authority"])

    def test_invented_tool_or_permission_request_does_not_create_authority(self):
        result = adoption.resolve_capability_needs("multi-part objective", self.matrix,
                 needs=["send email", "quantum_teleportation arbitrary_tool"])
        self.assertEqual([], result["selected_capability_ids"])
        self.assertEqual(["tool.send_email"], result["permission_required_ids"])
        self.assertEqual(2, len(result["unresolved_needs"]))

    def test_unverified_registry_surface_is_not_selected(self):
        matrix = {"capabilities": [capability("tool.web_search", "search public web", verified=False)]}
        result = adoption.resolve_capability_needs("search public web", matrix)
        self.assertEqual([], result["selected_capability_ids"])
        self.assertEqual("requires_owner_review", result["status"])

    def test_duplicate_needs_do_not_spend_retrieval_calls(self):
        result = adoption.resolve_capability_needs("web research", self.matrix, needs=["search public web", "search public web"])
        self.assertEqual(1, result["resolver_calls"])

    def test_invalid_or_unbounded_decomposition_fails_before_resolution(self):
        for needs in (["x"] * 5, [""], ["x"*321], [None], "tool names"):
            with self.subTest(needs=needs), patch.object(adoption, "resolve_capability_first") as resolve:
                with self.assertRaises(ValueError):
                    adoption.resolve_capability_needs("objective", self.matrix, needs=needs)
                resolve.assert_not_called()


if __name__ == "__main__":
    unittest.main()
