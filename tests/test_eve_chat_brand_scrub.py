import unittest
import importlib.util
import tempfile
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "bin" / "eve_chat_brand_scrub.py"
SPEC = importlib.util.spec_from_file_location("eve_chat_brand_scrub", SCRIPT_PATH)
eve_chat_brand_scrub = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(eve_chat_brand_scrub)


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


if __name__ == "__main__":
    unittest.main()
