import importlib.util
import json
import subprocess
import sys
import tempfile
import types
from pathlib import Path
import unittest
from unittest.mock import patch


def load_memory_embedding_helper():
    helper_path = Path(__file__).resolve().parents[1] / "bin" / "eve_memory_embedding.py"
    spec = importlib.util.spec_from_file_location("eve_memory_embedding_test_helper", helper_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load memory helper from {helper_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MemoryEmbeddingHelperTests(unittest.TestCase):
    def test_optional_evidence_metadata_survives_mixed_legacy_rows(self) -> None:
        helper = load_memory_embedding_helper()
        notes = [{"id": "legacy", "text": "old schema"}, {"id": "current", "text": "new schema",
                 "observed_at": "2026-10-01T00:00:00Z", "supersedes": ["previous"], "status": "active"}]
        rows, lance = helper.build_rows(notes, [[1.0], [1.0]])
        self.assertEqual(set(lance[0]), set(lance[1]))
        self.assertEqual(["previous"], helper.base_match_from_item(lance[1])["supersedes"])
        self.assertEqual("active", helper.base_match_from_item(rows[1])["status"])
        self.assertEqual("invalid_metadata", helper.base_match_from_item({"evidence_metadata": "broken"})["status"])

    def test_embedding_count_dimensions_and_finiteness_are_hard_gates(self) -> None:
        helper = load_memory_embedding_helper()
        notes = [{"id": "one"}, {"id": "two"}]
        for vectors in ([[1.0]], [[1.0], [1.0, 2.0]], [[], []],
                        [[float("nan")], [1.0]], [[float("inf")], [1.0]], [[True], [1.0]]):
            with self.subTest(vectors=vectors), self.assertRaises(ValueError):
                helper.build_rows(notes, vectors)
        rows, lance = helper.build_rows(notes, [[1.0, 0.0], [0.0, 1.0]])
        self.assertEqual(2, len(rows))
        self.assertEqual(["one", "two"], [row["id"] for row in lance])

    def test_invalid_json_embedding_keeps_previous_index(self) -> None:
        helper = load_memory_embedding_helper()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "index.json"
            output.write_text("previous index")
            with self.assertRaises(ValueError):
                helper.build_json_index(output, {}, [{"embedding": [float("nan")]}],
                                        model_name="candidate", query_mode="vector")
            self.assertEqual("previous index", output.read_text())
            self.assertEqual(["index.json"], [p.name for p in output.parent.iterdir()])

    def test_json_index_replaces_only_after_complete_serialization(self) -> None:
        helper = load_memory_embedding_helper()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "index.json"
            output.write_text("previous index")
            result = helper.build_json_index(output, {"notes_hash": "synthetic"},
                       [{"id": "one", "embedding": [1.0, 0.0]}], model_name="candidate", query_mode="vector")
            self.assertEqual(result, json.loads(output.read_text()))
            self.assertEqual(["index.json"], [p.name for p in output.parent.iterdir()])

    def test_lancedb_build_uses_supported_unified_fts_index_api(self) -> None:
        helper = load_memory_embedding_helper()
        create_index_calls: list[tuple[tuple, dict]] = []

        class FakeFTS:
            pass

        class FakeTable:
            def create_index(self, *args, **kwargs):
                create_index_calls.append((args, kwargs))

        class FakeDatabase:
            def create_table(self, _name, *, data, mode):
                self.data = data
                self.mode = mode
                return FakeTable()

        fake_db = FakeDatabase()
        fake_lancedb = types.ModuleType("lancedb")
        fake_lancedb.connect = lambda _path: fake_db
        fake_index = types.ModuleType("lancedb.index")
        fake_index.FTS = FakeFTS

        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            sys.modules,
            {"lancedb": fake_lancedb, "lancedb.index": fake_index},
        ):
            root = Path(tmp)
            output = root / "index.json"
            payload = helper.build_lancedb_index(
                output,
                {"notes_hash": "hash-fts"},
                [{"id": "note", "text": "supported full text search", "vector": [1.0]}],
                model_name="test-model",
                query_mode="hybrid",
                db_dir_value=str(root / "lancedb"),
                table_name="memory",
            )

        self.assertEqual("lancedb", payload["backend"])
        self.assertEqual("overwrite", fake_db.mode)
        self.assertEqual(1, len(create_index_calls))
        args, kwargs = create_index_calls[0]
        self.assertEqual(("text",), args)
        self.assertIsInstance(kwargs["config"], FakeFTS)
        self.assertTrue(kwargs["replace"])

    def test_lexical_fallback_builds_and_queries_without_mlx_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            notes = {
                "notes_hash": "hash-1",
                "notes": [
                    {"id": "calendar", "source": "test", "title": "Calendar", "text": "Calendar control and events."},
                    {"id": "models", "source": "test", "title": "Models", "text": "Model routing and bakeoffs."},
                ],
            }
            notes_path = root / "notes.json"
            index_path = root / "index.json"
            notes_path.write_text(json.dumps(notes), encoding="utf-8")
            helper = Path(__file__).resolve().parents[1] / "bin" / "eve_memory_embedding.py"

            build = subprocess.run(
                [
                    sys.executable,
                    str(helper),
                    "build",
                    "--notes",
                    str(notes_path),
                    "--output",
                    str(index_path),
                    "--model",
                    "lexical-local",
                    "--backend",
                    "json",
                    "--query-mode",
                    "text",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            self.assertEqual(0, build.returncode, build.stderr or build.stdout)

            query = subprocess.run(
                [
                    sys.executable,
                    str(helper),
                    "query",
                    "--index",
                    str(index_path),
                    "--query",
                    "calendar events",
                    "--limit",
                    "1",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            self.assertEqual(0, query.returncode, query.stderr or query.stdout)
            payload = json.loads(query.stdout)
            self.assertEqual("calendar", payload["matches"][0]["id"])


if __name__ == "__main__":
    unittest.main()
