import unittest
from datetime import datetime, timezone
from unittest import mock

import eve
import eve_sensory


NOW = "2026-08-23T13:00:00+00:00"


def event(
    summary,
    *,
    event_id="event-1",
    modality="system",
    source="test",
    subject="machine",
    observed_at=NOW,
    **values,
):
    return {
        "id": event_id,
        "observed_at": observed_at,
        "modality": modality,
        "source": source,
        "subject": subject,
        "summary": summary,
        "precision": 90,
        **values,
    }


class SensoryAttentionTests(unittest.TestCase):
    def test_cli_exposes_bounded_status_and_tick_surfaces(self):
        parser = eve.build_parser()

        status = parser.parse_args(["sensory", "status", "--runtime", "--full"])
        tick = parser.parse_args(["sensory", "tick", "--no-event"])
        hardware = parser.parse_args(
            [
                "infra",
                "nervous",
                "sense",
                "--session",
                "sensory-test",
                "--modality",
                "proprioceptive",
                "--features-json",
                '{"contact_count":1}',
            ]
        )

        self.assertIs(status.func, eve.cmd_sensory_status)
        self.assertTrue(status.runtime)
        self.assertTrue(status.full)
        self.assertIs(tick.func, eve.cmd_sensory_tick)
        self.assertTrue(tick.no_event)
        self.assertIs(hardware.func, eve.cmd_infra_nervous)
        self.assertEqual("sense", hardware.nervous_action)
        self.assertEqual("proprioceptive", hardware.modality)

    def test_hardware_bridge_keeps_session_token_out_of_process_arguments(self):
        args = eve.build_parser().parse_args(
            [
                "infra",
                "nervous",
                "sense",
                "--session",
                "sensory-test",
                "--modality",
                "proprioceptive",
                "--features-json",
                '{"contact_count":1}',
                "--json",
            ]
        )
        secret = "session-secret-that-must-not-appear-on-argv"
        completed = mock.Mock(stdout="{}\n", stderr="", returncode=0)
        with (
            mock.patch.dict("os.environ", {"EVE_SENSORY_SESSION_TOKEN": secret}),
            mock.patch.object(eve, "go_executable_path", return_value="go"),
            mock.patch.object(eve.subprocess, "run", return_value=completed) as run,
        ):
            self.assertEqual(0, eve.cmd_infra_nervous(args))

        command = run.call_args.args[0]
        self.assertIn("sense", command)
        self.assertIn("EVE_SENSORY_SESSION_TOKEN", command)
        self.assertNotIn(secret, command)
        self.assertNotIn("--session-token", command)

    def test_repetition_habituates_without_erasing_safety_or_direct_human_signals(self):
        repeated = event("fan hum", novelty=25, intensity=40)
        first = eve_sensory.build_frame([repeated], now=NOW)
        second = eve_sensory.build_frame(
            [repeated],
            prior_frame=first,
            now="2026-08-23T13:00:20+00:00",
        )

        self.assertEqual(2, second["winner"]["repeat_count"])
        self.assertTrue(second["winner"]["habituated"])
        self.assertLess(
            second["winner"]["attention_score"],
            first["winner"]["attention_score"],
        )

        human = event(
            "the user asked Eve a direct question",
            event_id="human-1",
            modality="social",
            source="chat",
            subject="user",
            direct_human=True,
            social_relevance=100,
        )
        current = eve_sensory.build_frame([human], now=NOW)
        for index in range(6):
            current = eve_sensory.build_frame(
                [human],
                prior_frame=current,
                now=f"2026-08-23T13:0{index + 1}:00+00:00",
            )
        self.assertGreaterEqual(current["winner"]["attention_score"], 80)
        self.assertEqual("orient", current["winner"]["disposition"])

    def test_changed_signal_dishabituates_on_the_same_channel(self):
        first = eve_sensory.build_frame(
            [event("steady fan", event_id="fan-a", novelty=15)],
            now=NOW,
        )
        repeated = eve_sensory.build_frame(
            [event("steady fan", event_id="fan-b", novelty=15)],
            prior_frame=first,
            now="2026-08-23T13:00:20+00:00",
        )
        changed = eve_sensory.build_frame(
            [event("fan stopped suddenly", event_id="fan-c", novelty=15)],
            prior_frame=repeated,
            now="2026-08-23T13:00:40+00:00",
        )

        self.assertTrue(repeated["winner"]["habituated"])
        self.assertTrue(changed["winner"]["dishabituated"])
        self.assertEqual(1, changed["winner"]["repeat_count"])
        self.assertGreaterEqual(changed["winner"]["change"], 90)
        self.assertGreater(
            changed["winner"]["attention_score"],
            repeated["winner"]["attention_score"],
        )

    def test_spontaneous_recovery_after_a_quiet_gap(self):
        first = eve_sensory.build_frame([event("clock tick")], now=NOW)
        repeated = eve_sensory.build_frame(
            [event("clock tick", event_id="tick-2")],
            prior_frame=first,
            now="2026-08-23T13:00:20+00:00",
        )
        recovered = eve_sensory.build_frame(
            [event("clock tick", event_id="tick-3")],
            prior_frame=repeated,
            now="2026-08-23T13:10:00+00:00",
        )

        self.assertEqual(1, recovered["winner"]["repeat_count"])
        self.assertGreater(
            recovered["winner"]["attention_score"],
            repeated["winner"]["attention_score"],
        )

    def test_cross_modal_binding_requires_shared_entity_and_time(self):
        events = [
            event(
                "the user spoke",
                event_id="audio-user",
                modality="auditory",
                subject="user",
                permission_granted=True,
                observed_at="2026-08-23T13:00:00+00:00",
            ),
            event(
                "the user entered view",
                event_id="visual-user",
                modality="visual",
                subject="user",
                permission_granted=True,
                observed_at="2026-08-23T13:00:02+00:00",
            ),
            event(
                "unrelated service changed",
                event_id="system-service",
                modality="system",
                subject="service",
                observed_at="2026-08-23T13:00:01+00:00",
            ),
        ]
        frame = eve_sensory.build_frame(events, now=NOW)

        self.assertEqual(1, frame["bound_episode_count"])
        episode = next(item for item in frame["working_set"] if item["modality"] == "multisensory")
        self.assertEqual(["auditory", "visual"], episode["modalities"])
        self.assertEqual("user", episode["subject"])
        self.assertNotIn("system-service", episode["member_ids"])

    def test_working_set_is_sparse_and_goal_relevant_signal_beats_noise(self):
        noise = [
            event(
                f"irrelevant hum {index}",
                event_id=f"noise-{index}",
                subject=f"noise-{index}",
                intensity=20,
                novelty=10,
                urgency=0,
                goal_relevance=0,
                self_relevance=0,
                precision=60,
            )
            for index in range(20)
        ]
        relevant = event(
            "A verified action contradicted Eve's prediction",
            event_id="prediction-error",
            modality="proprioceptive",
            subject="eve-action",
            novelty=95,
            change=100,
            urgency=85,
            goal_relevance=100,
            self_relevance=100,
        )
        frame = eve_sensory.build_frame([*noise, relevant], now=NOW, capacity=4)

        self.assertEqual(4, len(frame["working_set"]))
        self.assertEqual("prediction-error", frame["winner"]["id"])
        self.assertEqual(17, frame["ignored_count"])

    def test_sensitive_input_retains_features_not_content_or_raw_fields(self):
        normalized = eve_sensory.normalize_event(
            {
                **event(
                    "private spoken medical detail",
                    event_id="sensitive-audio",
                    modality="auditory",
                    privacy="sensitive",
                ),
                "raw_content": "must disappear",
                "audio": b"must disappear",
                "transcript": "must disappear",
            },
            now=NOW,
        )

        self.assertNotIn("medical detail", normalized["summary"])
        self.assertEqual("features_only", normalized["persistence"])
        self.assertTrue(normalized["requires_permission"])
        for field in eve_sensory.RAW_FIELDS:
            self.assertNotIn(field, normalized)

    def test_private_adapter_fails_closed_before_raw_content_reaches_normalization(self):
        with self.assertRaisesRegex(ValueError, "raw sensor content is forbidden"):
            eve_sensory.normalize_adapter_event(
                {
                    "modality": "visual",
                    "permission_granted": True,
                    "features": {"motion_percent": 40},
                    "debug": {"pixels": [1, 2, 3]},
                },
                allowed_modalities=["visual"],
                session_id="sensory-session-1",
                now=NOW,
            )

        with self.assertRaisesRegex(ValueError, "raw sensor content is forbidden"):
            eve_sensory.normalize_adapter_event(
                {
                    "modality": "auditory",
                    "permission_granted": True,
                    "features": {"energy_percent": 30},
                    "transcript": "private spoken words",
                },
                allowed_modalities=["auditory"],
                session_id="sensory-session-1",
                now=NOW,
            )

    def test_private_adapter_accepts_only_bounded_features_and_backend_generated_summary(self):
        with self.assertRaisesRegex(ValueError, "unknown sensory feature"):
            eve_sensory.normalize_adapter_event(
                {
                    "modality": "visual",
                    "permission_granted": True,
                    "features": {"motion_percent": 40, "unknown_future_field": "must reject"},
                },
                allowed_modalities=["visual"],
                session_id="sensory-session-1",
                now=NOW,
            )

        normalized = eve_sensory.normalize_adapter_event(
            {
                "id": "camera event 1",
                "modality": "visual",
                "source": "eve_app_camera_features",
                "subject": "Local Scene",
                "correlation_id": "sensory-session-1:scene:1",
                "summary": "caller prose must not survive",
                "permission_granted": True,
                "features": {
                    "motion_percent": 140,
                    "scene_state": "movement",
                },
            },
            allowed_modalities=["visual"],
            session_id="sensory-session-1",
            now=NOW,
        )

        self.assertEqual("eve_app_camera_features", normalized["source"])
        self.assertEqual("local_scene", normalized["subject"])
        self.assertEqual(100, normalized["features"]["motion_percent"])
        self.assertEqual("movement", normalized["features"]["scene_state"])
        self.assertNotIn("caller prose", normalized["summary"])
        self.assertNotEqual("camera_event_1", normalized["id"])
        self.assertTrue(normalized["private_adapter_event"])
        self.assertFalse(normalized["direct_human"])
        self.assertFalse(normalized["safety_critical"])

    def test_private_adapter_requires_current_session_modality_permission_and_correlation(self):
        with self.assertRaisesRegex(ValueError, "not admitted"):
            eve_sensory.normalize_adapter_event(
                {"modality": "visual", "permission_granted": True},
                allowed_modalities=["auditory"],
                session_id="sensory-session-1",
                now=NOW,
            )
        with self.assertRaisesRegex(ValueError, "requires current device permission"):
            eve_sensory.normalize_adapter_event(
                {"modality": "auditory", "permission_granted": False},
                allowed_modalities=["auditory"],
                session_id="sensory-session-1",
                now=NOW,
            )
        with self.assertRaisesRegex(ValueError, "requires current device permission"):
            eve_sensory.normalize_adapter_event(
                {
                    "modality": "auditory",
                    "permission_granted": "true",
                    "features": {"energy_percent": 10},
                },
                allowed_modalities=["auditory"],
                session_id="sensory-session-1",
                now=NOW,
            )
        with self.assertRaisesRegex(ValueError, "belong to the current session"):
            eve_sensory.normalize_adapter_event(
                {
                    "modality": "visual",
                    "permission_granted": True,
                    "correlation_id": "sensory-another-session:scene:1",
                },
                allowed_modalities=["visual"],
                session_id="sensory-session-1",
                now=NOW,
            )
        with self.assertRaisesRegex(ValueError, "belong to the current session"):
            eve_sensory.normalize_adapter_event(
                {
                    "modality": "visual",
                    "permission_granted": True,
                    "correlation_id": "sensory-session-1-covert-suffix",
                    "features": {"motion_percent": 20},
                },
                allowed_modalities=["visual"],
                session_id="sensory-session-1",
                now=NOW,
            )
        with self.assertRaisesRegex(ValueError, "must be boolean"):
            eve_sensory.normalize_adapter_event(
                {
                    "modality": "proprioceptive",
                    "features": {"active": "false"},
                },
                allowed_modalities=["proprioceptive"],
                session_id="sensory-session-1",
                now=NOW,
            )
        with self.assertRaisesRegex(ValueError, "must be a finite number"):
            eve_sensory.normalize_adapter_event(
                {
                    "modality": "proprioceptive",
                    "features": {"contact_count": 10**1_000},
                },
                allowed_modalities=["proprioceptive"],
                session_id="sensory-session-1",
                now=NOW,
            )
        with self.assertRaisesRegex(ValueError, "must be a finite number"):
            eve_sensory.normalize_adapter_event(
                {
                    "modality": "proprioceptive",
                    "features": {"contact_count": 1},
                    "novelty": float("nan"),
                },
                allowed_modalities=["proprioceptive"],
                session_id="sensory-session-1",
                now=NOW,
            )

    def test_private_visual_or_audio_orienting_is_a_permission_gated_proposal(self):
        frame = eve_sensory.build_frame(
            [
                event(
                    "camera detected change",
                    modality="visual",
                    novelty=100,
                    change=100,
                    urgency=90,
                    goal_relevance=90,
                    self_relevance=90,
                )
            ],
            now=NOW,
        )

        request = frame["orienting_request"]
        self.assertEqual("request_sensor_permission", request["recommended_action"])
        self.assertTrue(request["requires_permission"])
        self.assertEqual("proposal_only", request["authority"])
        self.assertFalse(frame["privacy"]["raw_images_retained"])

    def test_permitted_private_senses_propose_active_sampling_without_self_authorizing(self):
        auditory = eve_sensory.normalize_adapter_event(
            {
                "modality": "auditory",
                "permission_granted": True,
                "features": {"activity_state": "speech_like", "sound_change_percent": 90},
                "novelty": 100,
                "change": 100,
                "urgency": 90,
                "goal_relevance": 90,
                "self_relevance": 90,
            },
            allowed_modalities=["auditory"],
            session_id="sensory-session-1",
            now=NOW,
        )
        frame = eve_sensory.build_frame([auditory], now=NOW)

        self.assertEqual("listen_for_more_evidence", frame["orienting_request"]["recommended_action"])
        self.assertEqual("proposal_only", frame["orienting_request"]["authority"])
        self.assertFalse(frame["orienting_request"]["requires_permission"])
        self.assertTrue(frame["privacy"]["private_device_features_observed"])

    def test_private_feature_bins_dishabituate_real_change_without_tracking_tiny_jitter(self):
        def visual(motion: int, observed_at: str):
            return eve_sensory.normalize_adapter_event(
                {
                    "modality": "visual",
                    "permission_granted": True,
                    "observed_at": observed_at,
                    "features": {"motion_percent": motion, "scene_state": "movement"},
                },
                allowed_modalities=["visual"],
                session_id="sensory-session-1",
                now=observed_at,
            )

        first = eve_sensory.build_frame([visual(21, NOW)], now=NOW)
        jitter = eve_sensory.build_frame(
            [visual(22, "2026-08-23T13:00:10+00:00")],
            prior_frame=first,
            now="2026-08-23T13:00:10+00:00",
        )
        changed = eve_sensory.build_frame(
            [visual(78, "2026-08-23T13:00:20+00:00")],
            prior_frame=jitter,
            now="2026-08-23T13:00:20+00:00",
        )

        self.assertEqual(first["winner"]["fingerprint"], jitter["winner"]["fingerprint"])
        self.assertTrue(jitter["winner"]["habituated"])
        self.assertNotEqual(jitter["winner"]["fingerprint"], changed["winner"]["fingerprint"])
        self.assertTrue(changed["winner"]["dishabituated"])

    def test_feature_only_entity_tracks_continue_across_frames(self):
        first = eve_sensory.build_frame(
            [
                event(
                    "movement changed",
                    event_id="visual-1",
                    modality="visual",
                    subject="local_scene",
                    permission_granted=True,
                    features={"scene_state": "movement", "motion_percent": 45},
                )
            ],
            now=NOW,
        )
        second = eve_sensory.build_frame(
            [
                event(
                    "sound changed",
                    event_id="audio-1",
                    modality="auditory",
                    subject="local_scene",
                    permission_granted=True,
                    observed_at="2026-08-23T13:00:02+00:00",
                    features={"activity_state": "sound", "energy_percent": 30},
                )
            ],
            prior_frame=first,
            now="2026-08-23T13:00:02+00:00",
        )

        self.assertEqual(1, second["entity_track_count"])
        track = second["entity_tracks"][0]
        self.assertEqual(2, track["observation_count"])
        self.assertEqual(["auditory", "visual"], track["modalities"])
        self.assertEqual("features_only", track["persistence"])

    def test_inhibition_of_return_prevents_an_unchanged_signal_from_looping(self):
        stimulus = event(
            "novel system warning",
            intensity=80,
            novelty=100,
            change=45,
            urgency=80,
            goal_relevance=90,
            self_relevance=90,
        )
        first = eve_sensory.build_frame([stimulus], now=NOW)
        second = eve_sensory.build_frame(
            [stimulus],
            prior_frame=first,
            now="2026-08-23T13:00:20+00:00",
        )

        self.assertGreater(first["winner"]["attention_score"], second["winner"]["attention_score"])
        self.assertGreater(
            second["winner"]["score_components"]["inhibition_of_return"],
            0,
        )

    def test_empty_frame_is_quiet_and_does_not_manufacture_an_action(self):
        frame = eve_sensory.build_frame([], now=NOW)

        self.assertEqual("quiet", frame["status"])
        self.assertEqual({}, frame["winner"])
        self.assertEqual({}, frame["orienting_request"])
        self.assertEqual([], frame["working_set"])

    def test_runtime_collector_fuses_only_admitted_typed_inputs(self):
        now = datetime(2026, 8, 23, 13, 0, tzinfo=timezone.utc)
        with (
            mock.patch.object(
                eve,
                "read_lived_messages",
                return_value=[
                    {
                        "id": "human-message",
                        "timestamp": NOW,
                        "sender": "user",
                        "thread_id": "thread-1",
                        "body": "Please inspect the new signal.",
                    }
                ],
            ),
            mock.patch.object(
                eve,
                "load_system_snapshot",
                return_value={
                    "timestamp": NOW,
                    "load_state": "busy",
                    "model_summary": "models resident",
                    "disk": {"strict_used_percent": 70},
                },
            ),
            mock.patch.object(
                eve,
                "load_homeostasis",
                return_value={
                    "updated_at": NOW,
                    "pressures": [
                        {"id": "uncertainty", "label": "uncertainty", "level": 60, "trend": "rising"}
                    ],
                },
            ),
            mock.patch.object(
                eve,
                "read_action_executions",
                return_value=[
                    {
                        "id": "action-1",
                        "created_at": NOW,
                        "action": "inspect",
                        "verification_ok": True,
                        "summary": "The local check verified.",
                    }
                ],
            ),
            mock.patch.object(
                eve,
                "read_organ_pulses",
                return_value=[
                    {
                        "generated_at": NOW,
                        "organs": [
                            {"id": "sensor", "label": "Sensor adapter", "operational_status": "partial"}
                        ],
                    }
                ],
            ),
            mock.patch.object(eve.eve_db, "read_events", return_value=[]),
        ):
            observations = eve.collect_runtime_sensory_events(
                eve.DEFAULT_CONFIG,
                prefer_runtime=False,
                now=now,
            )

        self.assertEqual(
            {"social", "system", "interoceptive", "proprioceptive", "world"},
            {item["modality"] for item in observations},
        )

    def test_runtime_collector_does_not_replay_an_old_human_turn_as_perception(self):
        now = datetime(2026, 8, 23, 13, 0, tzinfo=timezone.utc)
        with (
            mock.patch.object(
                eve,
                "read_lived_messages",
                return_value=[
                    {
                        "id": "old-human-message",
                        "timestamp": "2026-08-23T12:30:00+00:00",
                        "sender": "user",
                        "body": "This is memory now, not a current stimulus.",
                    }
                ],
            ),
            mock.patch.object(eve, "load_system_snapshot", return_value={}),
            mock.patch.object(eve, "load_homeostasis", return_value={}),
            mock.patch.object(eve, "read_action_executions", return_value=[]),
            mock.patch.object(eve, "read_organ_pulses", return_value=[]),
            mock.patch.object(eve.eve_db, "read_events", return_value=[]),
        ):
            observations = eve.collect_runtime_sensory_events(
                {"sensory_attention_window_seconds": 180},
                prefer_runtime=False,
                now=now,
            )

        self.assertEqual([], observations)
        self.assertTrue(all(item["source"] for item in observations))
        self.assertTrue(all(item["persistence"] == "features_only" for item in observations))
        for item in observations:
            self.assertFalse(eve_sensory.RAW_FIELDS.intersection(item))

    def test_runtime_tick_persists_semantic_change_once_without_executing_body_action(self):
        now = datetime(2026, 8, 23, 13, 0, tzinfo=timezone.utc)
        direct = event(
            "the user asked a question",
            event_id="direct-human",
            modality="social",
            source="chat",
            subject="user",
            direct_human=True,
            social_relevance=100,
        )
        state = {}
        with (
            mock.patch.object(eve, "collect_runtime_sensory_events", return_value=[direct]),
            mock.patch.object(eve.eve_db, "record_event") as record_event,
        ):
            first = eve.run_sensory_attention_tick(
                eve.DEFAULT_CONFIG,
                state,
                source="test",
                prefer_runtime=False,
                now=now,
            )
            second = eve.run_sensory_attention_tick(
                eve.DEFAULT_CONFIG,
                state,
                source="test",
                prefer_runtime=False,
                now=datetime(2026, 8, 23, 13, 0, 20, tzinfo=timezone.utc),
            )

        self.assertEqual("attend_to_human_message", first["orienting_request"]["recommended_action"])
        self.assertEqual("proposal_only", first["orienting_request"]["authority"])
        self.assertEqual("direct-human", second["winner"]["id"])
        record_event.assert_called_once()
        self.assertIn("sensory_frame", state)
        self.assertNotIn("action_execution", state)


if __name__ == "__main__":
    unittest.main()
