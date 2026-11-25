import json
import unittest
from unittest.mock import patch

import eve
from tests.test_mind_tick import FakeHTTPResponse


class LlamaCppTruncationTests(unittest.TestCase):
    """A reply cut off by max_tokens is retried once with a larger budget; a whole reply wins."""

    def _run(self, responses, max_tokens=320):
        captured = []
        def fake_urlopen(req, data=None, timeout=None, **kwargs):
            url = req if isinstance(req, str) else getattr(req, "full_url", "")
            raw = data if data is not None else getattr(req, "data", None)
            if not raw or "chat/completions" not in url:
                # health, props or model-list calls the transport makes before chatting
                return FakeHTTPResponse({"status": "ok", "data": [{"id": "eve-fast"}], "default_generation_settings": {"n_ctx": 16384}})
            captured.append(json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw))
            return FakeHTTPResponse(responses.pop(0))
        with patch("eve.request.urlopen", side_effect=fake_urlopen), patch.object(eve, "append_perf_event") as perf, patch("eve.time.perf_counter", side_effect=[float(i) for i in range(40)]):
            content = eve.llama_cpp_chat(dict(eve.DEFAULT_CONFIG), "http://127.0.0.1:8080", "eve-fast", [{"role": "user", "content": "Return the active-mind JSON."}], max_tokens, operation="mind_tick", timeout_seconds=30)
        return content, captured, perf

    def test_truncated_json_is_retried_with_a_larger_budget(self):
        cut = {"choices": [{"message": {"content": '{"summary": "half an obj'}, "finish_reason": "length"}]}
        whole = {"choices": [{"message": {"content": '{"summary": "whole"}'}, "finish_reason": "stop"}]}
        content, captured, perf = self._run([cut, whole])
        self.assertEqual('{"summary": "whole"}', content)
        self.assertEqual([320, 640], [c["max_tokens"] for c in captured])
        kinds = [(call.kwargs.get("ok"), (call.kwargs.get("metadata") or {}).get("attempt")) for call in perf.call_args_list]
        self.assertIn((False, "primary"), kinds); self.assertIn((True, "truncation_retry"), kinds)

    def test_whole_reply_is_not_retried(self):
        whole = {"choices": [{"message": {"content": "done"}, "finish_reason": "stop"}]}
        content, captured, _ = self._run([whole])
        self.assertEqual("done", content); self.assertEqual(1, len(captured))

    def test_still_truncated_after_retry_returns_the_longer_attempt_marked(self):
        cut1 = {"choices": [{"message": {"content": "a" * 10}, "finish_reason": "length"}]}
        cut2 = {"choices": [{"message": {"content": "a" * 20}, "finish_reason": "length"}]}
        content, captured, perf = self._run([cut1, cut2])
        self.assertEqual("a" * 10, content, "an answer that is still cut off falls back to the primary, flagged truncated")
        self.assertEqual(2, len(captured))
        flagged = [(call.kwargs.get("metadata") or {}).get("truncated") for call in perf.call_args_list if call.kwargs.get("ok")]
        self.assertIn(True, flagged)

    def test_message_content_reports_truncation(self):
        content, _, kind = eve.llama_cpp_message_content({"choices": [{"message": {"content": "x"}, "finish_reason": "length"}]})
        self.assertEqual(("x", "truncated"), (content, kind))
        content, _, kind = eve.llama_cpp_message_content({"choices": [{"message": {"content": "x"}, "finish_reason": "stop"}]})
        self.assertEqual("", kind)


if __name__ == "__main__":
    unittest.main()
