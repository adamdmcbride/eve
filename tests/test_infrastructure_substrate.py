import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import eve
import eve_db
import eve_model_governor
import eve_tracing


class InfrastructureSubstrateTests(unittest.TestCase):
    def test_database_initializes_wal_and_records_core_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "operational_state.sqlite3"
            eve_db.initialize_database(db_path)
            eve_db.record_perf_event(
                db_path,
                {
                    "id": "perf-1",
                    "timestamp": "2026-04-24T00:00:00+00:00",
                    "category": "model_call",
                    "name": "reply_stream_synthesis",
                    "duration_ms": 123.4,
                    "ok": False,
                    "metadata": {"model": "eve-deep"},
                },
            )
            eve_tracing.record_span(
                db_path,
                name="model_call:reply_stream_synthesis",
                category="model_call",
                duration_ms=123.4,
                ok=False,
                attributes={"model": "eve-deep"},
            )
            eve_db.record_llama_cpp_metrics(
                db_path,
                profile="fast",
                host="http://127.0.0.1:8080",
                ok=True,
                metrics={"llamacpp_slots_processing": 1.0},
            )
            status = eve_db.database_status(db_path)
            self.assertTrue(status["exists"])
            self.assertEqual(status["journal_mode"], "wal")
            self.assertTrue(status["single_writer_guard_enabled"])
            self.assertEqual(status["single_writer_guard"], "fcntl_file_lock")
            self.assertEqual(status["tables"]["events"], 0)
            self.assertEqual(status["tables"]["perf_events"], 1)
            self.assertEqual(status["tables"]["trace_spans"], 1)
            self.assertEqual(status["tables"]["llama_cpp_metrics"], 1)

    def test_database_status_is_read_only_and_never_takes_the_writer_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "operational_state.sqlite3"
            eve_db.initialize_database(db_path)
            eve_db.record_event(db_path, kind="health.probe", stream="system")

            with patch.object(
                eve_db,
                "initialize_database",
                side_effect=AssertionError("status must not initialize the database"),
            ), patch.object(
                eve_db,
                "single_writer_lock",
                side_effect=AssertionError("status must not take the writer lock"),
            ):
                status = eve_db.database_status(db_path)

            self.assertTrue(status["exists"])
            self.assertTrue(status["readable"])
            self.assertTrue(status["read_only_probe"])
            self.assertEqual(status["error"], "")
            self.assertEqual(status["tables"]["events"], 1)

            with eve_db.connect_database(db_path, read_only=True) as conn:
                with self.assertRaises(sqlite3.OperationalError):
                    conn.execute("CREATE TABLE status_probe_must_not_write (id TEXT)")

    def test_database_status_reports_corruption_without_raising(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "operational_state.sqlite3"
            db_path.write_bytes(b"not a sqlite database")

            status = eve_db.database_status(db_path)

            self.assertTrue(status["exists"])
            self.assertFalse(status["readable"])
            self.assertEqual(status["journal_mode"], "unknown")
            self.assertIn("DatabaseError", status["error"])

    def test_typed_event_spine_round_trips_and_filters_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "operational_state.sqlite3"
            first = eve_db.record_event(
                db_path,
                kind="capability.tryout.completed",
                source="autonomy_free_run",
                actor="eve",
                stream="autonomy",
                subject="coder_mode_probe",
                correlation_id="corr-1",
                payload={"ok": True, "verification": "passed"},
                metadata={"model": "eve-fast"},
            )
            second = eve_db.record_event(
                db_path,
                kind="chat.message.received",
                source="cli",
                actor="user",
                stream="chat",
                subject="architecture",
                correlation_id="corr-2",
                causation_id=first["id"],
                payload={"text": "use the event spine"},
            )

            autonomy_events = eve_db.read_events(db_path, stream="autonomy")
            self.assertEqual(len(autonomy_events), 1)
            self.assertEqual(autonomy_events[0]["kind"], "capability.tryout.completed")
            self.assertEqual(autonomy_events[0]["payload"]["verification"], "passed")
            self.assertEqual(autonomy_events[0]["metadata"]["model"], "eve-fast")

            chat_events = eve_db.read_events(db_path, kind="chat.message.received")
            self.assertEqual(chat_events[0]["id"], second["id"])
            self.assertEqual(chat_events[0]["causation_id"], first["id"])

            correlated = eve_db.read_events(db_path, correlation_id="corr-1")
            self.assertEqual([event["id"] for event in correlated], [first["id"]])

            contract = eve_db.event_contract()
            self.assertIn("autonomy", contract["recommended_streams"])
            self.assertIn("action", contract["recommended_streams"])
            self.assertIn("payload", contract["required_fields"])

            status = eve_db.database_status(db_path)
            self.assertEqual(status["tables"]["events"], 2)

    def test_prometheus_metric_parser_keeps_numeric_samples(self) -> None:
        payload = """
        # HELP llamacpp_slots_processing Number of processing slots.
        llamacpp_slots_processing 1
        llamacpp_prompt_tokens_total{model="eve-fast"} 42
        bad_metric nope
        """
        metrics = eve_tracing.parse_prometheus_metrics(payload)
        self.assertEqual(metrics["llamacpp_slots_processing"], 1.0)
        self.assertEqual(metrics['llamacpp_prompt_tokens_total{model="eve-fast"}'], 42.0)
        self.assertNotIn("bad_metric", metrics)

    def test_model_governor_warns_or_skips_repeated_failures(self) -> None:
        events = [
            {
                "timestamp": eve_model_governor.utc_now(),
                "category": "model_call",
                "name": "reply_stream_synthesis",
                "ok": False,
                "metadata": {"model": "eve-deep", "host": "http://127.0.0.1:8081"},
            },
            {
                "timestamp": eve_model_governor.utc_now(),
                "category": "model_call",
                "name": "reply_stream_synthesis",
                "ok": False,
                "metadata": {"model": "eve-deep", "host": "http://127.0.0.1:8081"},
            },
        ]
        config = {
            "model_governor_enabled": True,
            "model_governor_enforce": False,
            "model_governor_failure_threshold": 2,
            "model_governor_failure_window_minutes": 20,
        }
        warning = eve_model_governor.decide(
            config,
            events,
            model="eve-deep",
            operation="reply_stream_synthesis",
            host="http://127.0.0.1:8081",
        )
        self.assertEqual(warning["action"], "warn")

        config["model_governor_enforce"] = True
        blocked = eve_model_governor.decide(
            config,
            events,
            model="eve-deep",
            operation="reply_stream_synthesis",
            host="http://127.0.0.1:8081",
        )
        self.assertEqual(blocked["action"], "skip")

    def test_model_governor_skips_repeated_context_overflow_even_without_global_enforcement(self) -> None:
        events = [
            {
                "timestamp": eve_model_governor.utc_now(),
                "category": "model_call",
                "name": "outreach_generate",
                "ok": False,
                "metadata": {
                    "model": "eve-fast",
                    "host": "http://127.0.0.1:8080",
                    "error": "{'type': 'exceed_context_size_error', 'n_prompt_tokens': 11066, 'n_ctx': 8192}",
                },
            },
            {
                "timestamp": eve_model_governor.utc_now(),
                "category": "model_call",
                "name": "outreach_generate",
                "ok": False,
                "metadata": {
                    "model": "eve-fast",
                    "host": "http://127.0.0.1:8080",
                    "error": "{'message': 'request exceeds the available context size', 'n_prompt_tokens': 11101, 'n_ctx': 8192}",
                },
            },
        ]
        decision = eve_model_governor.decide(
            {
                "model_governor_enabled": True,
                "model_governor_enforce": False,
                "model_governor_context_overflow_enforce": True,
                "model_governor_failure_threshold": 2,
                "model_governor_failure_window_minutes": 20,
            },
            events,
            model="eve-fast",
            operation="outreach_generate",
            host="http://127.0.0.1:8080",
        )

        self.assertEqual("skip", decision["action"])
        self.assertEqual(2, decision["context_overflow_failure_count"])

    def test_llama_cpp_profile_specs_surface_draft_model_config(self) -> None:
        specs = {spec["profile"]: spec for spec in eve.llama_cpp_profile_specs(
            {
                "llama_cpp_draft_hf_repo": "google/gemma-4-E2B-it-assistant",
                "llama_cpp_draft_tokens": 8,
                "llama_cpp_draft_min_tokens": 1,
            }
        )}

        fast = specs["fast"]
        self.assertTrue(fast["speculative_decoding_enabled"])
        self.assertEqual("draft_hf_repo", fast["speculative_decoding_mode"])
        self.assertEqual("google/gemma-4-E2B-it-assistant", fast["draft_hf_repo"])
        self.assertEqual(8, fast["draft_tokens"])
        self.assertEqual(1, fast["draft_min_tokens"])

    def test_dynamic_component_watchlist_tracks_configured_draft_repo(self) -> None:
        watchlist = eve.dynamic_component_watchlist(
            {"deep_llama_cpp_draft_hf_repo": "google/gemma-4-26B-A4B-it-assistant"}
        )

        draft = next(
            item
            for item in watchlist
            if item.get("config_field") == "deep_llama_cpp_draft_hf_repo"
        )
        self.assertEqual("huggingface_model", draft["kind"])
        self.assertEqual("google/gemma-4-26B-A4B-it-assistant", draft["model_repo"])
        self.assertIn("target-plus-drafter", draft["adoption"])

    def test_component_update_blocks_known_bad_python_latest(self) -> None:
        component = {
            "id": "numpy-techlab",
            "name": "NumPy numeric package",
            "kind": "python_package",
            "package": "numpy",
            "blocked_versions": ["2.4.4"],
            "blocked_version_reason": "import hung in techlab",
        }

        with patch("eve.load_component_update_state", return_value={"components": []}), patch(
            "eve.component_watchlist",
            return_value=[component],
        ), patch(
            "eve.python_package_local_version",
            return_value={"ok": True, "version": "2.4.3", "detail": "2.4.3"},
        ), patch(
            "eve.pypi_package_info",
            return_value={"ok": True, "latest_version": "2.4.4", "url": "https://pypi.org/project/numpy/"},
        ), patch(
            "eve.save_component_update_state",
            side_effect=lambda state: state,
        ), patch("eve.append_entry"):
            state = eve.check_component_updates({}, timeout=1)

        record = state["components"][0]
        self.assertFalse(record["update_available"])
        self.assertEqual("2.4.4", record["blocked_latest_version"])
        self.assertEqual("import hung in techlab", record["blocked_version_reason"])
        self.assertEqual("current_or_baselined", record["status"])

    def test_single_writer_lock_timeout_diagnostics(self) -> None:
        import os
        import threading
        import time
        from eve_db import single_writer_lock

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            lock_acquired_event = threading.Event()
            stop_thread_event = threading.Event()
            thread_error = []

            def holder_thread() -> None:
                try:
                    with single_writer_lock(db_path, timeout_seconds=1.0):
                        lock_acquired_event.set()
                        while not stop_thread_event.is_set():
                            time.sleep(0.01)
                except Exception as e:
                    thread_error.append(e)

            t = threading.Thread(target=holder_thread)
            t.start()

            try:
                self.assertTrue(lock_acquired_event.wait(timeout=2.0))
                with self.assertRaises(TimeoutError) as ctx:
                    with single_writer_lock(db_path, timeout_seconds=0.1):
                        pass
                self.assertIn("current holder:", str(ctx.exception))
                self.assertIn(f"pid={os.getpid()}", str(ctx.exception))
                self.assertIn("thread=", str(ctx.exception))
            finally:
                stop_thread_event.set()
                t.join()

            self.assertEqual(thread_error, [])


if __name__ == "__main__":
    unittest.main()
