import unittest

import eve


class DaemonLoopProfileTests(unittest.TestCase):
    """Which jobs run is a switch the operator sets, not a rewrite: absent config is today's behaviour."""

    OPTIONAL = ["nervous_system", "openclaw_sync", "openclaw_routines", "component_updates", "capability_scout", "capability_integration", "capability_intelligence", "capability_adoption", "quiet_consolidation", "self_awareness_perturbation", "episode_extraction", "beads_bridge"]
    CORE = ["mind_tick", "thought", "reflection", "proposal", "self_change", "outreach", "experiment_review", "heartbeat", "system_tasks", "failure_review"]

    def test_absent_config_runs_everything(self):
        for job in self.OPTIONAL + self.CORE:
            self.assertTrue(eve.daemon_job_enabled({}, job), job)
            self.assertTrue(eve.daemon_job_enabled(dict(eve.DEFAULT_CONFIG), job), job)

    def test_core_runs_the_original_loop_and_nothing_else(self):
        config = dict(eve.DEFAULT_CONFIG, daemon_loop_profile="core")
        for job in self.CORE:
            self.assertTrue(eve.daemon_job_enabled(config, job), job)
        for job in self.OPTIONAL + ["presence_cycle", "developmental_cycle", "autonomy_run"]:
            self.assertFalse(eve.daemon_job_enabled(config, job), job)

    def test_core_body_adds_her_body_and_free_runs(self):
        config = dict(eve.DEFAULT_CONFIG, daemon_loop_profile="core_body")
        for job in self.CORE + ["presence_cycle", "developmental_cycle", "autonomy_run"]:
            self.assertTrue(eve.daemon_job_enabled(config, job), job)
        for job in self.OPTIONAL:
            self.assertFalse(eve.daemon_job_enabled(config, job), job)

    def test_an_override_beats_the_profile_in_both_directions(self):
        config = dict(eve.DEFAULT_CONFIG, daemon_loop_profile="core", daemon_job_overrides={"capability_adoption": True, "proposal": False})
        self.assertTrue(eve.daemon_job_enabled(config, "capability_adoption"))
        self.assertFalse(eve.daemon_job_enabled(config, "proposal"))
        full = dict(eve.DEFAULT_CONFIG, daemon_job_overrides={"beads_bridge": False})
        self.assertFalse(eve.daemon_job_enabled(full, "beads_bridge"))
        self.assertTrue(eve.daemon_job_enabled(full, "capability_adoption"))

    def test_an_unknown_profile_is_treated_as_full(self):
        config = dict(eve.DEFAULT_CONFIG, daemon_loop_profile="whatever")
        self.assertTrue(eve.daemon_job_enabled(config, "beads_bridge"))

    def test_every_guarded_job_name_is_known_to_the_profile_sets(self):
        import inspect, re
        source = inspect.getsource(eve.run_daemon_cycle)
        guarded = set(re.findall(r'daemon_job_enabled\(config, "([a-z_]+)"\)', source))
        self.assertEqual(15, len(guarded), sorted(guarded))
        # a guarded job that is in neither set is "full only", which is the intent for all fifteen
        self.assertEqual(set(), guarded & eve.CORE_LOOP_JOBS - {"presence_cycle", "developmental_cycle", "autonomy_run"})
        self.assertEqual({"presence_cycle", "developmental_cycle", "autonomy_run"}, guarded & eve.CORE_BODY_JOBS)


if __name__ == "__main__":
    unittest.main()
