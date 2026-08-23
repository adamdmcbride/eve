import unittest
import importlib.util
import json
import tempfile
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "bin" / "eve_chat_brand_scrub.py"
SPEC = importlib.util.spec_from_file_location("eve_chat_brand_scrub", SCRIPT_PATH)
eve_chat_brand_scrub = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(eve_chat_brand_scrub)

LOCAL_SERVE_PATH = Path(__file__).resolve().parents[1] / "bin" / "eve_chat_local_serve.py"
LOCAL_SERVE_SPEC = importlib.util.spec_from_file_location("eve_chat_local_serve", LOCAL_SERVE_PATH)
eve_chat_local_serve = importlib.util.module_from_spec(LOCAL_SERVE_SPEC)
assert LOCAL_SERVE_SPEC.loader is not None
LOCAL_SERVE_SPEC.loader.exec_module(eve_chat_local_serve)


class EveChatBrandScrubTests(unittest.TestCase):
    def test_followup_script_renders_codex_style_inline_activity_stream(self) -> None:
        script = eve_chat_brand_scrub.FOLLOWUP_SCRIPT

        self.assertIn("function activityRows", script)
        self.assertIn("Thinking", script)
        self.assertIn("Reading thread", script)
        self.assertIn("Checking context", script)
        self.assertIn("Drafting", script)
        self.assertIn("Reply ready", script)
        self.assertNotIn("visible steps", script)
        self.assertNotIn("Eve worked through", script)
        self.assertNotIn("<details", script)

    def test_followup_script_exposes_copilotkit_demo_cards_in_chat(self) -> None:
        script = eve_chat_brand_scrub.FOLLOWUP_SCRIPT

        self.assertIn("?v=20260508-copilotkit-panel-anchor", eve_chat_brand_scrub.FOLLOWUP_SCRIPT_TAG)
        self.assertIn("function latestCopilotKitDemoMessage", script)
        self.assertIn("copilotKitDemoAnchor(host)", script)
        self.assertIn("return { parent: activity.parentElement, anchor: activity }", script)
        self.assertIn("function renderCopilotKitDemos", script)
        self.assertIn("CopilotKit demos in Eve Chat", script)
        self.assertIn("CopilotChat-style thread", script)
        self.assertIn("AG-UI-style visible beats", script)
        self.assertIn("Inline artifact cards", script)
        self.assertIn("UI actions Eve can call", script)
        self.assertIn("Review before action", script)
        self.assertIn("Chat and panels stay in sync", script)
        self.assertIn("Show CopilotKit demos", script)
        self.assertIn("Run live AG-UI smoke", script)
        self.assertIn("/api/eve-chat/ag-ui", script)
        self.assertIn('fetch("/api/eve-chat/ag-ui"', script)
        self.assertNotIn('fetch(`${apiBase}/api/eve-chat/ag-ui`', script)
        self.assertIn("reply with exactly agui-live-ok", script)
        self.assertIn("TEXT_MESSAGE_CONTENT", script)
        self.assertIn("eveChatCopilotKitDemoVisibleChat", script)
        self.assertIn("eveChatCopilotKitAguiAutoRun.20260508PanelAnchor", script)
        self.assertIn("copilotkit_demo: live", script)
        self.assertIn("i'm starting the live copilotkit demo now", script)
        self.assertIn("you should see the ag-ui event stream start below this reply", script)
        self.assertIn("if the panel does not start on its own", script)
        self.assertIn("climbs < 3", script)
        self.assertIn("maybeAutoRunCopilotKitAguiDemo", script)
        self.assertIn("showCopilotKitDemos", script)
        self.assertIn("do not change live model routing", script)

    def test_followup_overlay_replaces_old_uncached_script_tag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build = root / "build"
            build.mkdir()
            index = build / "index.html"
            index.write_text(
                '<html><body><script defer src="/eve-chat-followups.js" data-eve-chat-followups="true"></script></body></html>',
                encoding="utf-8",
            )

            report = eve_chat_brand_scrub.install_followup_overlay(root)
            html = index.read_text(encoding="utf-8")

        self.assertEqual(1, report["index_changed"])
        self.assertIn("?v=20260508-copilotkit-panel-anchor", html)
        self.assertNotIn('src="/eve-chat-followups.js" data-eve-chat-followups', html)

    def test_followup_overlay_handles_whitespace_in_script_end_tag(self) -> None:
        html = (
            '<html><body><script data-eve-chat-followups="true" '
            'src="/eve-chat-followups.js"></script   ></body></html>'
        )

        replaced, count = eve_chat_brand_scrub.replace_followup_script_tags(html)

        self.assertEqual(1, count)
        self.assertEqual(1, replaced.count("data-eve-chat-followups"))
        self.assertIn("?v=20260508-copilotkit-panel-anchor", replaced)

    def test_followup_overlay_does_not_replace_unrelated_scripts(self) -> None:
        html = '<html><body><script src="/app.js"></script></body></html>'

        replaced, count = eve_chat_brand_scrub.replace_followup_script_tags(html)

        self.assertEqual(0, count)
        self.assertEqual(html, replaced)

    def test_local_proxy_error_does_not_expose_exception_details(self) -> None:
        payload = eve_chat_local_serve.proxy_error_event_bytes().decode("utf-8")
        event = json.loads(payload.removeprefix("data: ").strip())

        self.assertEqual("backend_unavailable", event["code"])
        self.assertEqual("The local Eve chat backend is unavailable.", event["error"])
        self.assertNotIn("traceback", payload.lower())
        self.assertNotIn("127.0.0.1:8797", payload)


if __name__ == "__main__":
    unittest.main()
