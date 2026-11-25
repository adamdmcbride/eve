import contextlib
import stat
import sqlite3
import tempfile
import unittest
from pathlib import Path

import eve_db


class DatabaseLifecycleTests(unittest.TestCase):
    def test_connection_context_closes_after_commit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "eve.sqlite3"
            with eve_db.connect_database(path) as connection:
                connection.execute("CREATE TABLE lifecycle_probe (id INTEGER)")

            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute("SELECT 1")

    def test_initializer_rebuilds_schema_after_database_file_is_replaced(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "eve.sqlite3"
            eve_db.initialize_database(path)

            path.unlink()
            for suffix in ("-shm", "-wal"):
                sidecar = Path(str(path) + suffix)
                if sidecar.exists():
                    sidecar.unlink()
            path.touch()

            eve_db.initialize_database(path)

            with contextlib.closing(sqlite3.connect(path)) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
            self.assertIn("events", tables)
            self.assertIn("trace_spans", tables)

    def test_writer_lock_metadata_is_owner_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "eve.sqlite3"

            with eve_db.single_writer_lock(path):
                lock_path = Path(str(path) + ".lock")
                mode = stat.S_IMODE(lock_path.stat().st_mode)

            self.assertEqual(0o600, mode)


if __name__ == "__main__":
    unittest.main()
