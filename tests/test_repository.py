import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import eve_repository


class JsonDocumentRepositoryTests(unittest.TestCase):
    def test_load_prefers_resolved_runtime_path_when_requested(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_path = root / "state.json"
            runtime_path = root / "runtime-state.json"
            local_path.write_text('{"source":"local"}\n', encoding="utf-8")
            runtime_path.write_text('{"source":"runtime"}\n', encoding="utf-8")

            repo = eve_repository.JsonDocumentRepository(
                local_path,
                "state",
                ensure_store=lambda: None,
                read_path_resolver=lambda _path, prefer_runtime: runtime_path if prefer_runtime else local_path,
            )

            self.assertEqual({"source": "local"}, repo.load())
            self.assertEqual({"source": "runtime"}, repo.load(prefer_runtime=True))

    def test_save_runs_after_write_hook(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.json"
            mirrored = []

            repo = eve_repository.JsonDocumentRepository(
                path,
                "state",
                ensure_store=lambda: None,
                after_write=lambda written_path: mirrored.append(written_path),
            )

            repo.save({"ready": True})

            self.assertEqual([path], mirrored)
            self.assertEqual('{\n  "ready": true\n}\n', path.read_text(encoding="utf-8"))

    def test_update_mutates_document_and_runs_after_write_hook(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.json"
            path.write_text('{"count": 1}\n', encoding="utf-8")
            mirrored = []
            repo = eve_repository.JsonDocumentRepository(
                path,
                "state",
                ensure_store=lambda: None,
                after_write=lambda written_path: mirrored.append(written_path),
            )

            def bump(payload):
                payload["count"] = int(payload.get("count", 0)) + 1
                return payload["count"]

            result = repo.update(bump)

            self.assertEqual(2, result)
            self.assertEqual([path], mirrored)
            self.assertEqual({"count": 2}, repo.load())


if __name__ == "__main__":
    unittest.main()
