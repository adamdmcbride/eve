"""bin/eve_loop_metrics.py computes the section-9 measures from a fixture .eve store, read-only."""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIN_DIR = ROOT / "bin"
FIXTURES_DIR = ROOT / "tests" / "fixtures"


def _load_module(name, path):
    """Load a script by path without putting bin/ or fixtures/ on sys.path.

    Inserting bin/ at sys.path[0] for the whole session made later plain imports
    (for example ``import eve_sensory_eval``) resolve to the bin/ CLI wrapper of the
    same name instead of the repo-root module.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


eve_loop_metrics = _load_module("eve_loop_metrics_under_test", BIN_DIR / "eve_loop_metrics.py")
loop_metrics_store = _load_module("loop_metrics_store_under_test", FIXTURES_DIR / "loop_metrics_store.py")

NOW = datetime(2026, 9, 17, 0, 0, 0, tzinfo=timezone.utc)
SCRIPT = BIN_DIR / "eve_loop_metrics.py"


def _mtimes(root):
    out = {}
    for path in sorted(Path(root).rglob("*")):
        if path.is_file():
            out[str(path)] = os.stat(str(path)).st_mtime_ns
    return out


class LoopMetricsFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="eve-loop-metrics-")
        cls.eve_dir = loop_metrics_store.build_fixture(Path(cls._tmp.name) / ".eve")
        cls.before = _mtimes(cls.eve_dir)
        cls.metrics = eve_loop_metrics.compute_metrics(cls.eve_dir, days=7, now=NOW)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_window(self):
        window = self.metrics["window"]
        self.assertEqual(window["days"], 7.0)
        self.assertEqual(window["since"], "2026-09-10T00:00:00+00:00")
        self.assertEqual(window["until"], "2026-09-17T00:00:00+00:00")
        self.assertEqual(self.metrics["eve_dir"], str(self.eve_dir))
        for name in eve_loop_metrics.SOURCE_FILES:
            self.assertNotIn("missing", self.metrics["sources"][name], name)

    def test_compute_is_read_only(self):
        self.assertEqual(_mtimes(self.eve_dir), self.before)
        self.assertFalse((self.eve_dir / "operational_state.sqlite3-journal").exists())
        self.assertFalse((self.eve_dir / "operational_state.sqlite3-wal").exists())

    def test_journal_lived_share(self):
        journal = self.metrics["journal"]
        self.assertEqual(journal["rows_total"], 15)
        self.assertEqual(journal["rows_in_window"], 13)
        self.assertEqual(journal["lived"], 3)
        self.assertEqual(journal["telemetry"], 10)
        self.assertEqual(journal["lived_share"], round(3 / 13.0, 4))
        self.assertEqual(journal["rows_per_week"], 13.0)
        self.assertEqual(journal["lived_kinds"], {"thought": 1, "user_request": 1, "reflection": 1})
        self.assertEqual(journal["telemetry_kinds_top"]["cycle_skipped"], 3)
        self.assertEqual(journal["telemetry_kinds_top"]["mind_tick"], 3)

    def test_reflection_context_lived_share(self):
        reflection = self.metrics["reflection"]
        self.assertEqual(reflection["reflections_total"], 2)
        self.assertEqual(reflection["reflections_in_window"], 1)
        self.assertEqual(reflection["reflections_per_week"], 1.0)
        self.assertEqual(reflection["with_lived_kinds_metadata"], 0)
        self.assertEqual(reflection["context_rows"], 4)
        self.assertEqual(reflection["context_lived"], 2)
        self.assertEqual(reflection["context_lived_share"], 0.5)
        self.assertEqual(
            reflection["last_reflection_context_kinds"],
            {"cycle_skipped": 1, "thought": 1, "mind_tick": 1, "user_request": 1},
        )
        only = reflection["per_reflection"][0]
        self.assertEqual(only["timestamp"], "2026-09-15T12:00:00+00:00")
        self.assertEqual(only["source_entries"], 4)
        self.assertEqual(only["model"], "eve-deep")

    def test_tensions_per_week_with_source_reflection(self):
        tensions = self.metrics["tensions"]
        self.assertEqual(tensions["rows_total"], 3)
        self.assertEqual(tensions["rows_in_window"], 2)
        self.assertEqual(tensions["per_week"], 2.0)
        self.assertEqual(tensions["with_source_reflection"], 1)
        self.assertEqual(tensions["with_source_reflection_per_week"], 1.0)
        self.assertEqual(tensions["sources"], {"reflection": 1, "(none)": 1})

    def test_experiments_closed_on_evidence(self):
        experiments = self.metrics["experiments"]
        self.assertEqual(experiments["rows_total"], 4)
        self.assertEqual(experiments["status_counts"], {"completed": 2, "expired_unverified": 1, "active": 1})
        self.assertEqual(experiments["closed_total"], 2)
        self.assertEqual(experiments["closed_on_evidence_total"], 1)
        self.assertEqual(experiments["closed_in_window"], 2)
        self.assertEqual(experiments["closed_on_evidence_in_window"], 1)
        self.assertEqual(experiments["closed_on_evidence_per_week"], 1.0)
        self.assertEqual(experiments["expired_unverified_total"], 1)
        self.assertEqual(experiments["expired_unverified_share_in_window"], round(1 / 3.0, 4))

    def test_proposal_lineage_and_duplicate_titles(self):
        proposals = self.metrics["proposals"]
        self.assertEqual(proposals["rows_total"], 6)
        self.assertEqual(proposals["status_counts"], {"draft": 4, "applied": 1, "archived": 1})
        self.assertEqual(proposals["drafts"], 4)
        self.assertEqual(proposals["proposals_created_in_window"], 5)
        self.assertEqual(proposals["drafts_created_in_window"], 4)
        self.assertEqual(proposals["drafts_with_tension_ids"], 2)
        self.assertEqual(proposals["drafts_with_rollback"], 1)
        self.assertEqual(proposals["drafts_with_lineage"], 1)
        self.assertEqual(proposals["drafts_lineage_share"], 0.25)
        self.assertEqual(proposals["duplicate_title_draft_rows"], 2)
        self.assertEqual(proposals["duplicate_titles"], {"repair degraded local eve services": 2})

    def test_self_change_ledger(self):
        all_time = self.metrics["self_change"]["all_time"]
        self.assertEqual(all_time["rows"], 5)
        self.assertEqual(all_time["outcome_counts"], {"failed": 1, "applied": 3, "no_change": 1})
        self.assertEqual(all_time["failed"], 1)
        self.assertEqual(all_time["failed_rate"], 0.2)
        self.assertEqual(all_time["applied"], 3)
        self.assertEqual(all_time["applied_with_consequence"], 2)
        self.assertEqual(all_time["applied_with_before_json"], 1)
        self.assertEqual(all_time["applied_with_rollback"], 0)
        self.assertEqual(all_time["unfinished"], 0)
        self.assertEqual(
            all_time["duplicate_proposal_titles"],
            {"repair degraded local eve services": 2, "route proposals to the fast lane": 2},
        )
        window = self.metrics["self_change"]["in_window"]
        self.assertEqual(window["rows"], 4)
        self.assertEqual(window["failed"], 0)
        self.assertEqual(window["failed_rate"], 0.0)
        self.assertEqual(window["applied"], 3)

    def test_mind_ticks_parsed(self):
        ticks = self.metrics["mind_ticks"]
        for key in ("journal_all_time", "journal_in_window", "journal_last_50"):
            self.assertEqual(ticks[key]["rows"], 3, key)
            self.assertEqual(ticks[key]["used_fallback_false"], 1, key)
            self.assertEqual(ticks[key]["parsed_share"], round(1 / 3.0, 4), key)
        self.assertEqual(ticks["journal_in_window"]["model_counts"], {"deterministic": 2, "eve-fast": 1})
        self.assertEqual(
            ticks["journal_in_window"]["fallback_reason_top"],
            {"background model tick failed: Could not parse": 1, "System load is hot": 1},
        )
        transport = ticks["transport_in_window"]
        self.assertEqual(transport, {"calls": 2, "ok": 1, "ok_rate": 0.5, "truncated": 1})

    def test_daemon_messages_per_day_by_kind(self):
        messages = self.metrics["daemon_messages"]
        self.assertEqual(messages["eve_rows_in_window"], 5)
        self.assertEqual(messages["replies"], 1)
        self.assertEqual(messages["daemon_rows"], 4)
        self.assertEqual(messages["daemon_rows_to_user"], 4)
        self.assertEqual(messages["per_day"], round(4 / 7.0, 2))
        self.assertEqual(messages["loop_kind_rows"], 2)
        self.assertEqual(messages["loop_kind_share"], 0.5)
        self.assertEqual(messages["by_kind"], {"upgrade_review_update": 2, "proactive_outreach": 1, "reflection_update": 1})
        self.assertEqual(messages["by_kind_per_day"]["upgrade_review_update"], round(2 / 7.0, 2))

    def test_llama_cpp_calls_per_lane_and_operation(self):
        calls = self.metrics["model_calls"]
        total = calls["llama_cpp"]
        self.assertEqual(total["calls"], 5)
        self.assertEqual(total["ok"], 3)
        self.assertEqual(total["ok_rate"], 0.6)
        self.assertEqual(total["wall_hours"], round(3604000 / 3600000.0, 3))
        self.assertEqual(total["per_day"], round(5 / 7.0, 2))
        self.assertEqual(total["backends_seen"], {"llama_cpp": 5, "ollama": 1})
        self.assertEqual(total["model_call_rows_all_backends"], 6)
        self.assertEqual(total["truncated"], 1)
        self.assertEqual(total["errors_top"], {"timeout": 1, "parse": 1})
        spine = calls["spine"]
        self.assertEqual(spine["source"], "sqlite:ro")
        self.assertEqual(spine["errors"], [])
        self.assertTrue(spine["sqlite_present"])
        self.assertFalse(spine["wal_sidecar_present"])
        lanes = calls["per_lane"]
        self.assertEqual(sorted(lanes), ["eve-deep", "eve-fast", "eve-observer"])
        self.assertEqual(lanes["eve-fast"]["calls"], 2)
        self.assertEqual(lanes["eve-fast"]["ok"], 1)
        self.assertEqual(lanes["eve-fast"]["ok_rate"], 0.5)
        self.assertEqual(lanes["eve-fast"]["wall_hours"], 0.001)
        self.assertEqual(lanes["eve-deep"]["calls"], 2)
        self.assertEqual(lanes["eve-deep"]["ok"], 1)
        self.assertEqual(lanes["eve-deep"]["wall_hours"], 1.0)
        self.assertEqual(lanes["eve-observer"], {"calls": 1, "ok": 1, "ok_rate": 1.0, "wall_hours": 0.0, "per_day": round(1 / 7.0, 2)})
        self.assertEqual(calls["operations_total"], 3)
        ops = calls["per_operation_top_by_wall"]
        self.assertEqual([op["operation"] for op in ops], ["reflection", "continuous_thought", "daemon_model_mind_tick"])
        self.assertEqual(ops[0]["lanes"], {"eve-deep": 1})
        self.assertEqual(ops[1]["calls"], 2)
        self.assertEqual(ops[1]["ok"], 1)
        self.assertEqual(ops[2]["lanes"], {"eve-deep": 1, "eve-observer": 1})

    def test_cycle_skipped_by_gate(self):
        skipped = self.metrics["cycle_skipped"]
        self.assertEqual(skipped["rows_total"], 3)
        self.assertEqual(skipped["rows_in_window"], 3)
        self.assertEqual(skipped["per_week"], 3.0)
        self.assertEqual(skipped["by_gate"], {"system": 2, "quiet_period": 1})
        self.assertEqual(skipped["by_gate_per_week"], {"system": 2.0, "quiet_period": 1.0})
        self.assertEqual(
            skipped["by_job_top"],
            {"thought skipped": 1, "quiet consolidation skipped": 1, "self change skipped": 1},
        )

    def test_daemon_error_per_day(self):
        errors = self.metrics["daemon_error"]
        self.assertEqual(errors["rows_total"], 2)
        self.assertEqual(errors["rows_in_window"], 2)
        self.assertEqual(errors["per_day"], round(2 / 7.0, 2))
        self.assertEqual(errors["top_texts"], {"ambient model thought failed": 1, "reflection failed": 1})

    def test_actions_and_disk(self):
        actions = self.metrics["actions"]
        self.assertEqual(actions["rows_total"], 4)
        self.assertEqual(actions["rows_in_window"], 3)
        self.assertEqual(actions["result_ok"], 2)
        self.assertEqual(actions["result_ok_rate"], round(2 / 3.0, 4))
        self.assertEqual(actions["by_action_top"], {"system_tasks": 2, "openclaw_log_check": 1})
        self.assertEqual(actions["by_source_top"], {"daemon": 2, "autonomy_free_run": 1})
        disk = self.metrics["disk"]
        self.assertGreater(disk["free_bytes"], 0)
        self.assertGreater(disk["total_gib"], disk["free_gib"] - 1)
        self.assertEqual(disk["path"], str(self.eve_dir))

    def test_shorter_window_changes_the_counts(self):
        # one day back from NOW starts at 2026-09-16T00:00 (inclusive): two cycle_skipped and two daemon_error rows
        narrow = eve_loop_metrics.compute_metrics(self.eve_dir, days=1, now=NOW)
        self.assertEqual(narrow["window"]["since"], "2026-09-16T00:00:00+00:00")
        self.assertEqual(narrow["journal"]["rows_in_window"], 4)
        self.assertEqual(narrow["cycle_skipped"]["rows_in_window"], 2)
        self.assertEqual(narrow["cycle_skipped"]["per_week"], 14.0)
        self.assertEqual(narrow["daemon_error"]["per_day"], 2.0)
        self.assertEqual(narrow["mind_ticks"]["journal_in_window"]["rows"], 0)
        self.assertIsNone(narrow["mind_ticks"]["journal_in_window"]["parsed_share"])
        self.assertEqual(narrow["model_calls"]["llama_cpp"]["calls"], 0)
        self.assertEqual(narrow["reflection"]["reflections_in_window"], 0)


class LoopMetricsMissingStoreTests(unittest.TestCase):
    def test_missing_sqlite_and_ledgers_are_reported_not_fatal(self):
        with tempfile.TemporaryDirectory(prefix="eve-loop-metrics-empty-") as tmp:
            eve_dir = loop_metrics_store.build_fixture(Path(tmp) / ".eve", with_sqlite=False, with_perf_jsonl=False)
            (eve_dir / "tensions.jsonl").unlink()
            metrics = eve_loop_metrics.compute_metrics(eve_dir, days=7, now=NOW)
        self.assertEqual(metrics["model_calls"]["llama_cpp"]["calls"], 0)
        spine = metrics["model_calls"]["spine"]
        self.assertIsNone(spine["source"])
        self.assertFalse(spine["sqlite_present"])
        self.assertEqual(len(spine["errors"]), 2)
        self.assertTrue(spine["errors"][0].startswith("sqlite: missing"))
        self.assertTrue(spine["errors"][1].startswith("jsonl: missing"))
        self.assertEqual(metrics["model_calls"]["per_lane"], {})
        self.assertEqual(metrics["mind_ticks"]["transport_in_window"]["calls"], 0)
        self.assertEqual(metrics["tensions"]["rows_total"], 0)
        self.assertEqual(metrics["tensions"]["per_week"], 0.0)
        self.assertTrue(metrics["sources"]["tensions.jsonl"]["missing"])
        self.assertTrue(metrics["sources"]["operational_state.sqlite3"]["missing"])
        self.assertTrue(metrics["sources"]["perf_events.jsonl"]["missing"])


def _model_call_numbers(metrics):
    """Everything in the model_calls section except which source answered."""
    section = dict(metrics["model_calls"])
    section.pop("spine")
    return section


class LoopMetricsPerfSpineFallbackTests(unittest.TestCase):
    """The live spine is a WAL database; a mode=ro open fails whenever no -shm sidecar exists.

    The instrument then reads through ``immutable=1`` (never creates a sidecar) and, with no
    database at all, through the ``perf_events.jsonl`` mirror. Both must yield the same numbers.
    """

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="eve-loop-metrics-spine-")
        cls.eve_dir = loop_metrics_store.build_fixture(Path(cls._tmp.name) / ".eve")
        cls.reference = eve_loop_metrics.compute_metrics(cls.eve_dir, days=7, now=NOW)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_reference_reads_through_plain_ro(self):
        self.assertEqual(self.reference["model_calls"]["spine"]["source"], "sqlite:ro")
        self.assertEqual(self.reference["model_calls"]["llama_cpp"]["calls"], 5)

    def test_immutable_fallback_when_ro_open_cannot_create_shm(self):
        real_connect = eve_loop_metrics.sqlite3.connect
        seen = []

        def failing_connect(database, *args, **kwargs):
            seen.append(database)
            self.assertTrue(kwargs.get("uri"), "the loader must open through a URI so ?mode=ro applies")
            if "immutable=1" not in database:
                raise eve_loop_metrics.sqlite3.OperationalError("unable to open database file")
            return real_connect(database, *args, **kwargs)

        with mock.patch.object(eve_loop_metrics.sqlite3, "connect", failing_connect):
            metrics = eve_loop_metrics.compute_metrics(self.eve_dir, days=7, now=NOW)
        self.assertEqual(len(seen), 2)
        self.assertTrue(seen[0].endswith("?mode=ro"))
        self.assertTrue(seen[1].endswith("?mode=ro&immutable=1"))
        spine = metrics["model_calls"]["spine"]
        self.assertEqual(spine["source"], "sqlite:ro_immutable")
        self.assertEqual(spine["errors"], ["sqlite:ro: unable to open database file"])
        self.assertEqual(_model_call_numbers(metrics), _model_call_numbers(self.reference))
        self.assertEqual(metrics["mind_ticks"]["transport_in_window"], self.reference["mind_ticks"]["transport_in_window"])

    def test_jsonl_mirror_fallback_without_a_database(self):
        with tempfile.TemporaryDirectory(prefix="eve-loop-metrics-jsonl-") as tmp:
            eve_dir = loop_metrics_store.build_fixture(Path(tmp) / ".eve", with_sqlite=False)
            metrics = eve_loop_metrics.compute_metrics(eve_dir, days=7, now=NOW)
        spine = metrics["model_calls"]["spine"]
        self.assertEqual(spine["source"], "jsonl")
        self.assertFalse(spine["sqlite_present"])
        self.assertEqual(len(spine["errors"]), 1)
        self.assertTrue(spine["errors"][0].startswith("sqlite: missing"))
        self.assertEqual(_model_call_numbers(metrics), _model_call_numbers(self.reference))
        self.assertEqual(metrics["mind_ticks"]["transport_in_window"], self.reference["mind_ticks"]["transport_in_window"])


class LoopMetricsCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="eve-loop-metrics-cli-")
        cls.eve_dir = loop_metrics_store.build_fixture(Path(cls._tmp.name) / ".eve")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _run(self, *extra):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--eve-dir", str(self.eve_dir), "--days", "7", "--now", NOW.isoformat()] + list(extra),
            capture_output=True,
            text=True,
            check=False,
        )

    def test_json_output_matches_compute(self):
        result = self._run("--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        document = json.loads(result.stdout)
        expected = eve_loop_metrics.compute_metrics(self.eve_dir, days=7, now=NOW)
        for key in ("window", "journal", "reflection", "tensions", "experiments", "proposals", "self_change", "mind_ticks", "daemon_messages", "model_calls", "cycle_skipped", "daemon_error", "actions"):
            self.assertEqual(document[key], expected[key], key)

    def test_default_mode_is_json(self):
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["journal"]["rows_in_window"], 13)

    def test_table_output(self):
        result = self._run("--table")
        self.assertEqual(result.returncode, 0, result.stderr)
        text = result.stdout
        self.assertIn("reflection context lived share                50.0% over 1 reflections", text)
        self.assertIn("journal lived share", text)
        self.assertIn("lane eve-deep", text)
        self.assertIn("cycle_skipped/week", text)
        self.assertIn("system=2, quiet_period=1", text)
        self.assertIn("top 15 llama.cpp operations by wall time:", text)
        self.assertIn("reflection", text.split("top 15 llama.cpp operations")[1])
        self.assertIn("upgrade_review_update", text)

    def test_bad_now_is_rejected(self):
        result = self._run("--now", "yesterday")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Could not parse --now", result.stderr)


if __name__ == "__main__":
    unittest.main()
