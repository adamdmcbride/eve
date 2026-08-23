#!/usr/bin/env python3

import json
import unittest
from unittest import mock

import eve_prompt_budget


class _Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload


class PromptBudgetTests(unittest.TestCase):
    def test_prepare_messages_merges_leading_system_context_like_eve(self):
        prepared = eve_prompt_budget.prepare_llama_cpp_messages(
            [
                {"role": "system", "content": "identity"},
                {"role": "system", "content": "policy"},
                {"role": "user", "content": "request"},
            ]
        )
        self.assertEqual([item["role"] for item in prepared], ["system", "user"])
        self.assertEqual(prepared[0]["content"], "identity\n\npolicy")
        self.assertEqual(prepared[1]["content"], "request")

    def test_live_measurement_uses_effective_slot_context_and_real_template(self):
        responses = [
            _Response({"default_generation_settings": {"n_ctx": 8192}}),
            _Response({"prompt": "rendered chat prompt"}),
            _Response({"tokens": list(range(321))}),
        ]
        with mock.patch("eve_prompt_budget.request.urlopen", side_effect=responses):
            result = eve_prompt_budget.measure_prompt(
                "http://127.0.0.1:8080",
                [{"role": "user", "content": "hello"}],
            )
        self.assertEqual(result.context_tokens, 8192)
        self.assertEqual(result.prompt_tokens, 321)
        self.assertTrue(result.exact)

    def test_fit_removes_low_priority_context_and_preserves_required_user(self):
        messages = [
            {"role": "system", "content": "identity"},
            {"role": "system", "content": "old optional " * 120},
            {"role": "system", "content": "new optional " * 100},
            {"role": "user", "content": "latest user request"},
        ]

        def measure(current):
            chars = sum(len(str(item.get("content") or "")) for item in current)
            return eve_prompt_budget.PromptMeasurement(
                context_tokens=900,
                prompt_tokens=max(1, chars // 3),
                exact=True,
                source="test",
            )

        fitted, evidence = eve_prompt_budget.fit_messages(
            "unused",
            messages,
            max_tokens=180,
            safety_tokens=60,
            required_indices={0, 3},
            optional_priorities={1: 1, 2: 2},
            minimum_optional_chars=80,
            measurement=measure,
        )
        self.assertEqual(fitted[0]["content"], "identity")
        self.assertEqual(fitted[-1]["content"], "latest user request")
        self.assertTrue(evidence["final_user_preserved"])
        self.assertLessEqual(evidence["prompt_tokens_after"], evidence["prompt_budget_tokens"])
        self.assertTrue(evidence["removed_message_indices"] or evidence["trimmed_message_indices"])
        self.assertFalse(evidence["content_persisted"])

    def test_unlisted_messages_are_required_and_never_silently_cut(self):
        messages = [
            {"role": "system", "content": "required " * 400},
            {"role": "user", "content": "required user"},
        ]

        def measure(current):
            chars = sum(len(str(item.get("content") or "")) for item in current)
            return eve_prompt_budget.PromptMeasurement(500, chars // 2, True, "test")

        with self.assertRaises(eve_prompt_budget.PromptFitError):
            eve_prompt_budget.fit_messages(
                "unused",
                messages,
                max_tokens=100,
                safety_tokens=50,
                measurement=measure,
            )

    def test_offline_measurement_is_conservative_and_labeled(self):
        with mock.patch("eve_prompt_budget.request.urlopen", side_effect=OSError("offline")):
            result = eve_prompt_budget.measure_prompt(
                "http://127.0.0.1:9",
                [{"role": "user", "content": "hello world"}],
                fallback_context_tokens=4096,
            )
        self.assertEqual(result.context_tokens, 4096)
        self.assertFalse(result.exact)
        self.assertEqual(result.source, "conservative_character_fallback")
        self.assertGreater(result.prompt_tokens, 0)

    def test_budget_reserves_output_and_safety_tokens(self):
        self.assertEqual(eve_prompt_budget.available_prompt_tokens(8192, 180, safety_tokens=256), 7756)


if __name__ == "__main__":
    unittest.main()
