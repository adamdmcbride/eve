import unittest

import eve_agui


class AGUIProtocolTests(unittest.TestCase):
    def test_context_normalizes_prompt_without_changing_eve_route_metadata(self):
        context = eve_agui.copilotkit_agui_context(
            {
                "threadId": "thread-1",
                "runId": "run-1",
                "prompt": "  hello\nEve  ",
                "model": "eve",
            }
        )

        self.assertEqual([{"role": "user", "content": "hello\nEve"}], context["messages"])
        self.assertEqual("hello\nEve", context["latest_user"])
        self.assertEqual("run-1", context["client_request_id"])
        self.assertEqual(
            {
                "protocol": eve_agui.COPILOTKIT_AGUI_PROTOCOL,
                "thread_id": "thread-1",
                "run_id": "run-1",
            },
            context["openai_payload"]["metadata"],
        )

    def test_nested_input_messages_and_prompt_compatibility_are_preserved(self):
        messages_context = eve_agui.copilotkit_agui_context(
            {
                "run_id": "run-messages",
                "messages": [],
                "input": {"messages": [{"role": "user", "content": "nested"}]},
            }
        )
        prompt_context = eve_agui.copilotkit_agui_context(
            {
                "run_id": "run-prompt",
                "input": {"message": "nested prompt"},
            }
        )

        self.assertEqual("nested", messages_context["latest_user"])
        self.assertEqual("nested prompt", prompt_context["latest_user"])

    def test_malformed_consumed_fields_fail_instead_of_becoming_strings(self):
        cases = (
            ([], "JSON object"),
            ({"input": []}, "AG-UI input must be a JSON object"),
            ({"prompt": 17}, "AG-UI prompt must be text"),
            ({"prompt": "x" * 8001}, "AG-UI prompt is too long"),
            ({"model": 17, "prompt": "hello"}, "AG-UI model must be text"),
            ({"model": "x" * 81, "prompt": "hello"}, "AG-UI model is too long"),
            ({"messages": "hello"}, "non-empty messages array"),
            (
                {"messages": [{"role": "user", "content": "x" * 8001}]},
                r"messages\[0\].content is too long",
            ),
            (
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": ["x" * 5000, "y" * 5000],
                        }
                    ]
                },
                r"messages\[0\].content is too long",
            ),
            (
                {"messages": [{"role": "user\nadmin", "content": "hello"}]},
                r"messages\[0\].role must be printable",
            ),
            (
                {"messages": [{"role": 17, "content": "hello"}]},
                r"messages\[0\].role must be text",
            ),
            (
                {"messages": [{"role": "user", "content": 17}]},
                r"messages\[0\].content must be text or a content-parts array",
            ),
            (
                {"messages": [{"role": "user", "content": [17]}]},
                r"messages\[0\].content\[0\] must be text or an object",
            ),
            (
                {"messages": [{"role": "user", "content": ["hidden\u0000text"]}]},
                r"messages\[0\].content\[0\] must be printable",
            ),
            (
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": [{"type": "text", "text": 17}],
                        }
                    ]
                },
                r"messages\[0\].content\[0\].text must be text",
            ),
            (
                {"threadId": "thread-1", "chat_id": "thread-2", "prompt": "hello"},
                "Conflicting AG-UI thread id aliases",
            ),
            (
                {"runId": "run-1", "run_id": "run-2", "prompt": "hello"},
                "Conflicting AG-UI run id aliases",
            ),
            (
                {
                    "runId": "run-1",
                    "client_request_id": "request-1",
                    "user": "request-2",
                    "prompt": "hello",
                },
                "Conflicting AG-UI client request id aliases",
            ),
        )
        for payload, message in cases:
            with self.subTest(payload=payload), self.assertRaisesRegex(ValueError, message):
                eve_agui.copilotkit_agui_context(payload)

    def test_generated_event_ids_are_bounded_and_collision_resistant(self):
        first = eve_agui.copilotkit_agui_context(
            {"runId": "a" * 160, "messages": [{"role": "user", "content": "hello"}]}
        )
        same = eve_agui.copilotkit_agui_context(
            {"runId": "a" * 160, "messages": [{"role": "user", "content": "hello"}]}
        )
        different = eve_agui.copilotkit_agui_context(
            {"runId": "b" * 160, "messages": [{"role": "user", "content": "hello"}]}
        )

        for key in ("activity_message_id", "text_message_id"):
            self.assertEqual(160, len(first[key]))
            self.assertEqual(first[key], same[key])
            self.assertNotEqual(first[key], different[key])

    def test_event_type_is_bounded_printable_text(self):
        event = eve_agui.agui_event("RUN_STARTED", nullable=None, value="kept")
        self.assertEqual("RUN_STARTED", event["type"])
        self.assertEqual("kept", event["value"])
        self.assertNotIn("nullable", event)
        self.assertIsInstance(event["timestamp"], int)

        with self.assertRaisesRegex(ValueError, "must be printable"):
            eve_agui.agui_event("RUN\nSTARTED")
        with self.assertRaisesRegex(ValueError, "too long"):
            eve_agui.agui_event("x" * 65)

    def test_progress_and_completion_projection_remain_protocol_compatible(self):
        progress = eve_agui.copilotkit_agui_progress_content(
            {
                "status": "running",
                "phase": "drafting",
                "notes": [{"id": str(index)} for index in range(6)],
            }
        )
        reply_text, reply_id, metadata = eve_agui.copilotkit_agui_completion_reply(
            {
                "id": "completion-1",
                "choices": [{"message": {"content": "hello"}}],
                "eve": {"reply_message_id": "reply-1", "thread_id": "thread-1"},
            }
        )

        self.assertEqual([{"id": "2"}, {"id": "3"}, {"id": "4"}, {"id": "5"}], progress["notes"])
        self.assertEqual(("hello", "reply-1"), (reply_text, reply_id))
        self.assertEqual("thread-1", metadata["thread_id"])


if __name__ == "__main__":
    unittest.main()
