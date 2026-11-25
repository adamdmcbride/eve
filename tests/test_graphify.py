import importlib.util
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("eve_graphify", ROOT / "bin" / "eve_graphify.py")
graphify = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(graphify)


class GraphifyTests(unittest.TestCase):
    def test_source_allowlist(self):
        for name in ("eve.py", "eve_core/self_change.py", "eve_adapters/self_change.py", "bin/tool.py", "mac/EveChatApp.swift", "web/eve_app/app.js", "rust/src/main.rs", "go/bridge/main.go"):
            self.assertTrue(graphify.allowed_source(name), name)
        for name in (".eve/state.py", "tests/test_hidden.py", "data/private.py", "memory/note.py", "vendor/code.py", "openclaw/context/note.py", "mac/generated/code.swift", "web/node_modules/a.js", "bin/.secret.py", "docs/EVE_CORE.md", "models/model.gguf", "../eve.py", "/eve.py", "bin/../eve.py"):
            self.assertFalse(graphify.allowed_source(name), name)

    def test_only_tracked_code_and_no_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "eve.py").write_text("pass\n")
            (root / "untracked.py").write_text("private\n")
            (root / "link.py").symlink_to(root / "eve.py")
            (root / "bin").symlink_to(root)
            tracked = b"eve.py\0link.py\0bin/eve.py\0"
            with mock.patch.object(graphify.subprocess, "check_output", return_value=tracked):
                self.assertEqual(list(graphify.source_files(root)), ["eve.py"])

    def test_provider_credentials_and_python_path_not_inherited(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test", "ANTHROPIC_API_KEY": "test", "HTTP_PROXY": "test", "PYTHONPATH": "test", "GRAPHIFY_BACKEND": "openai"}):
            env = graphify.local_env()
        self.assertFalse(set(env) & {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "HTTP_PROXY", "PYTHONPATH", "GRAPHIFY_BACKEND"})

    def test_new_source_requires_explicit_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "eve.py").write_text("pass\n")
            (root / "new_module.py").write_text("pass\n")
            (root / "private.py").write_text("private\n")
            with mock.patch.object(graphify.subprocess, "check_output", return_value=b"eve.py\0"):
                self.assertEqual(list(graphify.source_files(root)), ["eve.py"])
                self.assertEqual(list(graphify.source_files(root, ["new_module.py"])), ["eve.py", "new_module.py"])
                for name in ("../private.py", ".eve/state.py", "tests/test_private.py"):
                    with self.assertRaises(ValueError):
                        graphify.source_files(root, [name])

    def dataless_stat(self, source):
        original = Path.stat

        def stat(path, *args, **kwargs):
            result = original(path, *args, **kwargs)
            if path == source:
                return SimpleNamespace(st_mode=result.st_mode, st_flags=0x40000000)
            return result

        return stat

    def test_dataless_source_is_rejected_before_payload_read(self):
        for explicit in (False, True):
            for content in ("", "pass\n"):
                with self.subTest(explicit=explicit, empty=not content), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    source = root / "unavailable.py"
                    source.write_text(content)
                    reads = []
                    original = Path.read_bytes

                    def read(path):
                        reads.append(path)
                        return original(path)

                    with mock.patch.object(graphify.subprocess, "check_output", return_value=b"" if explicit else b"unavailable.py\0"), mock.patch.object(
                        Path, "stat", self.dataless_stat(source)
                    ), mock.patch.object(Path, "read_bytes", read):
                        with self.assertRaisesRegex(ValueError, "dataless.*unavailable.py"):
                            graphify.source_files(root, ["unavailable.py"] if explicit else [])
                    self.assertNotIn(source, reads)

    def test_dataless_source_cannot_use_cached_graph(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / ".eve" / "graphify"
            cache.parent.mkdir()
            self.build_fixture(root, cache)
            source = root / "eve.py"
            graph_before = (cache / "graphify-out" / "graph.json").read_bytes()
            manifest_before = (cache / "graphify-out" / "eve_manifest.json").read_bytes()
            with mock.patch.object(graphify, "ROOT", root), mock.patch.object(
                graphify.subprocess, "check_output", return_value=b"eve.py\0"
            ), mock.patch.object(Path, "stat", self.dataless_stat(source)), mock.patch.object(
                graphify.sys, "argv", ["eve_graphify.py", "query", "example"]
            ), mock.patch.object(graphify, "graphify_binary") as binary, mock.patch.object(graphify, "run_tool") as run:
                with self.assertRaisesRegex(ValueError, "dataless.*eve.py"):
                    graphify.main()
            binary.assert_not_called()
            run.assert_not_called()
            self.assertEqual(graph_before, (cache / "graphify-out" / "graph.json").read_bytes())
            self.assertEqual(manifest_before, (cache / "graphify-out" / "eve_manifest.json").read_bytes())

    def test_source_offloaded_before_staging_preserves_previous_graph(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            self.build_fixture(root, cache)
            source = root / "eve.py"
            content = source.read_bytes()
            files = {"eve.py": hashlib.sha256(content).hexdigest()}
            graph_before = (cache / "graphify-out" / "graph.json").read_bytes()
            manifest_before = (cache / "graphify-out" / "eve_manifest.json").read_bytes()
            reads = []
            original = Path.read_bytes

            def read(path):
                reads.append(path)
                return original(path)

            def fake_tool(binary, *args, **kwargs):
                output = kwargs["cwd"] / "graphify-out"
                if args[0] == "extract":
                    output.mkdir()
                    (output / "graph.json").write_text(json.dumps({"nodes": [{"id": "example"}], "edges": []}))
                else:
                    (output / "GRAPH_REPORT.md").write_text("# Local report\n")

            with mock.patch.object(graphify, "source_files", return_value=files), mock.patch.object(
                Path, "stat", self.dataless_stat(source)
            ), mock.patch.object(Path, "read_bytes", read), mock.patch.object(
                graphify.subprocess, "check_output", return_value="fixture-head\n"
            ), mock.patch.object(graphify, "run_tool", side_effect=fake_tool) as run:
                with self.assertRaisesRegex(ValueError, "dataless.*eve.py"):
                    graphify.build(root, cache, "graphify")
            self.assertNotIn(source, reads)
            run.assert_not_called()
            self.assertEqual(graph_before, (cache / "graphify-out" / "graph.json").read_bytes())
            self.assertEqual(manifest_before, (cache / "graphify-out" / "eve_manifest.json").read_bytes())

    def test_wrong_tool_version_rejected(self):
        with mock.patch.object(graphify.subprocess, "check_output", return_value="graphify 1.0\n"):
            with self.assertRaises(ValueError):
                graphify.graphify_binary()

    def test_project_managed_version_precedes_unrelated_global_tool(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(graphify, "ROOT", Path(tmp)):
            binary = Path(tmp) / ".eve" / "toolchains" / ("graphify-" + graphify.VERSION) / "bin" / "graphify"
            binary.parent.mkdir(parents=True)
            binary.write_text("fixture")
            with mock.patch.object(graphify.shutil, "which", return_value="/global/graphify"), mock.patch.object(
                graphify.subprocess, "check_output", return_value="graphify " + graphify.VERSION + "\n"
            ) as call:
                self.assertEqual(str(binary), graphify.graphify_binary())
                self.assertEqual([str(binary), "--version"], call.call_args.args[0])

    def test_absent_managed_tool_uses_version_checked_path_fallback(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(graphify, "ROOT", Path(tmp)):
            with mock.patch.object(graphify.shutil, "which", return_value="/global/graphify"), mock.patch.object(
                graphify.subprocess, "check_output", return_value="graphify " + graphify.VERSION + "\n"
            ):
                self.assertEqual("/global/graphify", graphify.graphify_binary())

    def test_missing_graph_is_not_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(graphify.graph_status(Path(tmp), Path(tmp))["status"], "missing")

    def test_visualization_uses_local_verified_library(self):
        text = '<html><script src="' + graphify.VIS_URL + '" integrity="hash" crossorigin="anonymous"></script><body>map</body></html>'
        result = graphify.local_html(text)
        self.assertNotIn(graphify.VIS_URL, result)
        self.assertIn('../assets/vis-network-9.1.6.min.js', result)
        with self.assertRaises(ValueError):
            graphify.local_html('<script src="https://example.com/unknown.js"></script>')

    def test_map_rejects_corrupted_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            (cache / "assets").mkdir()
            (cache / "assets" / "vis-network-9.1.6.min.js").write_text("corrupt")
            with self.assertRaises(ValueError), mock.patch.object(graphify, "run_tool") as run:
                graphify.make_map(cache, "graphify", "graph.json")
            run.assert_not_called()

    def build_fixture(self, root, cache, include=None):
        (root / "eve.py").write_text("def example():\n    return True\n")
        cache.mkdir(exist_ok=True)
        calls = []
        previous = cache / "graphify-out" / "eve_manifest.json"
        expected_includes = include
        if expected_includes is None:
            expected_includes = json.loads(previous.read_text()).get("explicit_includes", []) if previous.exists() else []

        def fake_tool(binary, *args, **kwargs):
            calls.append(args)
            if args[0] == "extract":
                self.assertEqual(sorted(p.name for p in Path(args[1]).iterdir()), sorted(["eve.py", *expected_includes]))
                out = kwargs["cwd"] / "graphify-out"
                out.mkdir()
                (out / "graph.json").write_text(json.dumps({"nodes": [{"id": "example", "source_file": "eve.py"}], "edges": []}))
            else:
                (kwargs["cwd"] / "graphify-out" / "GRAPH_REPORT.md").write_text("# Local report\n")

        with mock.patch.object(graphify.subprocess, "check_output", side_effect=lambda cmd, **kw: b"eve.py\0" if cmd[1] == "ls-files" else "fixture-head\n"), mock.patch.object(graphify, "run_tool", side_effect=fake_tool):
            manifest = graphify.build(root, cache, "graphify", include=include)
        return manifest, calls

    def test_explicit_include_is_remembered_and_checked_for_staleness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            (root / "new_module.py").write_text("pass\n")
            manifest, _ = self.build_fixture(root, cache, include=["new_module.py"])
            self.assertEqual(["new_module.py"], manifest["explicit_includes"])
            self.assertIn("new_module.py", manifest["files"])
            retained, _ = self.build_fixture(root, cache)
            self.assertEqual(manifest["explicit_includes"], retained["explicit_includes"])
            with mock.patch.object(graphify.subprocess, "check_output", return_value=b"eve.py\0"):
                self.assertEqual("ok", graphify.graph_status(root, cache)["status"])
                (root / "new_module.py").write_text("changed\n")
                self.assertEqual(["new_module.py"], graphify.graph_status(root, cache)["changed_files"])
                (root / "new_module.py").unlink()
                self.assertEqual("stale", graphify.graph_status(root, cache)["status"])
                with self.assertRaises(ValueError):
                    graphify.build(root, cache, "graphify")

    def test_explicit_include_cannot_follow_a_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            (root / "target.py").write_text("private\n")
            (root / "link.py").symlink_to(root / "target.py")
            cache.mkdir()
            with mock.patch.object(graphify.subprocess, "check_output", return_value=b""), mock.patch.object(graphify, "run_tool") as run:
                with self.assertRaises(ValueError):
                    graphify.build(root, cache, "graphify", include=["link.py"])
                run.assert_not_called()

    def test_build_uses_ast_only_and_no_llm_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, calls = self.build_fixture(root, root / "cache")
            self.assertIn("--code-only", calls[0])
            self.assertIn("--no-cluster", calls[0])
            self.assertEqual(calls[0][-2:], ("--max-workers", "2"))
            self.assertIn("--no-label", calls[1])
            self.assertIn("--no-viz", calls[1])
            self.assertEqual(manifest["authority"], "derived_source_navigation_only")
            self.assertEqual(manifest["nodes"], 1)
            self.assertTrue(manifest["directed"])
            self.assertFalse(list((root / "cache").glob("build-*")))

    def test_source_changes_make_graph_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            self.build_fixture(root, cache)
            with mock.patch.object(graphify.subprocess, "check_output", return_value=b"eve.py\0"):
                self.assertEqual(graphify.graph_status(root, cache)["status"], "ok")
                (root / "eve.py").write_text("pass\n")
                status = graphify.graph_status(root, cache)
                self.assertEqual(status["status"], "stale")
                self.assertEqual(status["changed_files"], ["eve.py"])

    def test_modified_graph_is_not_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            self.build_fixture(root, cache)
            (cache / "graphify-out" / "graph.json").write_text("{}")
            with mock.patch.object(graphify.subprocess, "check_output", return_value=b"eve.py\0"):
                status = graphify.graph_status(root, cache)
            self.assertEqual(status["status"], "stale")
            self.assertFalse(status["graph_intact"])

    def test_failed_rebuild_preserves_previous_graph(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            self.build_fixture(root, cache)
            old = (cache / "graphify-out" / "graph.json").read_bytes()
            with mock.patch.object(graphify.subprocess, "check_output", return_value=b"eve.py\0"), mock.patch.object(graphify, "run_tool", side_effect=ValueError("canary failure")):
                with self.assertRaises(ValueError):
                    graphify.build(root, cache, "graphify")
            self.assertEqual((cache / "graphify-out" / "graph.json").read_bytes(), old)


if __name__ == "__main__":
    unittest.main()
