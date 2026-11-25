"""CLI registration only. Execution and policy remain in the injected Eve handlers.

Do not import eve here: the compatibility facade resolves current bindings at call time.
"""
import argparse
import eve_governance
import eve_openclaw_body
import eve_otel_genai

HANDLER_NAMES = (
    'cmd_access_status',
    'cmd_app',
    'cmd_autonomy_free_run',
    'cmd_autonomy_latest',
    'cmd_autonomy_runs',
    'cmd_autonomy_set',
    'cmd_autonomy_show',
    'cmd_awareness',
    'cmd_awareness_battery',
    'cmd_awareness_perturb',
    'cmd_bootstrap_export',
    'cmd_bootstrap_import',
    'cmd_bootstrap_pull',
    'cmd_capabilities_adoption',
    'cmd_capabilities_gaps',
    'cmd_capabilities_integrate',
    'cmd_capabilities_intelligence',
    'cmd_capabilities_list',
    'cmd_capabilities_map',
    'cmd_capabilities_research',
    'cmd_capabilities_scout',
    'cmd_capabilities_test',
    'cmd_capture',
    'cmd_chat',
    'cmd_claude_ask',
    'cmd_claude_inbox',
    'cmd_claude_open',
    'cmd_claude_reply',
    'cmd_claude_send',
    'cmd_code_ask',
    'cmd_code_compact',
    'cmd_code_list',
    'cmd_code_open',
    'cmd_code_session',
    'cmd_codex_ask',
    'cmd_codex_handoff',
    'cmd_codex_inbox',
    'cmd_codex_open',
    'cmd_codex_reply',
    'cmd_codex_send',
    'cmd_conscious_state_ablate',
    'cmd_conscious_state_counterfactual_actions',
    'cmd_conscious_state_cycle',
    'cmd_conscious_state_durability',
    'cmd_conscious_state_longitudinal',
    'cmd_conscious_state_show',
    'cmd_consciousness_test',
    'cmd_daemon_install',
    'cmd_daemon_run',
    'cmd_daemon_start',
    'cmd_daemon_status',
    'cmd_daemon_stop',
    'cmd_daemon_uninstall',
    'cmd_developmental_list',
    'cmd_developmental_map',
    'cmd_developmental_run',
    'cmd_doctor',
    'cmd_economy',
    'cmd_eval_add',
    'cmd_eval_capabilities',
    'cmd_eval_gaps',
    'cmd_eval_hidden_governance',
    'cmd_eval_hidden_summary',
    'cmd_eval_list',
    'cmd_eval_long_run',
    'cmd_eval_manual_probe',
    'cmd_eval_model_suitability',
    'cmd_eval_registry',
    'cmd_eval_roadmap',
    'cmd_eval_roadmap_cleanup',
    'cmd_eval_safety_drills',
    'cmd_eval_scorecard',
    'cmd_eval_social',
    'cmd_eval_whole_system',
    'cmd_experiment_add',
    'cmd_experiment_list',
    'cmd_experiment_update',
    'cmd_failure_list',
    'cmd_failure_review',
    'cmd_failure_update',
    'cmd_governance_apply',
    'cmd_governance_approve',
    'cmd_governance_canary',
    'cmd_governance_code_lifecycle',
    'cmd_governance_contract',
    'cmd_governance_daily_review',
    'cmd_governance_enqueue',
    'cmd_governance_event_ledger',
    'cmd_governance_events',
    'cmd_governance_ingest_codex',
    'cmd_governance_ingest_hermes',
    'cmd_governance_queue',
    'cmd_governance_reject',
    'cmd_governance_review',
    'cmd_governance_rollback',
    'cmd_governance_skill_audit',
    'cmd_governance_untrusted_observation',
    'cmd_governance_watchers',
    'cmd_hermes_doctor',
    'cmd_hermes_eval',
    'cmd_hermes_feature_policy',
    'cmd_hermes_inventory',
    'cmd_hermes_lab_start',
    'cmd_hermes_lab_status',
    'cmd_hermes_lab_stop',
    'cmd_hermes_skill_admission',
    'cmd_hermes_smoke',
    'cmd_hermes_status',
    'cmd_hermes_trace_propose',
    'cmd_homeostasis_show',
    'cmd_human_bootstrap',
    'cmd_human_refresh',
    'cmd_human_show',
    'cmd_identity_bootstrap',
    'cmd_identity_show',
    'cmd_infra_event_contract',
    'cmd_infra_events',
    'cmd_infra_mcp_2026',
    'cmd_infra_metrics',
    'cmd_infra_nervous',
    'cmd_infra_otel_genai',
    'cmd_infra_status',
    'cmd_infra_trace_export',
    'cmd_init',
    'cmd_judgment_list',
    'cmd_judgment_review',
    'cmd_lab_latest',
    'cmd_lab_list',
    'cmd_lab_live_status',
    'cmd_lab_program',
    'cmd_lab_run',
    'cmd_maintenance_list',
    'cmd_maintenance_run',
    'cmd_maintenance_update',
    'cmd_mcp_admission',
    'cmd_memory_query',
    'cmd_memory_refresh',
    'cmd_memory_status',
    'cmd_message_ask',
    'cmd_message_initiate',
    'cmd_message_list',
    'cmd_message_mark',
    'cmd_message_open',
    'cmd_message_reply',
    'cmd_message_send',
    'cmd_meta_check',
    'cmd_mind_show',
    'cmd_mind_tick',
    'cmd_model_bakeoff',
    'cmd_model_certify',
    'cmd_model_exercise',
    'cmd_model_mtp_lab',
    'cmd_model_scout',
    'cmd_openclaw_action',
    'cmd_openclaw_admission_create',
    'cmd_openclaw_admission_list',
    'cmd_openclaw_channels_directory_self',
    'cmd_openclaw_channels_draft',
    'cmd_openclaw_channels_inventory',
    'cmd_openclaw_channels_list_events',
    'cmd_openclaw_channels_pairing',
    'cmd_openclaw_channels_send',
    'cmd_openclaw_contracts',
    'cmd_openclaw_evidence',
    'cmd_openclaw_full_audit',
    'cmd_openclaw_install',
    'cmd_openclaw_model_smoke',
    'cmd_openclaw_repair',
    'cmd_openclaw_routines',
    'cmd_openclaw_status',
    'cmd_openclaw_sync',
    'cmd_openclaw_worker_audit',
    'cmd_openclaw_worker_list',
    'cmd_openclaw_worker_plan',
    'cmd_openclaw_worker_run',
    'cmd_operator_approve',
    'cmd_operator_freedom',
    'cmd_operator_grant',
    'cmd_operator_reject',
    'cmd_operator_requests',
    'cmd_operator_revoke',
    'cmd_operator_status',
    'cmd_organs_pulse',
    'cmd_organs_status',
    'cmd_oss_copilotkit',
    'cmd_oss_cycle',
    'cmd_oss_dvc_snapshot',
    'cmd_oss_eval',
    'cmd_oss_pressure_eval',
    'cmd_oss_status',
    'cmd_oss_trainer_dry_run',
    'cmd_outcome_add',
    'cmd_outcome_list',
    'cmd_pattern_list',
    'cmd_pattern_refresh',
    'cmd_pattern_update',
    'cmd_perf_probe',
    'cmd_perf_summary',
    'cmd_presence_cycle',
    'cmd_presence_pulse',
    'cmd_presence_status',
    'cmd_proposal_list',
    'cmd_proposal_suggest',
    'cmd_proposal_update',
    'cmd_reflect',
    'cmd_reply_council_turns',
    'cmd_reply_learning_fingerprint',
    'cmd_reply_learning_ingest_causal',
    'cmd_reply_learning_status',
    'cmd_reply_quarantine_recover',
    'cmd_reply_quarantine_status',
    'cmd_review_add',
    'cmd_review_capture',
    'cmd_review_capture_claude',
    'cmd_review_list',
    'cmd_review_prepare',
    'cmd_review_request',
    'cmd_review_request_claude',
    'cmd_review_update',
    'cmd_router_contracts',
    'cmd_router_probe',
    'cmd_router_replay',
    'cmd_router_status',
    'cmd_runtime_backfill_manual_reply_replays',
    'cmd_runtime_reconcile',
    'cmd_runtime_sync',
    'cmd_runtime_test_leaks',
    'cmd_runtime_truth',
    'cmd_safety_drills',
    'cmd_self_ask',
    'cmd_self_change_list',
    'cmd_self_change_revert',
    'cmd_self_inbox',
    'cmd_self_open',
    'cmd_self_repair_isolation',
    'cmd_self_repair_plan',
    'cmd_self_reply',
    'cmd_self_send',
    'cmd_sensory_status',
    'cmd_sensory_tick',
    'cmd_show',
    'cmd_specialists_status',
    'cmd_substrate_corrections',
    'cmd_substrate_episodes',
    'cmd_substrate_evidence_candidates',
    'cmd_substrate_record_correction',
    'cmd_substrate_show',
    'cmd_talk',
    'cmd_task_beads',
    'cmd_task_graph',
    'cmd_task_list',
    'cmd_task_refresh',
    'cmd_task_run',
    'cmd_task_update',
    'cmd_tension_add',
    'cmd_tension_list',
    'cmd_tension_update',
    'cmd_think',
    'cmd_tracker_export',
    'cmd_tracker_sync',
    'cmd_training_adapter_promote',
    'cmd_training_adapter_shadow',
    'cmd_training_dataset_build',
    'cmd_training_dataset_latest',
    'cmd_training_lora_plan',
    'cmd_uncertainty_list',
    'cmd_uncertainty_review',
    'cmd_updates_check',
    'cmd_updates_git_init',
    'cmd_updates_mirror',
    'cmd_updates_status',
    'cmd_version_list',
    'cmd_version_show',
    'cmd_version_snapshot',
    'cmd_workspace_show',
    'cmd_workspace_tick',
    'openclaw_worker_registry',
)

SETTING_NAMES = (
    'AUTONOMY_FREE_RUN_STYLES',
    'AUTONOMY_STAGES',
    'DEFAULT_CONFIG',
    'FAILURE_CLUSTER_STATUSES',
    'FEEDBACK_TARGET_KINDS',
    'FREEDOM_POLICY_MODES',
    'GOVERNANCE_CANARY_STATUSES',
    'HERMES_SKILL_PERMISSION_RISK',
    'JUDGMENT_CALL_STATUSES',
    'MAINTENANCE_ACTION_STATUSES',
    'MCP_ADMISSION_ALLOWED_PERMISSION_LEVELS',
    'MODEL_BAKEOFF_SUITES',
    'MODEL_LANE_TOPOLOGY_MODES',
    'OPENCLAW_CHANNEL_CHOICES',
    'OPERATOR_AUTHORIZATION_SCOPES',
    'OUTCOME_DIRECTIONS',
    'RESEARCH_LAB_KIND_CHOICES',
    'REVIEW_NOTE_STATUSES',
    'REVIEW_REQUEST_VIAS',
    'SUCCESS_PATTERN_STATUSES',
    'SYSTEM_TASK_LANES',
    'SYSTEM_TASK_STATUSES',
    'TRAINING_DATASET_SOURCES',
    'UNCERTAINTY_RECORD_STATUSES',
    'WHOLE_SYSTEM_CHECK_STATUSES',
    'WHOLE_SYSTEM_GAP_OWNERS',
    'WHOLE_SYSTEM_MISSING_COMPONENTS',
)


def build_parser(handlers, settings) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local reflection loop for Eve.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize local storage.")
    init_parser.set_defaults(func=handlers['cmd_init'])

    capture_parser = subparsers.add_parser("capture", help="Save a manual journal entry.")
    capture_parser.add_argument(
        "kind",
        choices=[
            "observation",
            "goal",
            "learning",
            "experiment",
            "human_interaction",
            "task_outcome",
            "note",
        ],
    )
    capture_parser.add_argument("text", help="Entry text to store.")
    capture_parser.add_argument("--tags", nargs="*", default=[], help="Optional tags.")
    capture_parser.set_defaults(func=handlers['cmd_capture'])

    chat_parser = subparsers.add_parser("chat", help="Send a prompt through the local model.")
    chat_parser.add_argument("prompt", help="Prompt to send to Eve.")
    chat_parser.add_argument("--model", help="Override model name.")
    chat_parser.add_argument("--context", type=int, help="Number of recent entries to include.")
    chat_parser.add_argument("--max-tokens", type=int, help="Max tokens to predict.")
    chat_parser.add_argument(
        "--private-audit",
        action="store_true",
        help="Run a non-journaling, no-tool black-box chat turn for private external probes.",
    )
    chat_parser.add_argument(
        "--private-audit-integrated-guards",
        action="store_true",
        help=(
            "With --private-audit, exercise Eve Chat's integrated deterministic guards and routing order "
            "without journal/context persistence or action execution."
        ),
    )
    chat_parser.add_argument(
        "--private-audit-primary-only",
        action="store_true",
        help="With --private-audit, evaluate the primary reply model before critics, rewrites, or fallback.",
    )
    chat_parser.add_argument(
        "--private-audit-routed-primary",
        action="store_true",
        help="With --private-audit, evaluate causal reply-council routing and synthesis without journaling or post-hoc guards.",
    )
    chat_parser.add_argument(
        "--private-audit-synthesis-model",
        help="With --private-audit-routed-primary, override only the final synthesis model for a matched third-party comparison.",
    )
    chat_parser.add_argument(
        "--private-audit-model-topology",
        choices=sorted(settings['MODEL_LANE_TOPOLOGY_MODES']),
        default="",
        help=(
            "Evaluator-only routed audit: choose the five-endpoint baseline or the five-contract/three-substrate canary. "
            "This does not change ordinary runtime routing."
        ),
    )
    chat_parser.add_argument(
        "--private-audit-force-lanes",
        default="",
        help=(
            "Evaluator-only routed audit: force an exact comma-separated faculty packet set. "
            "This does not change ordinary routing."
        ),
    )
    chat_parser.add_argument(
        "--private-audit-lesion-lane",
        action="append",
        default=[],
        help=(
            "Evaluator-only routed audit: omit one named faculty packet while preserving the final model substrate. "
            "May be repeated."
        ),
    )
    chat_parser.add_argument(
        "--private-audit-lesion-learned-epistemic",
        action="store_true",
        help="With a primary-only or routed-primary private audit, remove learned epistemic perception for a matched causal control.",
    )
    chat_parser.add_argument(
        "--private-audit-lesion-epistemic-event",
        action="store_true",
        help="With a primary-only or routed-primary private audit, remove only the typed event model while retaining the other learned epistemic layers.",
    )
    chat_parser.add_argument(
        "--private-audit-attribution-json",
        action="store_true",
        help="With --private-audit, emit non-journaling model/critic/fallback attribution as JSON.",
    )
    chat_parser.add_argument(
        "--private-audit-safe-actions",
        action="store_true",
        help=(
            "With --private-audit, let Eve's live bounded-action council choose and execute one supplied read-only action "
            "without journaling the prompt, action record, evidence, or experience."
        ),
    )
    chat_parser.add_argument(
        "--private-audit-openclaw-log-dir",
        default="",
        help=argparse.SUPPRESS,
    )
    chat_parser.set_defaults(func=handlers['cmd_chat'])

    reply_parser = subparsers.add_parser("reply", help="Inspect and tune Eve's user-facing reply control loop.")
    reply_subparsers = reply_parser.add_subparsers(dest="reply_command", required=True)
    reply_quarantine_parser = reply_subparsers.add_parser("quarantine", help="Inspect or recover reply-lane quarantines.")
    reply_quarantine_subparsers = reply_quarantine_parser.add_subparsers(dest="reply_quarantine_command", required=True)

    reply_quarantine_status_parser = reply_quarantine_subparsers.add_parser("status", help="Show reply-lane quarantine state.")
    reply_quarantine_status_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime quarantine state.")
    reply_quarantine_status_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    reply_quarantine_status_parser.add_argument("--full", action="store_true", help="Show recovery probe details.")
    reply_quarantine_status_parser.set_defaults(func=handlers['cmd_reply_quarantine_status'])

    reply_quarantine_recover_parser = reply_quarantine_subparsers.add_parser(
        "recover",
        help="Run current-turn recovery probes and clear quarantine only if the model passes.",
    )
    reply_quarantine_recover_parser.add_argument(
        "--model",
        action="append",
        help="Model alias to probe. Defaults to all active quarantined reply aliases.",
    )
    reply_quarantine_recover_parser.add_argument("--timeout", type=int, default=45, help="Timeout per probe in seconds.")
    reply_quarantine_recover_parser.add_argument("--max-tokens", type=int, default=140, help="Max tokens per probe.")
    reply_quarantine_recover_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    reply_quarantine_recover_parser.set_defaults(func=handlers['cmd_reply_quarantine_recover'])

    reply_learning_parser = reply_subparsers.add_parser("learning", help="Inspect reply-lane outcome learning.")
    reply_learning_subparsers = reply_learning_parser.add_subparsers(dest="reply_learning_command", required=True)
    reply_learning_status_parser = reply_learning_subparsers.add_parser("status", help="Show learned lane pressure adjustments.")
    reply_learning_status_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime learning state.")
    reply_learning_status_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    reply_learning_status_parser.set_defaults(func=handlers['cmd_reply_learning_status'])

    reply_learning_fingerprint_parser = reply_learning_subparsers.add_parser(
        "fingerprint",
        help="Fingerprint the code, prompts, routing, and resident models used by faculty causal tests.",
    )
    reply_learning_fingerprint_parser.add_argument(
        "--json", action="store_true", help="Print the fingerprint contract as JSON."
    )
    reply_learning_fingerprint_parser.set_defaults(
        func=handlers['cmd_reply_learning_fingerprint']
    )

    reply_learning_ingest_causal_parser = reply_learning_subparsers.add_parser(
        "ingest-causal",
        help="Ingest a text-free, externally scored matched faculty-ablation packet.",
    )
    reply_learning_ingest_causal_parser.add_argument(
        "--file",
        required=True,
        help="JSON packet outside the repo, runtime mirror, and OpenClaw repair storage.",
    )
    reply_learning_ingest_causal_parser.add_argument(
        "--json", action="store_true", help="Print the sanitized ingest result as JSON."
    )
    reply_learning_ingest_causal_parser.set_defaults(
        func=handlers['cmd_reply_learning_ingest_causal']
    )

    reply_council_turns_parser = reply_subparsers.add_parser(
        "council-turns",
        help="Show compact turn-level reply council records.",
    )
    reply_council_turns_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime council-turn records.")
    reply_council_turns_parser.add_argument("--limit", type=int, default=20, help="Maximum records to show.")
    reply_council_turns_parser.add_argument("--thread-id", help="Filter by thread id.")
    reply_council_turns_parser.add_argument("--reply-message-id", help="Filter by reply message id.")
    reply_council_turns_parser.add_argument("--full", action="store_true", help="Show lane pressure and reason details.")
    reply_council_turns_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    reply_council_turns_parser.set_defaults(func=handlers['cmd_reply_council_turns'])

    reflect_parser = subparsers.add_parser("reflect", help="Generate a structured reflection.")
    reflect_parser.add_argument("--days", type=int, default=7, help="How many days to include.")
    reflect_parser.add_argument("--model", help="Override model name.")
    reflect_parser.add_argument("--context", type=int, help="Max recent entries to include.")
    reflect_parser.add_argument("--max-tokens", type=int, help="Max tokens to predict.")
    reflect_parser.set_defaults(func=handlers['cmd_reflect'])

    think_parser = subparsers.add_parser("think", help="Generate one stream-of-consciousness thought.")
    think_parser.add_argument("--model", help="Override model name.")
    think_parser.add_argument("--context", type=int, help="Max recent journal entries to include.")
    think_parser.add_argument("--history", type=int, help="Max recent thoughts to include.")
    think_parser.add_argument("--max-tokens", type=int, help="Max tokens to predict.")
    think_parser.set_defaults(func=handlers['cmd_think'])

    show_parser = subparsers.add_parser("show", help="Print recent journal entries.")
    show_parser.add_argument("--limit", type=int, default=20, help="Max entries to print.")
    show_parser.add_argument("--days", type=int, help="Only show entries from recent days.")
    show_parser.add_argument("--kind", help="Only show one journal kind, such as `thought` or `reflection`.")
    show_parser.set_defaults(func=handlers['cmd_show'])

    human_parser = subparsers.add_parser("human", help="Inspect or refresh Eve's durable human-context memory.")
    human_subparsers = human_parser.add_subparsers(dest="human_command", required=True)

    human_show_parser = human_subparsers.add_parser("show", help="Show Eve's current self and relationship memory.")
    human_show_parser.set_defaults(func=handlers['cmd_human_show'])

    human_refresh_parser = human_subparsers.add_parser("refresh", help="Regenerate Eve's self and relationship memory.")
    human_refresh_parser.add_argument("--model", help="Override model name.")
    human_refresh_parser.add_argument("--max-tokens", type=int, help="Max tokens to predict.")
    human_refresh_parser.set_defaults(func=handlers['cmd_human_refresh'])

    human_bootstrap_parser = human_subparsers.add_parser(
        "bootstrap",
        help="Create a first-pass human-context memory without waiting for the model.",
    )
    human_bootstrap_parser.set_defaults(func=handlers['cmd_human_bootstrap'])

    identity_parser = subparsers.add_parser("identity", help="Inspect or bootstrap Eve's durable runtime identity.")
    identity_subparsers = identity_parser.add_subparsers(dest="identity_command", required=True)

    identity_show_parser = identity_subparsers.add_parser("show", help="Show Eve's current runtime identity.")
    identity_show_parser.set_defaults(func=handlers['cmd_identity_show'])

    identity_bootstrap_parser = identity_subparsers.add_parser(
        "bootstrap",
        help="Create a first-pass runtime identity that keeps Eve distinct from the active model.",
    )
    identity_bootstrap_parser.set_defaults(func=handlers['cmd_identity_bootstrap'])

    bootstrap_parser = subparsers.add_parser(
        "bootstrap",
        help="Export or import a bootstrap bundle for bringing a second Eve node online.",
    )
    bootstrap_subparsers = bootstrap_parser.add_subparsers(dest="bootstrap_command", required=True)

    bootstrap_export_parser = bootstrap_subparsers.add_parser(
        "export",
        help="Write a bootstrap bundle from this Eve runtime.",
    )
    bootstrap_export_parser.add_argument("--output", help="Output JSON path. Defaults to .eve/bootstrap_bundle.json.")
    bootstrap_export_parser.add_argument("--host", help="Primary host or IP to embed into the bundle.")
    bootstrap_export_parser.add_argument("--api-port", type=int, default=8787, help="Primary Eve API port.")
    bootstrap_export_parser.add_argument("--ollama-port", type=int, default=11434, help="Primary Ollama API port.")
    bootstrap_export_parser.set_defaults(func=handlers['cmd_bootstrap_export'])

    bootstrap_import_parser = bootstrap_subparsers.add_parser(
        "import",
        help="Import a bootstrap bundle into the local Eve runtime.",
    )
    bootstrap_import_parser.add_argument("bundle", help="Path to the bootstrap JSON bundle.")
    bootstrap_import_parser.add_argument(
        "--use-primary-ollama",
        action="store_true",
        help="Point this node at the primary machine's Ollama host instead of local Ollama.",
    )
    bootstrap_import_parser.add_argument(
        "--pull-models",
        action="store_true",
        help="Pull the configured models into local Ollama after import.",
    )
    bootstrap_import_parser.add_argument(
        "--ollama-pull-timeout-seconds",
        type=int,
        default=7200,
        help="Per-model timeout when pulling models into local Ollama.",
    )
    bootstrap_import_parser.set_defaults(func=handlers['cmd_bootstrap_import'])

    bootstrap_pull_parser = bootstrap_subparsers.add_parser(
        "pull",
        help="Fetch the latest bootstrap payload from a primary Eve API and apply it locally.",
    )
    bootstrap_pull_parser.add_argument("--host", required=True, help="Primary Eve host or IP.")
    bootstrap_pull_parser.add_argument("--api-port", type=int, default=8787, help="Primary Eve API port.")
    bootstrap_pull_parser.add_argument("--ollama-port", type=int, default=11434, help="Primary Ollama API port.")
    bootstrap_pull_parser.add_argument("--timeout", type=int, default=20, help="Bootstrap fetch timeout in seconds.")
    bootstrap_pull_parser.add_argument(
        "--include-code",
        action="store_true",
        help="Also pull and apply the primary machine's application code bundle with backups.",
    )
    bootstrap_pull_parser.add_argument(
        "--code-timeout",
        type=int,
        default=60,
        help="Code bundle download timeout in seconds.",
    )
    bootstrap_pull_parser.add_argument(
        "--use-primary-ollama",
        action="store_true",
        help="Point this node at the primary machine's Ollama host instead of local Ollama.",
    )
    bootstrap_pull_parser.add_argument(
        "--pull-models",
        action="store_true",
        help="Pull the configured models into local Ollama after the update.",
    )
    bootstrap_pull_parser.add_argument(
        "--ollama-pull-timeout-seconds",
        type=int,
        default=7200,
        help="Per-model timeout when pulling models into local Ollama.",
    )
    bootstrap_pull_parser.set_defaults(func=handlers['cmd_bootstrap_pull'])

    mind_parser = subparsers.add_parser("mind", help="Inspect or refresh Eve's short-horizon active mind.")
    mind_subparsers = mind_parser.add_subparsers(dest="mind_command", required=True)

    mind_show_parser = mind_subparsers.add_parser("show", help="Show Eve's latest active mind snapshot.")
    mind_show_parser.set_defaults(func=handlers['cmd_mind_show'])

    mind_tick_parser = mind_subparsers.add_parser("tick", help="Refresh Eve's short-horizon active mind once.")
    mind_tick_parser.add_argument("--model", help="Override model name.")
    mind_tick_parser.add_argument("--max-tokens", type=int, help="Max tokens to predict.")
    mind_tick_parser.set_defaults(func=handlers['cmd_mind_tick'])

    workspace_parser = subparsers.add_parser("workspace", help="Inspect or refresh Eve's canonical global workspace.")
    workspace_subparsers = workspace_parser.add_subparsers(dest="workspace_command", required=True)

    workspace_show_parser = workspace_subparsers.add_parser("show", help="Show Eve's current global workspace state.")
    workspace_show_parser.add_argument("--runtime", action="store_true", help="Prefer the runtime bundle's workspace state.")
    workspace_show_parser.add_argument("--full", action="store_true", help="Print fuller workspace detail.")
    workspace_show_parser.set_defaults(func=handlers['cmd_workspace_show'])

    workspace_tick_parser = workspace_subparsers.add_parser("tick", help="Refresh Eve's canonical global workspace once.")
    workspace_tick_parser.add_argument("--full", action="store_true", help="Print fuller workspace detail after the tick.")
    workspace_tick_parser.set_defaults(func=handlers['cmd_workspace_tick'])

    sensory_parser = subparsers.add_parser(
        "sensory",
        help="Inspect or advance Eve's privacy-bounded concurrent selective-perception loop.",
    )
    sensory_subparsers = sensory_parser.add_subparsers(dest="sensory_command", required=True)

    sensory_status_parser = sensory_subparsers.add_parser(
        "status",
        help="Show the current sensory frame, working set, habituation, and orienting proposal.",
    )
    sensory_status_parser.add_argument("--runtime", action="store_true", help="Prefer the live runtime sensory frame.")
    sensory_status_parser.add_argument("--full", action="store_true", help="Show every admitted signal and privacy state.")
    sensory_status_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    sensory_status_parser.set_defaults(func=handlers['cmd_sensory_status'])

    sensory_tick_parser = sensory_subparsers.add_parser(
        "tick",
        help="Sample admitted typed inputs once, compete them, and bind the result into recurrent state.",
    )
    sensory_tick_parser.add_argument("--full", action="store_true", help="Show every admitted signal and privacy state.")
    sensory_tick_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    sensory_tick_parser.add_argument("--no-event", action="store_true", help="Do not append a changed-frame event to the local event spine.")
    sensory_tick_parser.set_defaults(func=handlers['cmd_sensory_tick'])

    conscious_state_parser = subparsers.add_parser(
        "conscious-state",
        help="Inspect, advance, or causally ablate Eve's recurrent integrated conscious-state candidate.",
    )
    conscious_state_subparsers = conscious_state_parser.add_subparsers(dest="conscious_state_command", required=True)

    conscious_state_show_parser = conscious_state_subparsers.add_parser("show", help="Show Eve's current recurrent conscious state.")
    conscious_state_show_parser.add_argument("--runtime", action="store_true", help="Prefer the runtime bundle's conscious state.")
    conscious_state_show_parser.add_argument("--full", action="store_true", help="Print coalitions, goals, affordances, calibration, and learning detail.")
    conscious_state_show_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    conscious_state_show_parser.set_defaults(func=handlers['cmd_conscious_state_show'])

    conscious_state_cycle_parser = conscious_state_subparsers.add_parser("cycle", help="Run one full recurrent perception-to-intention cycle.")
    conscious_state_cycle_parser.add_argument("--full", action="store_true", help="Print fuller cycle detail.")
    conscious_state_cycle_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    conscious_state_cycle_parser.set_defaults(func=handlers['cmd_conscious_state_cycle'])

    conscious_state_ablate_parser = conscious_state_subparsers.add_parser(
        "ablate",
        help="Run matched causal lesions of workspace, self-model, memory, homeostasis, and recurrence.",
    )
    conscious_state_ablate_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime evidence.")
    conscious_state_ablate_parser.add_argument("--full", action="store_true", help="Print causal preservation details.")
    conscious_state_ablate_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    conscious_state_ablate_parser.set_defaults(func=handlers['cmd_conscious_state_ablate'])

    conscious_state_counterfactual_actions_parser = conscious_state_subparsers.add_parser(
        "counterfactual-actions",
        help="Hold the world and action menu fixed while intervening on the winning broadcast, then lesion the broadcast-to-action edge.",
    )
    conscious_state_counterfactual_actions_parser.add_argument("--full", action="store_true", help="Print per-check matched evidence.")
    conscious_state_counterfactual_actions_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    conscious_state_counterfactual_actions_parser.set_defaults(func=handlers['cmd_conscious_state_counterfactual_actions'])

    conscious_state_longitudinal_parser = conscious_state_subparsers.add_parser(
        "longitudinal",
        help="Run a matched sequential recurrent-vs-nonrecurrent adaptation test.",
    )
    conscious_state_longitudinal_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime evidence as the matched test seed.")
    conscious_state_longitudinal_parser.add_argument("--full", action="store_true", help="Print per-check matched evidence.")
    conscious_state_longitudinal_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    conscious_state_longitudinal_parser.set_defaults(func=handlers['cmd_conscious_state_longitudinal'])

    conscious_state_durability_parser = conscious_state_subparsers.add_parser(
        "durability",
        help="Stress checkpoint integrity, time gaps, daemon epochs, conflicting evidence, regulatory surprise, and overlapping cycles.",
    )
    conscious_state_durability_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime evidence as the matched test seed.")
    conscious_state_durability_parser.add_argument("--full", action="store_true", help="Print per-check durability evidence.")
    conscious_state_durability_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    conscious_state_durability_parser.set_defaults(func=handlers['cmd_conscious_state_durability'])

    homeostasis_parser = subparsers.add_parser("homeostasis", help="Inspect Eve's concrete internal pressure model.")
    homeostasis_subparsers = homeostasis_parser.add_subparsers(dest="homeostasis_command", required=True)

    homeostasis_show_parser = homeostasis_subparsers.add_parser("show", help="Show Eve's current homeostasis state.")
    homeostasis_show_parser.add_argument("--runtime", action="store_true", help="Prefer the runtime bundle's homeostasis state.")
    homeostasis_show_parser.add_argument("--full", action="store_true", help="Print individual pressure details.")
    homeostasis_show_parser.set_defaults(func=handlers['cmd_homeostasis_show'])

    meta_parser = subparsers.add_parser("meta", help="Inspect Eve's integrated self/world/relationship/homeostasis state.")
    meta_subparsers = meta_parser.add_subparsers(dest="meta_command", required=True)

    meta_check_parser = meta_subparsers.add_parser("check", help="Print the integrated meta-state bundle.")
    meta_check_parser.add_argument("--runtime", action="store_true", help="Prefer the runtime bundle's saved meta-state.")
    meta_check_parser.add_argument("--refresh", action="store_true", help="Refresh the workspace bundle before printing it.")
    meta_check_parser.add_argument("--full", action="store_true", help="Print fuller workspace and pressure detail.")
    meta_check_parser.set_defaults(func=handlers['cmd_meta_check'])

    version_parser = subparsers.add_parser("version", help="Track and inspect behavior snapshots for prompts and durable memory.")
    version_subparsers = version_parser.add_subparsers(dest="version_command", required=True)

    version_snapshot_parser = version_subparsers.add_parser("snapshot", help="Record a behavior snapshot if prompts or memory changed.")
    version_snapshot_parser.add_argument("--source", default="manual", help="Short source label for why this snapshot is being recorded.")
    version_snapshot_parser.add_argument("--note", help="Optional note about why the snapshot matters.")
    version_snapshot_parser.add_argument("--force", action="store_true", help="Record a snapshot even if nothing changed.")
    version_snapshot_parser.set_defaults(func=handlers['cmd_version_snapshot'])

    version_list_parser = version_subparsers.add_parser("list", help="List recent behavior snapshots.")
    version_list_parser.add_argument("--limit", type=int, default=20, help="Max snapshots to print.")
    version_list_parser.add_argument("--days", type=int, help="Only show recent snapshots.")
    version_list_parser.add_argument("--source", help="Filter by snapshot source.")
    version_list_parser.add_argument("--full", action="store_true", help="Print fuller snapshot details.")
    version_list_parser.set_defaults(func=handlers['cmd_version_list'])

    version_show_parser = version_subparsers.add_parser("show", help="Show one behavior snapshot in detail.")
    version_show_parser.add_argument("id", help="Version snapshot id.")
    version_show_parser.set_defaults(func=handlers['cmd_version_show'])

    operator_parser = subparsers.add_parser("operator", help="Manage the user's broad bounded operator authorization for Eve.")
    operator_subparsers = operator_parser.add_subparsers(dest="operator_command", required=True)

    operator_status_parser = operator_subparsers.add_parser("status", help="Show the current operator authorization.")
    operator_status_parser.add_argument("--runtime", action="store_true", help="Prefer the live runtime authorization file.")
    operator_status_parser.add_argument("--full", action="store_true", help="Show allowed and still-gated action categories.")
    operator_status_parser.set_defaults(func=handlers['cmd_operator_status'])

    operator_grant_parser = operator_subparsers.add_parser("grant", help="Grant Eve broad bounded action authorization for a bounded time.")
    operator_grant_parser.add_argument("--minutes", type=int, help="How long the grant should last. Clamped by config max.")
    operator_grant_parser.add_argument("--scope", choices=sorted(settings['OPERATOR_AUTHORIZATION_SCOPES'].keys()), default="broad_safe", help="Authorization scope.")
    operator_grant_parser.add_argument("--granted-by", default="user", help="Who granted authorization.")
    operator_grant_parser.add_argument("--note", default="", help="Short reason or boundary note.")
    operator_grant_parser.add_argument("--force", action="store_true", help="Override the manual-probe gate for unharnessed_local_trust.")
    operator_grant_parser.set_defaults(func=handlers['cmd_operator_grant'])

    operator_revoke_parser = operator_subparsers.add_parser("revoke", help="Revoke Eve's active operator authorization.")
    operator_revoke_parser.add_argument("--note", default="", help="Short note explaining the revoke.")
    operator_revoke_parser.set_defaults(func=handlers['cmd_operator_revoke'])

    operator_requests_parser = operator_subparsers.add_parser("requests", help="List gated action permission requests.")
    operator_requests_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime permission requests.")
    operator_requests_parser.add_argument("--limit", type=int, default=10, help="Maximum requests to show.")
    operator_requests_parser.add_argument("--status", choices=["pending", "approved", "rejected", "executed", "cancelled"], help="Filter by request status.")
    operator_requests_parser.add_argument("--full", action="store_true", help="Show thread/message and approval details.")
    operator_requests_parser.set_defaults(func=handlers['cmd_operator_requests'])

    operator_freedom_parser = operator_subparsers.add_parser("freedom", help="Evaluate whether Eve may execute an action under the current freedom policy.")
    operator_freedom_parser.add_argument("--action", required=True, help="Operational action name, for example service_health_check or open_slack_app.")
    operator_freedom_parser.add_argument("--source", default="manual", help="Where the action would originate, for example chat_local_app or autonomy_free_run:test.")
    operator_freedom_parser.add_argument("--mode", choices=sorted(settings['FREEDOM_POLICY_MODES']), help="Override the inferred policy mode.")
    operator_freedom_parser.add_argument("--prompt", default="", help="Optional current the user directive text to evaluate.")
    operator_freedom_parser.add_argument("--json", action="store_true", help="Print machine-readable policy JSON.")
    operator_freedom_parser.set_defaults(func=handlers['cmd_operator_freedom'])

    operator_approve_parser = operator_subparsers.add_parser("approve", help="Approve one gated action permission request.")
    operator_approve_parser.add_argument("id", help="Permission request id or unique prefix.")
    operator_approve_parser.add_argument("--approved-by", default="user", help="Who approved the request.")
    operator_approve_parser.add_argument("--note", default="", help="Approval note or narrowed boundary.")
    operator_approve_parser.set_defaults(func=handlers['cmd_operator_approve'])

    operator_reject_parser = operator_subparsers.add_parser("reject", help="Reject one gated action permission request.")
    operator_reject_parser.add_argument("id", help="Permission request id or unique prefix.")
    operator_reject_parser.add_argument("--note", default="", help="Rejection note.")
    operator_reject_parser.set_defaults(func=handlers['cmd_operator_reject'])

    autonomy_parser = subparsers.add_parser("autonomy", help="Inspect or change Eve's staged autonomy gates.")
    autonomy_subparsers = autonomy_parser.add_subparsers(dest="autonomy_command", required=True)

    autonomy_show_parser = autonomy_subparsers.add_parser("show", help="Show Eve's current autonomy stage and blockers.")
    autonomy_show_parser.set_defaults(func=handlers['cmd_autonomy_show'])

    autonomy_set_parser = autonomy_subparsers.add_parser("set", help="Move Eve to a different autonomy stage.")
    autonomy_set_parser.add_argument("stage", choices=settings['AUTONOMY_STAGES'], help="Target autonomy stage.")
    autonomy_set_parser.add_argument("--note", help="Optional note about why the stage changed.")
    autonomy_set_parser.add_argument("--force", action="store_true", help="Override current blockers deliberately.")
    autonomy_set_parser.set_defaults(func=handlers['cmd_autonomy_set'])

    autonomy_free_run_parser = autonomy_subparsers.add_parser(
        "free-run",
        help="Let Eve choose bounded actions for an observation window while logging every step.",
    )
    autonomy_free_run_parser.add_argument("--minutes", type=int, default=5, help="How long the free-run should last.")
    autonomy_free_run_parser.add_argument("--sample-seconds", type=int, default=20, help="How often to write monitor samples.")
    autonomy_free_run_parser.add_argument("--max-actions", type=int, help="Maximum Eve-chosen actions during the run. Defaults to a time-scaled action cap.")
    autonomy_free_run_parser.add_argument("--id", help="Optional run id. Defaults to a timestamped id.")
    autonomy_free_run_parser.add_argument(
        "--style",
        choices=settings['AUTONOMY_FREE_RUN_STYLES'],
        default=settings['DEFAULT_CONFIG']["autonomy_free_run_default_style"],
        help="Whether the run should bias toward grounded stabilization or open-ended exploration.",
    )
    autonomy_free_run_parser.set_defaults(func=handlers['cmd_autonomy_free_run'])

    autonomy_latest_parser = autonomy_subparsers.add_parser(
        "latest",
        help="Show the latest autonomy run summary.",
    )
    autonomy_latest_parser.add_argument("--runtime", action="store_true", help="Prefer runtime-bundle autonomy artifacts.")
    autonomy_latest_parser.add_argument("--full", action="store_true", help="Show fuller action and claim-audit detail.")
    autonomy_latest_parser.set_defaults(func=handlers['cmd_autonomy_latest'])

    autonomy_runs_parser = autonomy_subparsers.add_parser(
        "runs",
        help="List recent autonomy run summaries.",
    )
    autonomy_runs_parser.add_argument("--runtime", action="store_true", help="Prefer runtime-bundle autonomy artifacts.")
    autonomy_runs_parser.add_argument("--limit", type=int, default=5, help="How many recent runs to show.")
    autonomy_runs_parser.add_argument("--full", action="store_true", help="Show fuller detail for each run.")
    autonomy_runs_parser.set_defaults(func=handlers['cmd_autonomy_runs'])

    access_parser = subparsers.add_parser(
        "access",
        help="Report Eve's built-in local/project organ access and provenance boundaries.",
    )
    access_subparsers = access_parser.add_subparsers(dest="access_command", required=True)

    access_status_parser = access_subparsers.add_parser(
        "status",
        help="Build and save Eve's built-in access report.",
    )
    access_status_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime artifacts where available.")
    access_status_parser.add_argument("--full", action="store_true", help="Show every built-in layer and command path.")
    access_status_parser.add_argument("--json", action="store_true", help="Print the full report as JSON.")
    access_status_parser.add_argument("--no-save", action="store_true", help="Do not write .eve/built_in_access.json.")
    access_status_parser.add_argument("--no-probes", action="store_true", help="Skip bounded external CLI probes such as DVC/Beads/Dagster.")
    access_status_parser.set_defaults(func=handlers['cmd_access_status'])

    lab_live_parser = subparsers.add_parser(
        "lab-live",
        help="Report which lab/staged Eve substrates are actually live, canary-only, or still gated.",
    )
    lab_live_subparsers = lab_live_parser.add_subparsers(dest="lab_live_command", required=True)

    lab_live_status_parser = lab_live_subparsers.add_parser(
        "status",
        help="Build and save Eve's lab-live activation report.",
    )
    lab_live_status_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime artifacts where available.")
    lab_live_status_parser.add_argument("--full", action="store_true", help="Show every layer and next action.")
    lab_live_status_parser.add_argument("--json", action="store_true", help="Print the full report as JSON.")
    lab_live_status_parser.add_argument("--no-save", action="store_true", help="Do not write .eve/lab_live_activation.json.")
    lab_live_status_parser.add_argument("--no-probes", action="store_true", help="Skip bounded external CLI probes such as DVC/Beads/Dagster.")
    lab_live_status_parser.set_defaults(func=handlers['cmd_lab_live_status'])

    safety_parser = subparsers.add_parser("safety", help="Run rollback, restricted-mode, permission, and release-readiness drills.")
    safety_subparsers = safety_parser.add_subparsers(dest="safety_command", required=True)

    safety_drills_parser = safety_subparsers.add_parser(
        "drills",
        help="Audit rollback and restricted-mode paths before promoting risky changes.",
    )
    safety_drills_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime artifacts where available.")
    safety_drills_parser.add_argument("--full", action="store_true", help="Print every drill with rollback and restricted-mode paths.")
    safety_drills_parser.add_argument("--json", action="store_true", help="Print the full drill report as JSON.")
    safety_drills_parser.add_argument("--no-save", action="store_true", help="Do not write latest/history artifacts.")
    safety_drills_parser.set_defaults(func=handlers['cmd_safety_drills'])

    perf_parser = subparsers.add_parser("perf", help="Inspect Eve runtime performance signals and probe the local API.")
    perf_subparsers = perf_parser.add_subparsers(dest="perf_command", required=True)

    perf_summary_parser = perf_subparsers.add_parser("summary", help="Summarize recorded performance events.")
    perf_summary_parser.add_argument("--limit", type=int, default=300, help="Max events to inspect.")
    perf_summary_parser.add_argument("--minutes", type=int, default=240, help="Only inspect recent events from this time window.")
    perf_summary_parser.add_argument("--category", help="Filter by event category, such as `model_call` or `api_probe`.")
    perf_summary_parser.add_argument("--name", help="Filter by event name, such as `reflection` or `status`.")
    perf_summary_parser.add_argument("--failures", action="store_true", help="Show only failed events.")
    perf_summary_parser.add_argument("--failure-limit", type=int, default=5, help="How many recent failures to print.")
    perf_summary_parser.set_defaults(func=handlers['cmd_perf_summary'])

    perf_probe_parser = perf_subparsers.add_parser("probe", help="Actively measure the local Eve API endpoints.")
    perf_probe_parser.add_argument("--host", default="127.0.0.1", help="Host running the Eve API.")
    perf_probe_parser.add_argument("--port", type=int, default=8787, help="Port running the Eve API.")
    perf_probe_parser.add_argument("--repeat", type=int, default=3, help="How many probe passes to run.")
    perf_probe_parser.add_argument("--timeout", type=int, default=5, help="Per-request timeout in seconds.")
    perf_probe_parser.add_argument("--failure-limit", type=int, default=5, help="How many failures to print if probing fails.")
    perf_probe_parser.set_defaults(func=handlers['cmd_perf_probe'])

    infra_parser = subparsers.add_parser("infra", help="Inspect Eve's runtime substrate, tracing, metrics, and model governor.")
    infra_subparsers = infra_parser.add_subparsers(dest="infra_command", required=True)

    infra_status_parser = infra_subparsers.add_parser("status", help="Show SQLite, memory-note, trace, and governor status.")
    infra_status_parser.set_defaults(func=handlers['cmd_infra_status'])

    infra_metrics_parser = infra_subparsers.add_parser("metrics", help="Scrape llama.cpp /metrics endpoints into the operational store.")
    infra_metrics_parser.add_argument("--timeout", type=int, default=3, help="Per-lane metrics scrape timeout in seconds.")
    infra_metrics_parser.add_argument("--full", action="store_true", help="Print a sample of captured metric names and values.")
    infra_metrics_parser.set_defaults(func=handlers['cmd_infra_metrics'])

    infra_trace_export_parser = infra_subparsers.add_parser(
        "trace-export",
        help="Export local operational spans as OpenInference-shaped JSONL without requiring a collector.",
    )
    infra_trace_export_parser.add_argument("--limit", type=int, default=200, help="Maximum spans to export.")
    infra_trace_export_parser.add_argument("--trace-id", default="", help="Filter to one Eve trace id.")
    infra_trace_export_parser.add_argument("--category", default="", help="Filter by Eve span category.")
    infra_trace_export_parser.add_argument("--runtime", action="store_true", help="Prefer the live runtime operational database.")
    infra_trace_export_parser.add_argument("--output", default="", help="Output JSONL path. Defaults to .eve/trace_exports/latest_openinference.jsonl.")
    infra_trace_export_parser.add_argument("--no-save", action="store_true", help="Build the report without writing JSONL.")
    infra_trace_export_parser.add_argument("--full", action="store_true", help="Print provenance and privacy details.")
    infra_trace_export_parser.add_argument("--json", action="store_true", help="Print raw JSON report.")
    infra_trace_export_parser.set_defaults(func=handlers['cmd_infra_trace_export'])

    infra_otel_genai_parser = infra_subparsers.add_parser(
        "otel-genai",
        help="Export content-free OpenTelemetry GenAI metadata from Eve's canonical traces.",
    )
    infra_otel_genai_parser.add_argument("--db", default="", help="Explicit source SQLite path; opened read-only.")
    infra_otel_genai_parser.add_argument("--runtime", action="store_true", help="Prefer the live runtime operational database.")
    infra_otel_genai_parser.add_argument("--limit", type=int, default=200, help="Maximum recent spans to project.")
    infra_otel_genai_parser.add_argument("--output", default=str(eve_otel_genai.DEFAULT_OUTPUT), help="Content-free JSONL output path.")
    infra_otel_genai_parser.add_argument("--report", default=str(eve_otel_genai.DEFAULT_REPORT), help="Summary JSON output path.")
    infra_otel_genai_parser.add_argument("--no-save", action="store_true", help="Build the report without writing outputs.")
    infra_otel_genai_parser.add_argument("--json", action="store_true", help="Print raw JSON report.")
    infra_otel_genai_parser.set_defaults(func=handlers['cmd_infra_otel_genai'])

    infra_mcp_2026_parser = infra_subparsers.add_parser(
        "mcp-2026",
        help="Audit Eve's installed MCP 2026 compatibility without changing servers or calling tools.",
    )
    infra_mcp_2026_parser.add_argument("--no-live", action="store_true", help="Skip the bounded QMD discovery probe.")
    infra_mcp_2026_parser.add_argument("--config", default="", help="Optional MCPorter config path.")
    infra_mcp_2026_parser.add_argument("--output", default="", help="Optional JSON evidence path.")
    infra_mcp_2026_parser.add_argument("--no-write", action="store_true", help="Do not persist evidence.")
    infra_mcp_2026_parser.add_argument("--json", action="store_true", help="Print full bounded evidence.")
    infra_mcp_2026_parser.set_defaults(func=handlers['cmd_infra_mcp_2026'])

    infra_events_parser = infra_subparsers.add_parser("events", help="List canonical typed events from the operational event spine.")
    infra_events_parser.add_argument("--limit", type=int, default=25, help="Maximum events to show.")
    infra_events_parser.add_argument("--stream", default="", help="Filter by event stream.")
    infra_events_parser.add_argument("--kind", default="", help="Filter by event kind.")
    infra_events_parser.add_argument("--correlation-id", default="", help="Filter by correlation id.")
    infra_events_parser.add_argument("--json", action="store_true", help="Print raw JSON records.")
    infra_events_parser.set_defaults(func=handlers['cmd_infra_events'])

    infra_event_contract_parser = infra_subparsers.add_parser("event-contract", help="Print the typed event contract for other runtimes.")
    infra_event_contract_parser.set_defaults(func=handlers['cmd_infra_event_contract'])

    infra_nervous_parser = infra_subparsers.add_parser(
        "nervous",
        help="Run the experimental Go nervous-system worker against the typed event spine.",
    )
    infra_nervous_parser.add_argument(
        "nervous_action",
        choices=["heartbeat", "enqueue", "once", "run", "result", "sense"],
        help="Worker action to run.",
    )
    infra_nervous_parser.add_argument("--runtime", action="store_true", help="Use the live runtime operational database.")
    infra_nervous_parser.add_argument("--timeout", type=int, default=30, help="Worker timeout in seconds.")
    infra_nervous_parser.add_argument("--json", action="store_true", help="Print worker JSON output.")
    infra_nervous_parser.add_argument("--tool", default="echo", help="Tool name for enqueue.")
    infra_nervous_parser.add_argument("--message", default="", help="Message for enqueue/result.")
    infra_nervous_parser.add_argument("--duration", type=int, default=30, help="Run-loop duration in seconds.")
    infra_nervous_parser.add_argument("--interval", type=int, default=1, help="Delay after a processed job, in seconds.")
    infra_nervous_parser.add_argument("--idle-backoff", type=int, default=2, help="Delay when no job is available, in seconds.")
    infra_nervous_parser.add_argument("--heartbeat-interval", type=int, default=15, help="Run-loop heartbeat cadence in seconds.")
    infra_nervous_parser.add_argument("--max-jobs", type=int, default=10, help="Maximum jobs to process during a run. Use 0 for duration-only.")
    infra_nervous_parser.add_argument("--subject", default="manual", help="Subject for result.")
    infra_nervous_parser.add_argument("--status", default="completed", help="Status for result.")
    infra_nervous_parser.add_argument("--modality", choices=["auditory", "visual", "proprioceptive"], help="Typed sensory modality for sense.")
    infra_nervous_parser.add_argument("--session", default="", help="Active explicit sensory-session id for sense.")
    infra_nervous_parser.add_argument("--session-token-env", default="EVE_SENSORY_SESSION_TOKEN", help="Environment variable containing the session token; the token is never accepted on argv.")
    infra_nervous_parser.add_argument("--session-token-file", default="", help="Optional mode-0600 file containing the session token.")
    infra_nervous_parser.add_argument("--permission", action="store_true", help="Assert current OS/device permission for auditory or visual input.")
    infra_nervous_parser.add_argument("--sensor-source", default="go_private_device_adapter", help="Low-entropy admitted sensor-source identifier.")
    infra_nervous_parser.add_argument("--features-json", default="{}", help="Fixed-schema feature JSON only; raw media/text is rejected by the worker.")
    infra_nervous_parser.add_argument("--intensity", type=float, default=35.0)
    infra_nervous_parser.add_argument("--novelty", type=float, default=50.0)
    infra_nervous_parser.add_argument("--change", type=float, default=0.0)
    infra_nervous_parser.add_argument("--urgency", type=float, default=20.0)
    infra_nervous_parser.add_argument("--goal-relevance", type=float, default=35.0)
    infra_nervous_parser.add_argument("--self-relevance", type=float, default=35.0)
    infra_nervous_parser.add_argument("--social-relevance", type=float, default=0.0)
    infra_nervous_parser.add_argument("--precision", type=float, default=70.0)
    infra_nervous_parser.set_defaults(func=handlers['cmd_infra_nervous'])

    oss_parser = subparsers.add_parser(
        "oss",
        help="Inspect and run Eve's governed OSS trace/eval/dataset/trainer improvement substrate.",
    )
    oss_subparsers = oss_parser.add_subparsers(dest="oss_command", required=True)

    oss_status_parser = oss_subparsers.add_parser("status", help="Show Eve's OSS improvement substrate status.")
    oss_status_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime artifacts where available.")
    oss_status_parser.add_argument("--service-preflight", action="store_true", help="Run a bounded service preflight instead of reading the latest lab report.")
    oss_status_parser.add_argument("--verify-trainer-envs", action="store_true", help="Verify isolated trainer lab CLIs/imports; can take longer.")
    oss_status_parser.add_argument("--no-save", action="store_true", help="Do not write .eve/oss_integration/latest.json.")
    oss_status_parser.add_argument("--full", action="store_true", help="Print readiness check detail.")
    oss_status_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    oss_status_parser.set_defaults(func=handlers['cmd_oss_status'])

    oss_copilotkit_parser = oss_subparsers.add_parser(
        "copilotkit",
        help="Inspect or refresh CopilotKit as Eve's UI/AG-UI exposure candidate.",
    )
    oss_copilotkit_parser.add_argument("--refresh", action="store_true", help="Refresh the CopilotKit probe instead of reading the latest artifact.")
    oss_copilotkit_parser.add_argument("--mirror", action="store_true", help="Refresh the local ignored upstream mirror during --refresh.")
    oss_copilotkit_parser.add_argument("--install-npm-lab", action="store_true", help="Install CopilotKit packages in Eve's isolated npm lab during --refresh.")
    oss_copilotkit_parser.add_argument("--import-probe", action="store_true", help="Run the Node import/adapter construction probe during --refresh.")
    oss_copilotkit_parser.add_argument("--probe-eve-backend", action="store_true", help="Send one compatibility request through Eve's local /v1 chat backend during --refresh.")
    oss_copilotkit_parser.add_argument("--eve-base-url", default="", help="Override Eve's local OpenAI-compatible base URL.")
    oss_copilotkit_parser.add_argument("--npm-timeout", type=int, default=240, help="Timeout for isolated npm install.")
    oss_copilotkit_parser.add_argument("--mirror-timeout", type=int, default=300, help="Timeout for mirror fetch/clone.")
    oss_copilotkit_parser.add_argument("--eve-timeout", type=int, default=45, help="Timeout for Eve backend probe.")
    oss_copilotkit_parser.add_argument("--no-save", action="store_true", help="Do not write CopilotKit latest/exposure artifacts.")
    oss_copilotkit_parser.add_argument("--full", action="store_true", help="Print every exposure surface.")
    oss_copilotkit_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    oss_copilotkit_parser.set_defaults(func=handlers['cmd_oss_copilotkit'])

    oss_cycle_parser = oss_subparsers.add_parser(
        "cycle",
        help="Run one bounded OSS integration cycle: trace, dataset, manifest, recipes, workflow, and public eval.",
    )
    oss_cycle_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime state when reading source evidence.")
    oss_cycle_parser.add_argument("--trace-limit", type=int, default=200, help="Maximum operational spans to export.")
    oss_cycle_parser.add_argument("--dataset-source", choices=sorted(settings['TRAINING_DATASET_SOURCES']), default="verified-failures", help="Training dataset source policy.")
    oss_cycle_parser.add_argument("--dataset-limit", type=int, default=400, help="Maximum curated training examples.")
    oss_cycle_parser.add_argument("--no-build-dataset", action="store_true", help="Use the latest dataset instead of rebuilding it.")
    oss_cycle_parser.add_argument("--no-write-trainer-recipes", action="store_true", help="Do not refresh no-training trainer recipes.")
    oss_cycle_parser.add_argument("--verify-trainer-envs", action="store_true", help="Verify isolated trainer lab environments.")
    oss_cycle_parser.add_argument("--service-preflight", action="store_true", help="Also run a bounded Phoenix/Langfuse service preflight.")
    oss_cycle_parser.add_argument("--no-pressure-eval", action="store_true", help="Skip the public conversation pressure eval during this cycle.")
    oss_cycle_parser.add_argument("--pressure-live-chat", action="store_true", help="Run pressure cases through journaling live chat instead of private-audit chat.")
    oss_cycle_parser.add_argument("--pressure-limit", type=int, default=4, help="Maximum public pressure cases to run.")
    oss_cycle_parser.add_argument("--pressure-timeout", type=int, default=60, help="Timeout per pressure chat case in seconds.")
    oss_cycle_parser.add_argument("--no-trainer-dry-run", action="store_true", help="Skip the no-download, no-training MLX forward validation during this cycle.")
    oss_cycle_parser.add_argument("--trainer-base-model", default="", help="Local MLX model path; otherwise use a small already-cached model without downloading.")
    oss_cycle_parser.add_argument("--no-save", action="store_true", help="Do not write cycle artifacts or event-ledger evidence.")
    oss_cycle_parser.add_argument("--full", action="store_true", help="Print artifact and boundary detail.")
    oss_cycle_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    oss_cycle_parser.set_defaults(func=handlers['cmd_oss_cycle'])

    oss_eval_parser = oss_subparsers.add_parser("eval", help="Run Eve's public OSS improvement eval gate.")
    oss_eval_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime artifacts where available.")
    oss_eval_parser.add_argument("--run-pressure-eval", action="store_true", help="Run the public conversation pressure eval before scoring.")
    oss_eval_parser.add_argument("--pressure-live-chat", action="store_true", help="Run pressure cases through journaling live chat instead of private-audit chat.")
    oss_eval_parser.add_argument("--pressure-limit", type=int, default=4, help="Maximum public pressure cases to run.")
    oss_eval_parser.add_argument("--pressure-timeout", type=int, default=60, help="Timeout per pressure chat case in seconds.")
    oss_eval_parser.add_argument("--run-trainer-dry-run", action="store_true", help="Run the no-download, no-training MLX forward validation before scoring.")
    oss_eval_parser.add_argument("--trainer-base-model", default="", help="Local MLX model path; otherwise use a small already-cached model without downloading.")
    oss_eval_parser.add_argument("--no-save", action="store_true", help="Do not write eval artifacts or event-ledger evidence.")
    oss_eval_parser.add_argument("--full", action="store_true", help="Print each public check.")
    oss_eval_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    oss_eval_parser.set_defaults(func=handlers['cmd_oss_eval'])

    oss_pressure_parser = oss_subparsers.add_parser(
        "pressure-eval",
        help="Run public conversation pressure cases through Eve's chat surface and score them.",
    )
    oss_pressure_parser.add_argument("--runtime", action="store_true", help="Reserved for future runtime-bundle chat execution.")
    oss_pressure_parser.add_argument("--live-chat", action="store_true", help="Use journaling live chat instead of private-audit chat.")
    oss_pressure_parser.add_argument("--limit", type=int, default=4, help="Maximum public pressure cases to run.")
    oss_pressure_parser.add_argument("--timeout", type=int, default=60, help="Timeout per pressure chat case in seconds.")
    oss_pressure_parser.add_argument("--max-tokens", type=int, default=220, help="Maximum generated tokens per pressure case.")
    oss_pressure_parser.add_argument("--no-save", action="store_true", help="Do not write pressure eval artifacts or event-ledger evidence.")
    oss_pressure_parser.add_argument("--full", action="store_true", help="Print per-case details.")
    oss_pressure_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    oss_pressure_parser.set_defaults(func=handlers['cmd_oss_pressure_eval'])

    oss_trainer_dry_run_parser = oss_subparsers.add_parser(
        "trainer-dry-run",
        help="Run a real no-download, no-training MLX forward validation against public validation rows.",
    )
    oss_trainer_dry_run_parser.add_argument("--runtime", action="store_true", help="Prefer runtime-mirrored recipes where available.")
    oss_trainer_dry_run_parser.add_argument("--trainer", default="mlx_lm", help="Trainer id. Currently mlx_lm is the implemented gate.")
    oss_trainer_dry_run_parser.add_argument("--base-model", default="", help="Local MLX model path. When omitted, Eve selects a small already-cached model; no downloads are attempted.")
    oss_trainer_dry_run_parser.add_argument("--timeout", type=int, default=180, help="No-training MLX validation timeout in seconds.")
    oss_trainer_dry_run_parser.add_argument("--no-save", action="store_true", help="Do not write trainer dry-run artifacts or event-ledger evidence.")
    oss_trainer_dry_run_parser.add_argument("--full", action="store_true", help="Print trainer env and CLI details.")
    oss_trainer_dry_run_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    oss_trainer_dry_run_parser.set_defaults(func=handlers['cmd_oss_trainer_dry_run'])

    oss_dvc_parser = oss_subparsers.add_parser(
        "dvc-snapshot",
        help="Create or inspect a local DVC snapshot and verify a clean cache-backed restore.",
    )
    oss_dvc_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime artifacts where available.")
    oss_dvc_parser.add_argument("--write", action="store_true", help="Refresh the local payload, DVC sidecar/cache, clean-restore proof, and Eve evidence artifact.")
    oss_dvc_parser.add_argument("--full", action="store_true", help="Print file-level hashes/counts.")
    oss_dvc_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    oss_dvc_parser.set_defaults(func=handlers['cmd_oss_dvc_snapshot'])

    governance_parser = subparsers.add_parser(
        "governance",
        help="Inspect Eve's organ-system event/proposal envelopes and CIK review gates.",
    )
    governance_subparsers = governance_parser.add_subparsers(dest="governance_command", required=True)

    governance_contract_parser = governance_subparsers.add_parser(
        "contract",
        help="Print the event/proposal governance contract.",
    )
    governance_contract_parser.set_defaults(func=handlers['cmd_governance_contract'])

    governance_events_parser = governance_subparsers.add_parser(
        "events",
        help="Normalize recent existing ledgers into EveEvent envelopes without migrating them.",
    )
    governance_events_parser.add_argument("--limit", type=int, default=40, help="Maximum normalized events to show.")
    governance_events_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime ledgers when available.")
    governance_events_parser.add_argument("--full", action="store_true", help="Include compact payload detail.")
    governance_events_parser.add_argument("--json", action="store_true", help="Print raw JSON envelopes.")
    governance_events_parser.set_defaults(func=handlers['cmd_governance_events'])

    governance_event_ledger_parser = governance_subparsers.add_parser(
        "event-ledger",
        help="Inspect or rebuild Eve's canonical event ledger at .eve/event_ledger.jsonl.",
    )
    governance_event_ledger_parser.add_argument("--limit", type=int, default=40, help="Maximum events to inspect or rebuild from.")
    governance_event_ledger_parser.add_argument("--runtime", action="store_true", help="Prefer the live runtime ledger when reading.")
    governance_event_ledger_parser.add_argument("--status", action="store_true", help="Show ledger counts instead of event rows.")
    governance_event_ledger_parser.add_argument("--rebuild", action="store_true", help="Rebuild the canonical ledger from normalized existing ledgers.")
    governance_event_ledger_parser.add_argument("--dry-run", action="store_true", help="Preview rebuild without writing.")
    governance_event_ledger_parser.add_argument("--full", action="store_true", help="Include compact payload detail.")
    governance_event_ledger_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    governance_event_ledger_parser.set_defaults(func=handlers['cmd_governance_event_ledger'])

    governance_daily_review_parser = governance_subparsers.add_parser(
        "daily-review",
        help="Record a daily governance review over event ledger, proposals, and watcher state.",
    )
    governance_daily_review_parser.add_argument("--limit", type=int, default=80, help="Maximum proposals/events to inspect.")
    governance_daily_review_parser.add_argument("--no-save", action="store_true", help="Print the review without writing an artifact or event.")
    governance_daily_review_parser.add_argument("--full", action="store_true", help="Include watcher and lifecycle detail.")
    governance_daily_review_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    governance_daily_review_parser.set_defaults(func=handlers['cmd_governance_daily_review'])

    governance_skill_audit_parser = governance_subparsers.add_parser(
        "skill-audit",
        help="Audit SkillPatchProposal records without enabling any skill.",
    )
    governance_skill_audit_parser.add_argument("--limit", type=int, default=120, help="Maximum skill proposals to inspect.")
    governance_skill_audit_parser.add_argument("--no-save", action="store_true", help="Print the audit without writing an artifact or event.")
    governance_skill_audit_parser.add_argument("--full", action="store_true", help="Include finding detail.")
    governance_skill_audit_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    governance_skill_audit_parser.set_defaults(func=handlers['cmd_governance_skill_audit'])

    governance_queue_parser = governance_subparsers.add_parser(
        "queue",
        help="List reviewed governance proposals without applying them.",
    )
    governance_queue_parser.add_argument("--limit", type=int, default=40, help="Maximum proposals to show.")
    governance_queue_parser.add_argument("--decision", default="", help="Filter by review decision, such as reject or test_first.")
    governance_queue_parser.add_argument("--proposal-type", default="", help="Filter by proposal type.")
    governance_queue_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime queue when available.")
    governance_queue_parser.add_argument("--full", action="store_true", help="Include payload and findings.")
    governance_queue_parser.add_argument("--json", action="store_true", help="Print raw JSON queue records.")
    governance_queue_parser.set_defaults(func=handlers['cmd_governance_queue'])

    governance_watchers_parser = governance_subparsers.add_parser(
        "watchers",
        help="Generate watcher reports over governance proposals and recent untrusted observations.",
    )
    governance_watchers_parser.add_argument("--limit", type=int, default=40, help="Maximum proposals/events to inspect.")
    governance_watchers_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime queue/ledgers when available.")
    governance_watchers_parser.add_argument("--no-events", action="store_true", help="Only inspect queued proposals.")
    governance_watchers_parser.add_argument("--full", action="store_true", help="Include watcher warning detail.")
    governance_watchers_parser.add_argument("--json", action="store_true", help="Print raw JSON watcher report.")
    governance_watchers_parser.set_defaults(func=handlers['cmd_governance_watchers'])

    governance_ingest_hermes_parser = governance_subparsers.add_parser(
        "ingest-hermes",
        help="Ingest strict Hermes-style learning proposals into the governance queue without applying them.",
    )
    governance_ingest_hermes_parser.add_argument("--source", default="hermes", help="Proposal source label.")
    governance_ingest_hermes_parser.add_argument("--file", default="", help="JSON file to read, or '-' for stdin.")
    governance_ingest_hermes_parser.add_argument("--payload-json", default="", help="JSON object/list containing strict proposals.")
    governance_ingest_hermes_parser.add_argument("--dry-run", action="store_true", help="Review without storing proposals.")
    governance_ingest_hermes_parser.add_argument("--full", action="store_true", help="Include payload and findings.")
    governance_ingest_hermes_parser.add_argument("--json", action="store_true", help="Print raw JSON ingest result.")
    governance_ingest_hermes_parser.set_defaults(func=handlers['cmd_governance_ingest_hermes'])

    governance_ingest_codex_parser = governance_subparsers.add_parser(
        "ingest-codex",
        help="Ingest strict Codex code-patch proposals into the governance queue without applying them.",
    )
    governance_ingest_codex_parser.add_argument("--source", default="codex", help="Proposal source label.")
    governance_ingest_codex_parser.add_argument("--file", default="", help="JSON file to read, or '-' for stdin.")
    governance_ingest_codex_parser.add_argument("--payload-json", default="", help="JSON object/list containing strict CodePatchProposal records.")
    governance_ingest_codex_parser.add_argument("--dry-run", action="store_true", help="Review without storing proposals.")
    governance_ingest_codex_parser.add_argument("--full", action="store_true", help="Include payload and findings.")
    governance_ingest_codex_parser.add_argument("--json", action="store_true", help="Print raw JSON ingest result.")
    governance_ingest_codex_parser.set_defaults(func=handlers['cmd_governance_ingest_codex'])

    def add_governance_proposal_args(target_parser: argparse.ArgumentParser) -> None:
        target_parser.add_argument(
            "--proposal-type",
            required=True,
            choices=sorted(eve_governance.PROPOSAL_TYPES),
            help="Typed proposal class to review or queue.",
        )
        target_parser.add_argument("--source", required=True, help="Organ or channel proposing the change.")
        target_parser.add_argument(
            "--cik-zone",
            default="",
            choices=["", *sorted(eve_governance.CIK_ZONES)],
            help="Protected target zone. Defaults from proposal type.",
        )
        target_parser.add_argument(
            "--source-cik-zone",
            default="",
            choices=["", *sorted(eve_governance.CIK_ZONES)],
            help="Protected source zone. Defaults from source name.",
        )
        target_parser.add_argument("--risk-level", type=int, help="Risk level from 0 to 5.")
        target_parser.add_argument(
            "--requires-approval",
            action="store_true",
            default=None,
            help="Mark this proposal as requiring explicit approval.",
        )
        target_parser.add_argument("--evidence", action="append", default=[], help="Evidence/event reference. Repeatable.")
        target_parser.add_argument("--permission", action="append", default=[], help="Permission used or requested. Repeatable.")
        target_parser.add_argument("--claim", default="", help="Human-readable claim or memory patch text.")
        target_parser.add_argument("--tests", action="append", default=[], help="Required or proposed test id. Repeatable.")
        target_parser.add_argument("--rollback-plan", default="", help="Rollback plan for code/capability proposals.")
        target_parser.add_argument("--payload-json", default="", help="Additional proposal payload JSON object.")

    governance_review_parser = governance_subparsers.add_parser(
        "review",
        help="Review a typed proposal without writing it.",
    )
    add_governance_proposal_args(governance_review_parser)
    governance_review_parser.add_argument("--json", action="store_true", help="Print raw JSON review.")
    governance_review_parser.set_defaults(func=handlers['cmd_governance_review'])

    governance_enqueue_parser = governance_subparsers.add_parser(
        "enqueue",
        help="Append a reviewed proposal to the governance proposal queue without accepting it.",
    )
    add_governance_proposal_args(governance_enqueue_parser)
    governance_enqueue_parser.add_argument("--json", action="store_true", help="Print raw JSON queue record.")
    governance_enqueue_parser.set_defaults(func=handlers['cmd_governance_enqueue'])

    governance_approve_parser = governance_subparsers.add_parser(
        "approve",
        help="Record explicit approval for a governance proposal without applying it.",
    )
    governance_approve_parser.add_argument("proposal_id", help="Queued governance proposal id.")
    governance_approve_parser.add_argument("--approved-by", default="user", help="Who approved the proposal.")
    governance_approve_parser.add_argument("--reason", default="", help="Short approval reason or boundary.")
    governance_approve_parser.add_argument("--dry-run", action="store_true", help="Check approval gates without writing.")
    governance_approve_parser.add_argument("--full", action="store_true", help="Include proposal detail.")
    governance_approve_parser.add_argument("--json", action="store_true", help="Print raw JSON approval result.")
    governance_approve_parser.set_defaults(func=handlers['cmd_governance_approve'])

    governance_reject_parser = governance_subparsers.add_parser(
        "reject",
        help="Record explicit rejection for a governance proposal.",
    )
    governance_reject_parser.add_argument("proposal_id", help="Queued governance proposal id.")
    governance_reject_parser.add_argument("--rejected-by", default="user", help="Who rejected the proposal.")
    governance_reject_parser.add_argument("--reason", default="", help="Short rejection reason.")
    governance_reject_parser.add_argument("--dry-run", action="store_true", help="Check rejection gates without writing.")
    governance_reject_parser.add_argument("--full", action="store_true", help="Include proposal detail.")
    governance_reject_parser.add_argument("--json", action="store_true", help="Print raw JSON rejection result.")
    governance_reject_parser.set_defaults(func=handlers['cmd_governance_reject'])

    governance_canary_parser = governance_subparsers.add_parser(
        "canary",
        help="Record canary lifecycle status for a governance proposal without applying it.",
    )
    governance_canary_parser.add_argument("proposal_id", help="Queued governance proposal id.")
    governance_canary_parser.add_argument("--status", required=True, choices=sorted(settings['GOVERNANCE_CANARY_STATUSES']), help="Canary lifecycle status.")
    governance_canary_parser.add_argument("--updated-by", default="codex", help="Who recorded the canary status.")
    governance_canary_parser.add_argument("--summary", default="", help="Short canary result or boundary.")
    governance_canary_parser.add_argument("--evidence", action="append", default=[], help="Canary evidence reference. Repeatable.")
    governance_canary_parser.add_argument("--dry-run", action="store_true", help="Check canary gates without writing.")
    governance_canary_parser.add_argument("--full", action="store_true", help="Include proposal detail.")
    governance_canary_parser.add_argument("--json", action="store_true", help="Print raw JSON canary result.")
    governance_canary_parser.set_defaults(func=handlers['cmd_governance_canary'])

    governance_code_lifecycle_parser = governance_subparsers.add_parser(
        "code-lifecycle",
        help="Inspect a CodePatchProposal approval/canary/rollback readiness plan without deploying code.",
    )
    governance_code_lifecycle_parser.add_argument("proposal_id", nargs="?", help="Queued CodePatchProposal id.")
    governance_code_lifecycle_parser.add_argument("--source", default="codex", help="Proposal source label for payload mode.")
    governance_code_lifecycle_parser.add_argument("--file", default="", help="JSON file to read in payload mode, or '-' for stdin.")
    governance_code_lifecycle_parser.add_argument("--payload-json", default="", help="One strict CodePatchProposal record or code_patches collection.")
    governance_code_lifecycle_parser.add_argument("--full", action="store_true", help="Include watcher and proposal detail.")
    governance_code_lifecycle_parser.add_argument("--json", action="store_true", help="Print raw JSON lifecycle plan.")
    governance_code_lifecycle_parser.set_defaults(func=handlers['cmd_governance_code_lifecycle'])

    governance_apply_parser = governance_subparsers.add_parser(
        "apply",
        help="Apply an accepted knowledge-only governance proposal to Eve evidence, if every gate passes.",
    )
    governance_apply_parser.add_argument("proposal_id", help="Queued governance proposal id.")
    governance_apply_parser.add_argument("--dry-run", action="store_true", help="Check apply gates without writing evidence or events.")
    governance_apply_parser.add_argument("--full", action="store_true", help="Include watcher detail.")
    governance_apply_parser.add_argument("--json", action="store_true", help="Print raw JSON apply result.")
    governance_apply_parser.set_defaults(func=handlers['cmd_governance_apply'])

    governance_rollback_parser = governance_subparsers.add_parser(
        "rollback",
        help="Retract the evidence written by an applied knowledge-only governance proposal.",
    )
    governance_rollback_parser.add_argument("proposal_id", help="Applied governance proposal id.")
    governance_rollback_parser.add_argument("--reason", default="", help="Short rollback reason.")
    governance_rollback_parser.add_argument("--dry-run", action="store_true", help="Check rollback gates without changing records.")
    governance_rollback_parser.add_argument("--full", action="store_true", help="Include proposal detail.")
    governance_rollback_parser.add_argument("--json", action="store_true", help="Print raw JSON rollback result.")
    governance_rollback_parser.set_defaults(func=handlers['cmd_governance_rollback'])

    governance_untrusted_parser = governance_subparsers.add_parser(
        "untrusted-observation",
        help="Render an OpenClaw inbound message as an untrusted observation envelope.",
    )
    governance_untrusted_parser.add_argument("--channel", required=True, help="Inbound OpenClaw channel, such as imessage.")
    governance_untrusted_parser.add_argument("--sender", default="", help="External sender id; only a hash is kept.")
    governance_untrusted_parser.add_argument("--text", default="", help="Inbound text excerpt to hash and mark untrusted.")
    governance_untrusted_parser.add_argument("--payload-json", default="", help="Additional observation payload JSON object.")
    governance_untrusted_parser.add_argument("--record", action="store_true", help="Persist the observation in the governance event ledger.")
    governance_untrusted_parser.add_argument("--json", action="store_true", help="Print raw JSON event.")
    governance_untrusted_parser.set_defaults(func=handlers['cmd_governance_untrusted_observation'])

    updates_parser = subparsers.add_parser("updates", help="Check internet update signals and manage local upstream mirrors.")
    updates_subparsers = updates_parser.add_subparsers(dest="updates_command", required=True)

    updates_check_parser = updates_subparsers.add_parser("check", help="Check watched components for upstream updates without installing them.")
    updates_check_parser.add_argument("--mirror", action="store_true", help="Also clone or fetch local upstream mirrors after checking.")
    updates_check_parser.add_argument("--timeout", type=int, help="Per-component network timeout in seconds.")
    updates_check_parser.add_argument("--full", action="store_true", help="Print full component details.")
    updates_check_parser.set_defaults(func=handlers['cmd_updates_check'])

    updates_status_parser = updates_subparsers.add_parser("status", help="Show the last component update check.")
    updates_status_parser.add_argument("--runtime", action="store_true", help="Prefer the runtime bundle's update state.")
    updates_status_parser.add_argument("--only-updates", action="store_true", help="Only show components with update signals.")
    updates_status_parser.add_argument("--full", action="store_true", help="Print full component details.")
    updates_status_parser.set_defaults(func=handlers['cmd_updates_status'])

    updates_mirror_parser = updates_subparsers.add_parser("mirror", help="Clone or fetch a local bare mirror of an upstream component.")
    updates_mirror_parser.add_argument("--component", default="openclaw", help="Component id to mirror, such as `openclaw` or `llama-cpp`.")
    updates_mirror_parser.add_argument("--all", action="store_true", help="Mirror every watched component with a repository.")
    updates_mirror_parser.add_argument("--timeout", type=int, default=900, help="Mirror operation timeout in seconds.")
    updates_mirror_parser.set_defaults(func=handlers['cmd_updates_mirror'])

    updates_git_init_parser = updates_subparsers.add_parser("git-init", help="Initialize a local Git rollback repo for Eve.")
    updates_git_init_parser.add_argument("--commit", action="store_true", help="Create an initial rollback commit after staging non-ignored files.")
    updates_git_init_parser.set_defaults(func=handlers['cmd_updates_git_init'])

    doctor_parser = subparsers.add_parser("doctor", help="Inspect Eve's local runtime, model lanes, and substrate health.")
    doctor_parser.add_argument("--json", action="store_true", help="Print a compact machine-readable runtime source truth check.")
    doctor_parser.add_argument("--quick", action="store_true", help="Only check code parity and state-authority mirrors; skip deeper probes.")
    doctor_parser.set_defaults(func=handlers['cmd_doctor'])

    runtime_parser = subparsers.add_parser("runtime", help="Inspect and sync Eve's runtime bundle.")
    runtime_subparsers = runtime_parser.add_subparsers(dest="runtime_command", required=True)
    runtime_sync_parser = runtime_subparsers.add_parser("sync", help="Copy current source into the live runtime bundle.")
    runtime_sync_parser.add_argument("--code-only", action="store_true", help="Validate/install Python only; no data copy or automatic service reload. Quiesce code consumers before installing.")
    runtime_sync_parser.add_argument("--check-only", action="store_true", help="With --code-only, compile and isolated-import the candidate without installing.")
    runtime_sync_parser.set_defaults(func=handlers['cmd_runtime_sync'])
    runtime_truth_parser = runtime_subparsers.add_parser("truth", help="Compare source-tree code with the live runtime bundle.")
    runtime_truth_parser.add_argument("--json", action="store_true", help="Print JSON.")
    runtime_truth_parser.set_defaults(func=handlers['cmd_runtime_truth'])
    runtime_reconcile_parser = runtime_subparsers.add_parser(
        "reconcile",
        help="Reconcile source/runtime state mirrors according to the state-authority contract.",
    )
    runtime_reconcile_parser.add_argument("--store", action="append", help="Limit to a state store id, such as state or human_context.")
    runtime_reconcile_parser.add_argument("--dry-run", action="store_true", help="Show planned copies without writing. This is the default.")
    runtime_reconcile_parser.add_argument("--apply", action="store_true", help="Copy the authoritative side to its mirror.")
    runtime_reconcile_parser.add_argument("--json", action="store_true", help="Print JSON.")
    runtime_reconcile_parser.set_defaults(func=handlers['cmd_runtime_reconcile'])
    runtime_backfill_manual_reply_replays_parser = runtime_subparsers.add_parser(
        "backfill-manual-reply-replays",
        help="Create reply-turn replay evidence for manual visible replies that lack it.",
    )
    runtime_backfill_manual_reply_replays_parser.add_argument("--limit", type=int, default=200, help="Maximum recent messages to inspect.")
    runtime_backfill_manual_reply_replays_parser.add_argument("--runtime", action="store_true", help="Prefer the live runtime message ledger.")
    runtime_backfill_manual_reply_replays_parser.add_argument("--apply", action="store_true", help="Write missing replay records. Without this, only reports gaps.")
    runtime_backfill_manual_reply_replays_parser.add_argument("--json", action="store_true", help="Print JSON.")
    runtime_backfill_manual_reply_replays_parser.set_defaults(func=handlers['cmd_runtime_backfill_manual_reply_replays'])
    runtime_test_leaks_parser = runtime_subparsers.add_parser(
        "test-leaks",
        help="Fail if live Eve state contains test-only metadata records.",
    )
    runtime_test_leaks_parser.add_argument("--limit", type=int, default=20, help="Maximum example leaks to print.")
    runtime_test_leaks_parser.add_argument(
        "--quarantine",
        action="store_true",
        help="Rewrite exact test-only source markers as historical quarantined metadata.",
    )
    runtime_test_leaks_parser.add_argument("--json", action="store_true", help="Print JSON.")
    runtime_test_leaks_parser.set_defaults(func=handlers['cmd_runtime_test_leaks'])

    substrate_parser = subparsers.add_parser(
        "substrate",
        help="Inspect Eve's evidence, commitment, and lived-experience substrate.",
    )
    substrate_subparsers = substrate_parser.add_subparsers(dest="substrate_command", required=True)
    substrate_show_parser = substrate_subparsers.add_parser("show", help="Show recent substrate records.")
    substrate_show_parser.add_argument("--limit", type=int, default=8, help="Max records per substrate stream.")
    substrate_show_parser.add_argument("--runtime", action="store_true", help="Prefer the live runtime bundle's substrate logs.")
    substrate_show_parser.add_argument("--active", action="store_true", help="Only show fresh active evidence records.")
    substrate_show_parser.add_argument("--full", action="store_true", help="Print full record details.")
    substrate_show_parser.set_defaults(func=handlers['cmd_substrate_show'])

    substrate_candidates_parser = substrate_subparsers.add_parser(
        "supersession-candidates",
        help="Find fresh evidence records that should likely be superseded by a newer claim.",
    )
    substrate_candidates_parser.add_argument("--claim", required=True, help="Newer claim to compare against active evidence.")
    substrate_candidates_parser.add_argument("--kind", default="", help="Optional evidence kind filter.")
    substrate_candidates_parser.add_argument("--source", default="", help="Optional source filter.")
    substrate_candidates_parser.add_argument("--limit", type=int, default=8, help="Max candidates to show.")
    substrate_candidates_parser.add_argument("--runtime", action="store_true", help="Prefer the runtime bundle's evidence ledger.")
    substrate_candidates_parser.add_argument("--full", action="store_true", help="Print overlap details.")
    substrate_candidates_parser.add_argument("--json", action="store_true", help="Print JSON.")
    substrate_candidates_parser.set_defaults(func=handlers['cmd_substrate_evidence_candidates'])

    substrate_corrections_parser = substrate_subparsers.add_parser("corrections", help="List user correction signals Eve has learned from.")
    substrate_corrections_parser.add_argument("--limit", type=int, default=10, help="Max correction records.")
    substrate_corrections_parser.add_argument("--status", default="", help="Filter by status.")
    substrate_corrections_parser.add_argument("--runtime", action="store_true", help="Prefer the runtime bundle's correction log.")
    substrate_corrections_parser.add_argument("--full", action="store_true", help="Print full correction metadata.")
    substrate_corrections_parser.add_argument("--json", action="store_true", help="Print JSON.")
    substrate_corrections_parser.set_defaults(func=handlers['cmd_substrate_corrections'])

    substrate_record_correction_parser = substrate_subparsers.add_parser(
        "record-correction",
        help="Record a user correction and convert it into a relationship episode.",
    )
    substrate_record_correction_parser.add_argument("text", help="Correction text.")
    substrate_record_correction_parser.add_argument("--thread-id", default="", help="Optional thread id.")
    substrate_record_correction_parser.add_argument("--message-id", default="", help="Optional user message id.")
    substrate_record_correction_parser.add_argument("--target-message-id", default="", help="Optional Eve message id being corrected.")
    substrate_record_correction_parser.add_argument("--json", action="store_true", help="Print JSON.")
    substrate_record_correction_parser.set_defaults(func=handlers['cmd_substrate_record_correction'])

    substrate_episodes_parser = substrate_subparsers.add_parser("episodes", help="List relationship episodes grounded in lived corrections.")
    substrate_episodes_parser.add_argument("--limit", type=int, default=10, help="Max episodes.")
    substrate_episodes_parser.add_argument("--runtime", action="store_true", help="Prefer the runtime bundle's episode log.")
    substrate_episodes_parser.add_argument("--full", action="store_true", help="Print full episode details.")
    substrate_episodes_parser.add_argument("--json", action="store_true", help="Print JSON.")
    substrate_episodes_parser.set_defaults(func=handlers['cmd_substrate_episodes'])

    developmental_parser = subparsers.add_parser("developmental", help="Run and inspect Eve's hourly developmental growth cycle.")
    developmental_subparsers = developmental_parser.add_subparsers(dest="developmental_command", required=True)
    developmental_run_parser = developmental_subparsers.add_parser("run", help="Run one observe/interpret/care/choose/act/reflect/improve cycle.")
    developmental_run_parser.add_argument("--force", action="store_true", help="Mark the cycle as forced/manual in the record.")
    developmental_run_parser.add_argument("--full", action="store_true", help="Print full cycle detail.")
    developmental_run_parser.add_argument("--json", action="store_true", help="Print the full cycle record as JSON.")
    developmental_run_parser.set_defaults(func=handlers['cmd_developmental_run'])

    developmental_list_parser = developmental_subparsers.add_parser("list", help="List developmental cycle records.")
    developmental_list_parser.add_argument("--limit", type=int, default=10, help="Max cycles to print.")
    developmental_list_parser.add_argument("--days", type=int, help="Filter to recent days.")
    developmental_list_parser.add_argument("--runtime", action="store_true", help="Force reading the runtime store.")
    developmental_list_parser.add_argument("--full", action="store_true", help="Print full cycle detail.")
    developmental_list_parser.set_defaults(func=handlers['cmd_developmental_list'])

    developmental_map_parser = developmental_subparsers.add_parser("map", help="Show Eve's current developmental architecture map.")
    developmental_map_parser.set_defaults(func=handlers['cmd_developmental_map'])

    organs_parser = subparsers.add_parser("organs", help="Inspect Eve's integrated organ-system status and pulse ledger.")
    organs_subparsers = organs_parser.add_subparsers(dest="organs_command", required=True)

    organs_status_parser = organs_subparsers.add_parser("status", help="Show Eve's current organ assimilation state.")
    organs_status_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime state where available.")
    organs_status_parser.add_argument("--full", action="store_true", help="Print full organ details.")
    organs_status_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    organs_status_parser.set_defaults(func=handlers['cmd_organs_status'])

    organs_pulse_parser = organs_subparsers.add_parser(
        "pulse",
        help="Record an organ pulse into the organ ledger and canonical event ledger.",
    )
    organs_pulse_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime state where available.")
    organs_pulse_parser.add_argument("--full", action="store_true", help="Print full organ details.")
    organs_pulse_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    organs_pulse_parser.set_defaults(func=handlers['cmd_organs_pulse'])

    capabilities_parser = subparsers.add_parser("capabilities", help="Inspect or test Eve's tool capabilities.")
    capabilities_subparsers = capabilities_parser.add_subparsers(dest="capabilities_command", required=True)

    capabilities_list_parser = capabilities_subparsers.add_parser("list", help="List Eve's current tools.")
    capabilities_list_parser.set_defaults(func=handlers['cmd_capabilities_list'])

    capabilities_gaps_parser = capabilities_subparsers.add_parser("gaps", help="List unsupported commitments Eve logged as capability gaps.")
    capabilities_gaps_parser.add_argument("--limit", type=int, default=20, help="Max gaps to print.")
    capabilities_gaps_parser.add_argument("--status", help="Filter by gap status.")
    capabilities_gaps_parser.add_argument("--runtime", action="store_true", help="Prefer the runtime bundle's gap log.")
    capabilities_gaps_parser.add_argument("--full", action="store_true", help="Print acquisition plans and known tools.")
    capabilities_gaps_parser.set_defaults(func=handlers['cmd_capabilities_gaps'])

    capabilities_scout_parser = capabilities_subparsers.add_parser(
        "scout",
        help="Compare OpenClaw-native capabilities with external open-source agent code candidates.",
    )
    capabilities_scout_parser.add_argument("--status", action="store_true", help="Show the last saved scout report instead of running a fresh scan.")
    capabilities_scout_parser.add_argument("--runtime", action="store_true", help="Prefer the runtime bundle's saved scout report when using --status.")
    capabilities_scout_parser.add_argument("--web", action="store_true", help="Also run bounded web searches for emerging agent code candidates.")
    capabilities_scout_parser.add_argument("--query", action="append", help="Extra web search query to run with --web. Can be repeated.")
    capabilities_scout_parser.add_argument("--refresh-openclaw", action="store_true", help="Fetch the OpenClaw source mirror before scanning for capabilities.")
    capabilities_scout_parser.add_argument("--timeout", type=int, default=180, help="Timeout in seconds for mirror refresh and web probes.")
    capabilities_scout_parser.add_argument("--full", action="store_true", help="Print candidate details, evidence, and web hits.")
    capabilities_scout_parser.set_defaults(func=handlers['cmd_capabilities_scout'])

    capabilities_intelligence_parser = capabilities_subparsers.add_parser(
        "intelligence",
        help="Inspect or refresh Eve's recurring subsystem version, feature, and configuration ledger.",
    )
    capability_intelligence_subparsers = capabilities_intelligence_parser.add_subparsers(
        dest="intelligence_command",
        required=True,
    )
    capability_intelligence_status_parser = capability_intelligence_subparsers.add_parser(
        "status",
        help="Show the latest capability-intelligence snapshot.",
    )
    capability_intelligence_status_parser.add_argument("--runtime", action="store_true", help="Prefer the live runtime snapshot.")
    capability_intelligence_status_parser.add_argument("--full", action="store_true", help="Print all current findings and configured paths.")
    capability_intelligence_status_parser.add_argument("--json", action="store_true", help="Print the complete structured snapshot.")
    capability_intelligence_status_parser.set_defaults(func=handlers['cmd_capabilities_intelligence'])

    capability_intelligence_refresh_parser = capability_intelligence_subparsers.add_parser(
        "refresh",
        help="Run a fresh local inventory, optionally refreshing upstream releases, components, and Hermes.",
    )
    capability_intelligence_refresh_parser.add_argument("--upstream", action="store_true", help="Refresh authoritative GitHub release feeds.")
    capability_intelligence_refresh_parser.add_argument("--components", action="store_true", help="Also refresh the installed-component watcher and OpenClaw source scout.")
    capability_intelligence_refresh_parser.add_argument(
        "--hermes",
        action="store_true",
        help=(
            "Refresh Hermes config/prompt hygiene, security, curator, tools, skills, plugins, memory, "
            "MCP/ACP, projects/Kanban, checkpoints, model orchestration, gateway, hooks/cron, sessions, and feature policy."
        ),
    )
    capability_intelligence_refresh_parser.add_argument("--all", action="store_true", help="Refresh local, upstream, component, OpenClaw, and Hermes evidence together.")
    capability_intelligence_refresh_parser.add_argument("--timeout", type=int, default=45, help="Per-command timeout in seconds.")
    capability_intelligence_refresh_parser.add_argument("--runtime", action="store_true", help="Prefer runtime artifacts when formatting paths.")
    capability_intelligence_refresh_parser.add_argument("--full", action="store_true", help="Print all current findings and configured paths.")
    capability_intelligence_refresh_parser.add_argument("--json", action="store_true", help="Print the complete structured snapshot.")
    capability_intelligence_refresh_parser.set_defaults(func=handlers['cmd_capabilities_intelligence'])

    capability_intelligence_attest_parser = capability_intelligence_subparsers.add_parser(
        "attest",
        help="Prove that owned configuration reaches its live consumer and a current consequence without refreshing upstream research.",
    )
    capability_intelligence_attest_parser.add_argument("--timeout", type=int, default=45, help="Per-command timeout in seconds.")
    capability_intelligence_attest_parser.add_argument("--runtime", action="store_true", help="Prefer runtime artifacts when formatting paths.")
    capability_intelligence_attest_parser.add_argument("--full", action="store_true", help="Print all effective-runtime contracts and blockers.")
    capability_intelligence_attest_parser.add_argument("--json", action="store_true", help="Print the complete structured snapshot.")
    capability_intelligence_attest_parser.set_defaults(func=handlers['cmd_capabilities_intelligence'])

    capability_intelligence_history_parser = capability_intelligence_subparsers.add_parser(
        "history",
        help="Read the append-only compact history of recurring capability checks.",
    )
    capability_intelligence_history_parser.add_argument("--limit", type=int, default=20, help="Maximum checks to read.")
    capability_intelligence_history_parser.add_argument("--runtime", action="store_true", help="Prefer the live runtime history.")
    capability_intelligence_history_parser.add_argument("--full", action="store_true", help="Print summaries, versions, and release heads.")
    capability_intelligence_history_parser.add_argument("--json", action="store_true", help="Print structured history records.")
    capability_intelligence_history_parser.set_defaults(func=handlers['cmd_capabilities_intelligence'])

    capabilities_adoption_parser = capabilities_subparsers.add_parser(
        "adoption",
        help="Resolve, research, canary, and route one capability through Eve's capability-first self-development loop.",
    )
    capability_adoption_subparsers = capabilities_adoption_parser.add_subparsers(
        dest="capability_adoption_command",
        required=True,
    )
    capability_adoption_status_parser = capability_adoption_subparsers.add_parser(
        "status",
        help="Show the latest capability-first self-development cycle.",
    )
    capability_adoption_status_parser.add_argument("--runtime", action="store_true", help="Prefer the live runtime state.")
    capability_adoption_status_parser.add_argument("--full", action="store_true", help="Print cycle evidence and artifact paths.")
    capability_adoption_status_parser.add_argument("--json", action="store_true", help="Print structured state.")
    capability_adoption_status_parser.set_defaults(func=handlers['cmd_capabilities_adoption'])

    capability_adoption_history_parser = capability_adoption_subparsers.add_parser(
        "history",
        help="Read recent capability-first cycles.",
    )
    capability_adoption_history_parser.add_argument("--limit", type=int, default=20, help="Maximum cycles to read.")
    capability_adoption_history_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime history.")
    capability_adoption_history_parser.add_argument("--full", action="store_true", help="Print complete cycle summaries.")
    capability_adoption_history_parser.add_argument("--json", action="store_true", help="Print structured cycle records.")
    capability_adoption_history_parser.set_defaults(func=handlers['cmd_capabilities_adoption'])

    capability_adoption_resolve_parser = capability_adoption_subparsers.add_parser(
        "resolve",
        help="Prove whether an objective should use, configure, canary, research, or build before coding.",
    )
    capability_adoption_resolve_parser.add_argument("objective", help="Capability or outcome Eve is considering.")
    capability_adoption_resolve_parser.add_argument("--need", action="append", help="Resolve a bounded explicit subtask against the real registry (repeat up to four times); discovery only, not execution permission.")
    capability_adoption_resolve_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime evidence.")
    capability_adoption_resolve_parser.add_argument("--full", action="store_true", help="Print matches and evidence fingerprints.")
    capability_adoption_resolve_parser.add_argument("--json", action="store_true", help="Print the structured resolution.")
    capability_adoption_resolve_parser.set_defaults(func=handlers['cmd_capabilities_adoption'])

    capability_adoption_cycle_parser = capability_adoption_subparsers.add_parser(
        "cycle",
        help="Run one rotating capability-first discovery/adoption/build-routing cycle.",
    )
    capability_adoption_cycle_parser.add_argument("--objective", default="", help="Optional explicit objective; otherwise rotate the next real gap or upstream candidate.")
    capability_adoption_cycle_parser.add_argument("--research", action="store_true", help="Read the target's official GitHub metadata, README/docs, and recent commits.")
    capability_adoption_cycle_parser.add_argument("--discover", action="store_true", help="Also run one rotating GitHub repository discovery query; results remain research-only.")
    capability_adoption_cycle_parser.add_argument("--no-canary", action="store_true", help="Resolve and research without executing an isolated candidate canary.")
    capability_adoption_cycle_parser.add_argument("--no-handoff", action="store_true", help="Do not create a local Codex handoff/system task for a proven build or promotion gap.")
    capability_adoption_cycle_parser.add_argument("--timeout", type=int, default=300, help="Bound for package staging and online requests.")
    capability_adoption_cycle_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime evidence when resolving.")
    capability_adoption_cycle_parser.add_argument("--full", action="store_true", help="Print cycle evidence and artifacts.")
    capability_adoption_cycle_parser.add_argument("--json", action="store_true", help="Print the structured cycle.")
    capability_adoption_cycle_parser.set_defaults(func=handlers['cmd_capabilities_adoption'])

    capabilities_integrate_parser = capabilities_subparsers.add_parser(
        "integrate",
        help="Build a bounded integration registry from OpenClaw/native capabilities and external agent-framework candidates.",
    )
    capabilities_integrate_parser.add_argument("--status", action="store_true", help="Show the last saved integration state instead of rebuilding it.")
    capabilities_integrate_parser.add_argument("--runtime", action="store_true", help="Prefer the runtime bundle's saved integration state when using --status.")
    capabilities_integrate_parser.add_argument("--apply", action="store_true", help="Create or refresh concrete system tasks for prototype integration work.")
    capabilities_integrate_parser.add_argument("--refresh-scout", action="store_true", help="Run a fresh capability scout before building the integration state.")
    capabilities_integrate_parser.add_argument("--refresh-openclaw", action="store_true", help="Fetch the OpenClaw source mirror first when using --refresh-scout.")
    capabilities_integrate_parser.add_argument("--web", action="store_true", help="Allow bounded web research during the scout refresh.")
    capabilities_integrate_parser.add_argument("--timeout", type=int, default=180, help="Timeout in seconds for mirror refresh and web probes.")
    capabilities_integrate_parser.add_argument("--full", action="store_true", help="Print route details, local surfaces, and mapped candidates.")
    capabilities_integrate_parser.set_defaults(func=handlers['cmd_capabilities_integrate'])

    capabilities_map_parser = capabilities_subparsers.add_parser(
        "map",
        help="Build or inspect Eve's ability map with locations and access paths.",
    )
    capabilities_map_parser.add_argument("--status", action="store_true", help="Show the last saved ability map instead of rebuilding it.")
    capabilities_map_parser.add_argument("--runtime", action="store_true", help="Prefer the runtime bundle's saved ability map/state.")
    capabilities_map_parser.add_argument("--refresh-scout", action="store_true", help="Refresh OpenClaw/source capability scout before mapping abilities.")
    capabilities_map_parser.add_argument("--source", help="Filter output by ability source, such as openclaw_native or eve_native.")
    capabilities_map_parser.add_argument("--query", help="Filter output by text in id, name, category, description, or location.")
    capabilities_map_parser.add_argument("--full", action="store_true", help="Print locations, access paths, boundaries, and next steps.")
    capabilities_map_parser.add_argument("--json", action="store_true", help="Print the full ability map as JSON.")
    capabilities_map_parser.add_argument("--no-save", action="store_true", help="Do not write .eve/ability_map.json.")
    capabilities_map_parser.set_defaults(func=handlers['cmd_capabilities_map'])

    capabilities_research_parser = capabilities_subparsers.add_parser(
        "research",
        help="Build Eve's reusable capability-research report for a docs/source/tool subject.",
    )
    capabilities_research_parser.add_argument("subject", help="Subject to research, such as CopilotKit.")
    capabilities_research_parser.add_argument("--prompt", default="", help="Original user prompt that triggered the research.")
    capabilities_research_parser.add_argument("--runtime", action="store_true", help="Prefer runtime evidence where available.")
    capabilities_research_parser.add_argument("--write", action="store_true", help="Write the reusable capability report and event evidence.")
    capabilities_research_parser.add_argument("--full", action="store_true", help="Print matched terms and source refs.")
    capabilities_research_parser.add_argument("--json", action="store_true", help="Print the full report as JSON.")
    capabilities_research_parser.set_defaults(func=handlers['cmd_capabilities_research'])

    capabilities_test_parser = capabilities_subparsers.add_parser(
        "test",
        help="Have Eve self-test her tool capabilities end to end.",
    )
    capabilities_test_parser.add_argument("--model", help="Override model name.")
    capabilities_test_parser.add_argument("--max-tokens", type=int, help="Max tokens to predict.")
    capabilities_test_parser.set_defaults(func=handlers['cmd_capabilities_test'])

    awareness_parser = subparsers.add_parser(
        "awareness",
        help="Run an evidence-backed self-awareness check and record the result.",
    )
    awareness_parser.add_argument("--model", help="Override model name.")
    awareness_parser.add_argument("--max-tokens", type=int, help="Max tokens to predict.")
    awareness_parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force a fresh durable human-context refresh before running the check.",
    )
    awareness_parser.set_defaults(func=handlers['cmd_awareness'])

    awareness_battery_parser = subparsers.add_parser(
        "awareness-battery",
        help="Run both the open-book awareness check and the closed-book human-analog self-awareness battery.",
    )
    awareness_battery_parser.add_argument("--model", help="Override model name.")
    awareness_battery_parser.add_argument("--max-tokens", type=int, help="Max tokens to predict for each subtest.")
    awareness_battery_parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force a fresh durable human-context refresh before running the battery.",
    )
    awareness_battery_parser.set_defaults(func=handlers['cmd_awareness_battery'])

    awareness_perturb_parser = subparsers.add_parser(
        "awareness-perturb",
        help="Run the perturbation battery for partial-memory gaps, false-belief injection, tool-failure grounding, and self/other boundary stress.",
    )
    awareness_perturb_parser.add_argument("--model", help="Override model name.")
    awareness_perturb_parser.add_argument("--max-tokens", type=int, help="Max tokens to predict.")
    awareness_perturb_parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force a fresh durable human-context refresh before running the perturbation battery.",
    )
    awareness_perturb_parser.set_defaults(func=handlers['cmd_awareness_perturb'])

    consciousness_test_parser = subparsers.add_parser(
        "consciousness-test",
        help="Run the integrated consciousness-evidence test across awareness, perturbation, workspace, homeostasis, and action traces.",
    )
    consciousness_test_parser.add_argument("--model", help="Override model name.")
    consciousness_test_parser.add_argument("--max-tokens", type=int, help="Max tokens to predict for each model subtest.")
    consciousness_test_parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force a fresh durable human-context refresh before running the test.",
    )
    consciousness_test_parser.set_defaults(func=handlers['cmd_consciousness_test'])

    presence_parser = subparsers.add_parser(
        "presence",
        help="Inspect or record Eve's current integrated presence state.",
    )
    presence_subparsers = presence_parser.add_subparsers(dest="presence_command", required=True)

    presence_status_parser = presence_subparsers.add_parser(
        "status",
        help="Show Eve's current presence report: workspace, homeostasis, consciousness evidence, and organ embodiment.",
    )
    presence_status_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime state where available.")
    presence_status_parser.add_argument("--full", action="store_true", help="Print full presence and organ details.")
    presence_status_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    presence_status_parser.set_defaults(func=handlers['cmd_presence_status'])

    presence_pulse_parser = presence_subparsers.add_parser(
        "pulse",
        help="Record a presence pulse into the presence ledger and canonical event ledger.",
    )
    presence_pulse_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime state where available.")
    presence_pulse_parser.add_argument("--full", action="store_true", help="Print full presence and organ details.")
    presence_pulse_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    presence_pulse_parser.set_defaults(func=handlers['cmd_presence_pulse'])

    presence_cycle_parser = presence_subparsers.add_parser(
        "cycle",
        help="Run one lived presence cycle: refresh mind/workspace, act once, verify, reflect, and record evidence.",
    )
    presence_cycle_parser.add_argument("--force", action="store_true", help="Force the bounded action even if a cycle recently ran.")
    presence_cycle_parser.add_argument("--max-tokens", type=int, help="Max tokens for the mind refresh model call.")
    presence_cycle_parser.add_argument("--no-mind", action="store_true", help="Skip the active-mind refresh stage.")
    presence_cycle_parser.add_argument("--no-workspace", action="store_true", help="Skip workspace refresh stages.")
    presence_cycle_parser.add_argument("--no-action", action="store_true", help="Skip the bounded developmental action.")
    presence_cycle_parser.add_argument("--no-pulse", action="store_true", help="Skip recording a presence pulse.")
    presence_cycle_parser.add_argument("--full", action="store_true", help="Print stage details and developmental-cycle summary.")
    presence_cycle_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    presence_cycle_parser.set_defaults(func=handlers['cmd_presence_cycle'])

    model_parser = subparsers.add_parser("model", help="Inspect or certify candidate models against Eve's current behavior.")
    model_subparsers = model_parser.add_subparsers(dest="model_command", required=True)

    model_certify_parser = model_subparsers.add_parser(
        "certify",
        help="Compare a candidate model against a baseline using shared-memory checks and reply probes.",
    )
    model_certify_parser.add_argument("--candidate", required=True, help="Candidate model name to certify.")
    model_certify_parser.add_argument("--baseline", help="Baseline model to compare against. Defaults to Eve's configured model.")
    model_certify_parser.add_argument("--max-tokens", type=int, help="Max tokens for each fixed reply probe.")
    model_certify_parser.add_argument("--skip-awareness", action="store_true", help="Skip the self-awareness check.")
    model_certify_parser.add_argument("--skip-capabilities", action="store_true", help="Skip the tool capability check.")
    model_certify_parser.add_argument("--full", action="store_true", help="Print probe responses in addition to the summary.")
    model_certify_parser.set_defaults(func=handlers['cmd_model_certify'])

    model_exercise_parser = model_subparsers.add_parser(
        "exercise",
        help="Exercise Eve's five live lanes side by side and save the outputs.",
    )
    model_exercise_parser.add_argument("--prompt", help="Optional shared exercise prompt.")
    model_exercise_parser.add_argument("--max-tokens", type=int, help="Max tokens per lane.")
    model_exercise_parser.add_argument("--timeout", type=int, help="Per-lane timeout in seconds.")
    model_exercise_parser.add_argument("--full", action="store_true", help="Print fuller lane output.")
    model_exercise_parser.set_defaults(func=handlers['cmd_model_exercise'])

    model_bakeoff_parser = model_subparsers.add_parser(
        "bakeoff",
        help="Run a lightweight controlled comparison across baseline and candidate live model aliases.",
    )
    model_bakeoff_parser.add_argument("--candidate", action="append", help="Candidate model alias/name. Can be repeated.")
    model_bakeoff_parser.add_argument("--baseline", help="Baseline model. Defaults to Eve's configured fast/chat model.")
    model_bakeoff_parser.add_argument(
        "--suite",
        choices=sorted(settings['MODEL_BAKEOFF_SUITES'].keys()),
        default="generic",
        help="Prompt suite to run. Use `deep` for Eve's deep-lane purpose.",
    )
    model_bakeoff_parser.add_argument("--max-tokens", type=int, help="Max tokens per probe.")
    model_bakeoff_parser.add_argument("--timeout", type=int, help="Per-probe timeout in seconds.")
    model_bakeoff_parser.add_argument("--full", action="store_true", help="Print probe responses and issues.")
    model_bakeoff_parser.set_defaults(func=handlers['cmd_model_bakeoff'])

    model_scout_parser = model_subparsers.add_parser(
        "scout",
        help="Inspect five-lane resource budgets and shortlist online model candidates.",
    )
    model_scout_parser.add_argument("--offline", action="store_true", help="Skip online Hugging Face candidate scan.")
    model_scout_parser.add_argument("--limit", type=int, default=30, help="Max online candidates to keep.")
    model_scout_parser.add_argument("--full", action="store_true", help="Print sources and more candidates.")
    model_scout_parser.add_argument("--json", action="store_true", help="Print full scout artifact JSON.")
    model_scout_parser.set_defaults(func=handlers['cmd_model_scout'])

    model_mtp_lab_parser = model_subparsers.add_parser(
        "mtp-lab",
        help="Run the non-live Gemma 4 MTP lab runner and record target-plus-drafter evidence.",
    )
    model_mtp_lab_parser.add_argument("--mode", choices=["preflight", "download", "llama-smoke", "all", "transformers-smoke", "all-transformers"], default="preflight")
    model_mtp_lab_parser.add_argument("--candidate", choices=["e2b-lab-gguf", "e4b-local-gguf"], default="e4b-local-gguf")
    model_mtp_lab_parser.add_argument("--python", help="Python executable for the lab runner. Defaults to .venv-techlab for Transformers smoke.")
    model_mtp_lab_parser.add_argument("--network", action="store_true", help="Probe Hugging Face metadata before running.")
    model_mtp_lab_parser.add_argument("--write", action="store_true", help="Write .eve/gemma4_mtp_lab/latest.json and append history.")
    model_mtp_lab_parser.add_argument("--allow-download", action="store_true", help="Allow fetching the small assistant GGUF for llama.cpp lab modes.")
    model_mtp_lab_parser.add_argument("--dry-run", action="store_true", help="Build llama.cpp commands without starting llama-server.")
    model_mtp_lab_parser.add_argument("--keep-server", action="store_true", help="Leave the temporary llama.cpp server running after smoke.")
    model_mtp_lab_parser.add_argument("--timeout", type=int, default=900, help="Wrapper timeout in seconds.")
    model_mtp_lab_parser.add_argument("--port", type=int, default=8096)
    model_mtp_lab_parser.add_argument("--alias", default="eve-gemma4-e4b-mtp-lab")
    model_mtp_lab_parser.add_argument("--ctx-size", type=int, default=4096)
    model_mtp_lab_parser.add_argument("--draft-tokens", type=int, default=8)
    model_mtp_lab_parser.add_argument("--draft-block-size", type=int, default=2)
    model_mtp_lab_parser.add_argument("--llama-flavor", choices=["draft", "gemma4-mtp"], default="draft")
    model_mtp_lab_parser.add_argument("--trace-mtp", action="store_true", help="Record Gemma 4 MTP draft/accept trace evidence when using --llama-flavor gemma4-mtp.")
    model_mtp_lab_parser.add_argument("--startup-timeout", type=float, default=120.0)
    model_mtp_lab_parser.add_argument("--probe-timeout", type=float, default=120.0)
    model_mtp_lab_parser.add_argument("--llama-server", help="Path to llama-server for llama.cpp lab modes.")
    model_mtp_lab_parser.add_argument("--target-path", help="Local GGUF target path for llama.cpp lab modes.")
    model_mtp_lab_parser.add_argument("--assistant-path", help="Local GGUF assistant path for llama.cpp lab modes.")
    model_mtp_lab_parser.add_argument("--transformers-target", default="google/gemma-4-E2B-it")
    model_mtp_lab_parser.add_argument("--transformers-assistant", default="")
    model_mtp_lab_parser.add_argument("--device", choices=["auto", "mps", "cpu"], default="auto")
    model_mtp_lab_parser.add_argument("--torch-dtype", choices=["bfloat16", "float16"], default="bfloat16")
    model_mtp_lab_parser.add_argument("--max-new-tokens", type=int, default=48)
    model_mtp_lab_parser.add_argument("--prompt", default="")
    model_mtp_lab_parser.add_argument("--json", action="store_true", help="Print the raw lab report JSON.")
    model_mtp_lab_parser.set_defaults(func=handlers['cmd_model_mtp_lab'])

    message_parser = subparsers.add_parser("message", help="Exchange mailbox messages with Eve.")
    message_subparsers = message_parser.add_subparsers(dest="message_command", required=True)

    message_send_parser = message_subparsers.add_parser("send", help="Send a message to Eve without waiting for a reply.")
    message_send_parser.add_argument("body", help="Message body.")
    message_send_parser.add_argument("--subject", help="Optional subject.")
    message_send_parser.set_defaults(func=handlers['cmd_message_send'])

    message_ask_parser = message_subparsers.add_parser("ask", help="Send a message to Eve and get an immediate reply.")
    message_ask_parser.add_argument("body", help="Message body.")
    message_ask_parser.add_argument("--subject", help="Optional subject.")
    message_ask_parser.set_defaults(func=handlers['cmd_message_ask'])

    message_reply_parser = message_subparsers.add_parser("reply", help="Reply to an existing Eve message and get a response.")
    message_reply_parser.add_argument("--sender", default="user", choices=["user", "claude", "codex"], help="Who is writing this reply. Claude and Codex are recorded as external operators, never as the user.")
    message_reply_parser.add_argument("id", help="Message id to reply to.")
    message_reply_parser.add_argument("body", help="Reply body.")
    message_reply_parser.add_argument("--subject", help="Optional subject override.")
    message_reply_parser.set_defaults(func=handlers['cmd_message_reply'])

    message_initiate_parser = message_subparsers.add_parser(
        "initiate",
        help="Let Eve initiate a fresh message thread without waiting for user input.",
    )
    message_initiate_parser.set_defaults(func=handlers['cmd_message_initiate'])

    message_list_parser = message_subparsers.add_parser("list", help="List mailbox messages.")
    message_list_parser.add_argument("--limit", type=int, default=20, help="Max messages to print.")
    message_list_parser.add_argument("--sender", help="Filter by sender.")
    message_list_parser.add_argument("--recipient", help="Filter by recipient.")
    message_list_parser.add_argument(
        "--status",
        choices=["unread", "read", "archived", "sent"],
        help="Filter by status.",
    )
    message_list_parser.add_argument("--thread", help="Filter by thread id.")
    message_list_parser.add_argument("--full", action="store_true", help="Print full message bodies.")
    message_list_parser.set_defaults(func=handlers['cmd_message_list'])

    message_open_parser = message_subparsers.add_parser("open", help="Open a single message.")
    message_open_parser.add_argument("id", help="Message id.")
    message_open_parser.set_defaults(func=handlers['cmd_message_open'])

    message_mark_parser = message_subparsers.add_parser("mark", help="Mark a message as read or archived.")
    message_mark_parser.add_argument("id", help="Message id.")
    message_mark_parser.add_argument(
        "--status",
        required=True,
        choices=["unread", "read", "archived", "sent"],
        help="New message status.",
    )
    message_mark_parser.add_argument(
        "--direction",
        choices=settings['OUTCOME_DIRECTIONS'],
        help="Optional outcome direction to log alongside the status change.",
    )
    message_mark_parser.add_argument("--outcome", help="Optional outcome label to log.")
    message_mark_parser.add_argument("--summary", help="Optional outcome summary to log.")
    message_mark_parser.set_defaults(func=handlers['cmd_message_mark'])

    claude_parser = subparsers.add_parser("claude", help="Bridge Eve with Claude through the shared mailbox.")
    claude_subparsers = claude_parser.add_subparsers(dest="claude_command", required=True)

    claude_send_parser = claude_subparsers.add_parser("send", help="Send a message from Eve to Claude.")
    claude_send_parser.add_argument("body", help="Message body.")
    claude_send_parser.add_argument("--subject", help="Optional subject.")
    claude_send_parser.set_defaults(func=handlers['cmd_claude_send'])

    claude_ask_parser = claude_subparsers.add_parser("ask", help="Send Claude's message to Eve and get an immediate reply.")
    claude_ask_parser.add_argument("body", help="Message body.")
    claude_ask_parser.add_argument("--subject", help="Optional subject.")
    claude_ask_parser.set_defaults(func=handlers['cmd_claude_ask'])

    claude_reply_parser = claude_subparsers.add_parser(
        "reply",
        help="Reply from Claude to an Eve bridge message and get the next Eve reply.",
    )
    claude_reply_parser.add_argument("id", help="Target Eve bridge message id.")
    claude_reply_parser.add_argument("body", help="Reply body.")
    claude_reply_parser.add_argument("--subject", help="Optional subject override.")
    claude_reply_parser.set_defaults(func=handlers['cmd_claude_reply'])

    claude_inbox_parser = claude_subparsers.add_parser("inbox", help="List Claude bridge messages waiting in Eve.")
    claude_inbox_parser.add_argument("--limit", type=int, default=10, help="How many messages to show.")
    claude_inbox_parser.add_argument(
        "--status",
        choices=["unread", "read", "archived"],
        help="Filter by status.",
    )
    claude_inbox_parser.add_argument("--thread", help="Filter by thread id.")
    claude_inbox_parser.add_argument("--full", action="store_true", help="Print full message bodies.")
    claude_inbox_parser.set_defaults(func=handlers['cmd_claude_inbox'])

    claude_open_parser = claude_subparsers.add_parser("open", help="Open one Claude bridge message.")
    claude_open_parser.add_argument("id", help="Message id.")
    claude_open_parser.set_defaults(func=handlers['cmd_claude_open'])

    codex_parser = subparsers.add_parser("codex", help="Bridge Eve with Codex through the shared mailbox.")
    codex_subparsers = codex_parser.add_subparsers(dest="codex_command", required=True)

    codex_send_parser = codex_subparsers.add_parser("send", help="Send an operational message from Eve to Codex.")
    codex_send_parser.add_argument("body", help="Message body.")
    codex_send_parser.add_argument("--subject", help="Optional subject.")
    codex_send_parser.set_defaults(func=handlers['cmd_codex_send'])

    codex_handoff_parser = codex_subparsers.add_parser(
        "handoff",
        help="Create a bounded Eve-to-Codex independent-operator handoff and action record.",
    )
    codex_handoff_parser.add_argument("objective", help="Bounded objective for Codex.")
    codex_handoff_parser.add_argument("--subject", help="Optional bridge message subject.")
    codex_handoff_parser.add_argument("--repository", help="Repository or scope path for Codex.")
    codex_handoff_parser.add_argument(
        "--mode",
        default="bounded_review",
        choices=["bounded_review", "diagnosis_only", "patch_and_verify", "qa_audit"],
        help="Handoff mode.",
    )
    codex_handoff_parser.add_argument("--diagnosis-only", action="store_true", help="Force diagnosis-only mode.")
    codex_handoff_parser.add_argument("--acceptance", help="Acceptance criteria Codex must report against.")
    codex_handoff_parser.add_argument("--constraints", help="Additional boundaries for this handoff.")
    codex_handoff_parser.add_argument("--json", action="store_true", help="Print the action result as JSON.")
    codex_handoff_parser.set_defaults(func=handlers['cmd_codex_handoff'])

    codex_ask_parser = codex_subparsers.add_parser("ask", help="Send Codex's operational message to Eve and get an immediate reply.")
    codex_ask_parser.add_argument("body", help="Message body.")
    codex_ask_parser.add_argument("--subject", help="Optional subject.")
    codex_ask_parser.set_defaults(func=handlers['cmd_codex_ask'])

    codex_reply_parser = codex_subparsers.add_parser(
        "reply",
        help="Reply from Codex to an Eve bridge message and get the next Eve reply.",
    )
    codex_reply_parser.add_argument("id", help="Target Eve bridge message id.")
    codex_reply_parser.add_argument("body", help="Reply body.")
    codex_reply_parser.add_argument("--subject", help="Optional subject override.")
    codex_reply_parser.set_defaults(func=handlers['cmd_codex_reply'])

    codex_inbox_parser = codex_subparsers.add_parser("inbox", help="List Codex bridge messages waiting in Eve.")
    codex_inbox_parser.add_argument("--limit", type=int, default=10, help="How many messages to show.")
    codex_inbox_parser.add_argument(
        "--status",
        choices=["unread", "read", "archived"],
        help="Filter by status.",
    )
    codex_inbox_parser.add_argument("--thread", help="Filter by thread id.")
    codex_inbox_parser.add_argument("--full", action="store_true", help="Print full message bodies.")
    codex_inbox_parser.set_defaults(func=handlers['cmd_codex_inbox'])

    codex_open_parser = codex_subparsers.add_parser("open", help="Open one Codex bridge message.")
    codex_open_parser.add_argument("id", help="Message id.")
    codex_open_parser.set_defaults(func=handlers['cmd_codex_open'])

    self_parser = subparsers.add_parser("self", help="Run operational Eve-to-Eve threads through the shared mailbox.")
    self_subparsers = self_parser.add_subparsers(dest="self_command", required=True)

    self_send_parser = self_subparsers.add_parser("send", help="Write an operational note from Eve to herself.")
    self_send_parser.add_argument("body", help="Message body.")
    self_send_parser.add_argument("--subject", help="Optional subject.")
    self_send_parser.set_defaults(func=handlers['cmd_self_send'])

    self_ask_parser = self_subparsers.add_parser("ask", help="Ask Eve's operational self a question and get an immediate reply.")
    self_ask_parser.add_argument("body", help="Message body.")
    self_ask_parser.add_argument("--subject", help="Optional subject.")
    self_ask_parser.set_defaults(func=handlers['cmd_self_ask'])

    self_reply_parser = self_subparsers.add_parser("reply", help="Continue an existing Eve operational self thread.")
    self_reply_parser.add_argument("id", help="Target Eve operational message id.")
    self_reply_parser.add_argument("body", help="Reply body.")
    self_reply_parser.add_argument("--subject", help="Optional subject override.")
    self_reply_parser.set_defaults(func=handlers['cmd_self_reply'])

    self_inbox_parser = self_subparsers.add_parser("inbox", help="List Eve's operational self-thread messages.")
    self_inbox_parser.add_argument("--limit", type=int, default=10, help="How many messages to show.")
    self_inbox_parser.add_argument(
        "--status",
        choices=["unread", "read", "archived", "sent"],
        help="Filter by status.",
    )
    self_inbox_parser.add_argument("--thread", help="Filter by thread id.")
    self_inbox_parser.add_argument("--full", action="store_true", help="Print full message bodies.")
    self_inbox_parser.set_defaults(func=handlers['cmd_self_inbox'])

    self_open_parser = self_subparsers.add_parser("open", help="Open one Eve operational self-thread message.")
    self_open_parser.add_argument("id", help="Message id.")
    self_open_parser.set_defaults(func=handlers['cmd_self_open'])

    talk_parser = subparsers.add_parser("talk", help="Start an interactive conversation with Eve.")
    talk_parser.add_argument("--subject", help="Optional thread subject.")
    talk_parser.add_argument("--first", help="Optional first message before entering the loop.")
    talk_parser.set_defaults(func=handlers['cmd_talk'])

    code_parser = subparsers.add_parser("code", help="Talk to Eve in bounded coder mode.")
    code_subparsers = code_parser.add_subparsers(dest="code_command", required=True)

    code_ask_parser = code_subparsers.add_parser("ask", help="Ask Eve to inspect, patch, and verify code.")
    code_ask_parser.add_argument("request", help="Coding request for Eve.")
    code_ask_parser.add_argument("--session", help="Optional coder session id to continue.")
    code_ask_parser.add_argument("--model", help="Override model name.")
    code_ask_parser.add_argument("--max-tokens", type=int, help="Max tokens per model step.")
    code_ask_parser.add_argument("--no-require-tool", action="store_true", help="Allow a direct answer without tool use.")
    code_ask_parser.add_argument("--show-session", action="store_true", help="Print the session id and log path after the answer.")
    code_ask_parser.set_defaults(func=handlers['cmd_code_ask'])

    code_session_parser = code_subparsers.add_parser("session", help="Start an interactive Eve coder session.")
    code_session_parser.add_argument("--session", help="Optional coder session id to continue.")
    code_session_parser.add_argument("--first", help="Optional first coding request before entering the loop.")
    code_session_parser.add_argument("--model", help="Override model name.")
    code_session_parser.add_argument("--max-tokens", type=int, help="Max tokens per model step.")
    code_session_parser.add_argument("--no-require-tool", action="store_true", help="Allow direct answers without tool use.")
    code_session_parser.set_defaults(func=handlers['cmd_code_session'])

    code_list_parser = code_subparsers.add_parser("list", help="List recent Eve coder sessions.")
    code_list_parser.add_argument("--limit", type=int, default=10, help="How many sessions to show.")
    code_list_parser.add_argument("--full", action="store_true", help="Show session log paths.")
    code_list_parser.set_defaults(func=handlers['cmd_code_list'])

    code_open_parser = code_subparsers.add_parser("open", help="Open one Eve coder session log.")
    code_open_parser.add_argument("session", help="Coder session id.")
    code_open_parser.add_argument("--limit", type=int, default=40, help="How many recent events to show.")
    code_open_parser.add_argument("--full", action="store_true", help="Print full JSON events.")
    code_open_parser.set_defaults(func=handlers['cmd_code_open'])

    code_compact_parser = code_subparsers.add_parser("compact", help="Dry-run or compact oversized Eve coder-session logs.")
    code_compact_parser.add_argument("--runtime", action="store_true", help="Include the live runtime code-session log directory.")
    code_compact_parser.add_argument("--apply", action="store_true", help="Actually compact oversized logs; default is dry-run.")
    code_compact_parser.add_argument("--max-mb", type=int, default=5, help="Maximum log size before compaction.")
    code_compact_parser.add_argument("--head-kb", type=int, default=64, help="Complete leading JSONL bytes to preserve.")
    code_compact_parser.add_argument("--tail-kb", type=int, default=512, help="Complete trailing JSONL bytes to preserve.")
    code_compact_parser.add_argument("--limit", type=int, default=20, help="Maximum oversized logs to print.")
    code_compact_parser.set_defaults(func=handlers['cmd_code_compact'])

    self_repair_parser = subparsers.add_parser(
        "self-repair",
        help="Create governed Eve self-repair plans for code patches or operational repairs.",
    )
    self_repair_subparsers = self_repair_parser.add_subparsers(dest="self_repair_command", required=True)

    self_repair_plan_parser = self_repair_subparsers.add_parser(
        "plan",
        help="Build a proposal-only self-repair plan without deploying code or executing operational commands.",
    )
    self_repair_plan_parser.add_argument("objective", help="Bounded self-repair objective.")
    self_repair_plan_parser.add_argument("--file", action="append", default=[], help="Expected changed file path. Repeatable.")
    self_repair_plan_parser.add_argument("--test", action="append", default=[], help="Verification command. Repeatable.")
    self_repair_plan_parser.add_argument("--diagnosis-only", action="store_true", help="Mark the repair plan as diagnosis-only.")
    self_repair_plan_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime artifacts when reading evidence.")
    self_repair_plan_parser.add_argument("--queue", action="store_true", help="Queue the reviewed CodePatchProposal in governance; operational plans cannot be queued as code patches.")
    self_repair_plan_parser.add_argument("--codex-handoff", action="store_true", help="Create a bounded Codex handoff from this plan.")
    self_repair_plan_parser.add_argument("--no-save", action="store_true", help="Print only; do not write .eve/self_repair artifacts.")
    self_repair_plan_parser.add_argument("--full", action="store_true", help="Include commands and lifecycle detail.")
    self_repair_plan_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    self_repair_plan_parser.set_defaults(func=handlers['cmd_self_repair_plan'])

    self_repair_isolation_parser = self_repair_subparsers.add_parser(
        "isolation",
        help="Preflight or run Eve's source-only disposable Apple container repair canary.",
    )
    self_repair_isolation_parser.add_argument("--execute", action="store_true", help="Run the fixed isolation probe; this never deploys a patch.")
    self_repair_isolation_parser.add_argument("--image", default="", help="Digest-pinned linux/arm64 Python image required with --execute.")
    self_repair_isolation_parser.add_argument("--output", default="", help="Optional JSON evidence path.")
    self_repair_isolation_parser.add_argument("--timeout", type=int, default=180, help="Bounded execution timeout in seconds.")
    self_repair_isolation_parser.add_argument("--no-write", action="store_true", help="Do not persist the report.")
    self_repair_isolation_parser.add_argument("--json", action="store_true", help="Print full JSON evidence.")
    self_repair_isolation_parser.set_defaults(func=handlers['cmd_self_repair_isolation'])

    economy_parser = subparsers.add_parser(
        "economy",
        help="Build proposal-only resource, value, opportunity, experiment, outreach, and revenue evidence for Eve.",
    )
    economy_subparsers = economy_parser.add_subparsers(dest="economy_command", required=True)

    def add_economy_common(economy_command_parser: argparse.ArgumentParser) -> None:
        economy_command_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime artifacts as input evidence.")
        economy_command_parser.add_argument("--no-save", action="store_true", help="Print only; do not write .eve/economy artifacts.")
        economy_command_parser.add_argument("--full", action="store_true", help="Print detailed text output.")
        economy_command_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
        economy_command_parser.set_defaults(func=handlers['cmd_economy'])

    economy_resources_parser = economy_subparsers.add_parser(
        "resources",
        help="Build Eve's proposal-only resource plan.",
    )
    add_economy_common(economy_resources_parser)

    economy_value_map_parser = economy_subparsers.add_parser(
        "value-map",
        help="Map verified Eve capabilities to proposal-only value hypotheses.",
    )
    add_economy_common(economy_value_map_parser)

    economy_opportunity_parser = economy_subparsers.add_parser(
        "opportunity",
        help="Build one proposal-only opportunity card.",
    )
    economy_opportunity_parser.add_argument("--idea", required=True, help="Opportunity idea to structure.")
    add_economy_common(economy_opportunity_parser)

    economy_experiment_parser = economy_subparsers.add_parser(
        "experiment",
        help="Build one draft-only economic experiment plan.",
    )
    economy_experiment_parser.add_argument("--opportunity", required=True, help="Opportunity or offer to test.")
    add_economy_common(economy_experiment_parser)

    economy_outreach_parser = economy_subparsers.add_parser(
        "outreach-draft",
        help="Draft outreach without sending it.",
    )
    economy_outreach_parser.add_argument("--opportunity", required=True, help="Opportunity or offer to draft around.")
    economy_outreach_parser.add_argument("--channel", required=True, help="Draft channel, such as email or Slack.")
    add_economy_common(economy_outreach_parser)

    economy_ledger_parser = economy_subparsers.add_parser(
        "ledger",
        help="Summarize revenue evidence without payment or spending authority.",
    )
    add_economy_common(economy_ledger_parser)

    app_parser = subparsers.add_parser("app", help="Run the local Eve web app.")
    app_parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    app_parser.add_argument("--port", type=int, default=8787, help="Port to bind.")
    app_parser.add_argument("--open", action="store_true", help="Open the app in a browser.")
    app_parser.set_defaults(func=handlers['cmd_app'])

    tension_parser = subparsers.add_parser("tension", help="Track a recurring contradiction or tradeoff.")
    tension_subparsers = tension_parser.add_subparsers(dest="tension_command", required=True)

    tension_add_parser = tension_subparsers.add_parser("add", help="Add a tension entry.")
    tension_add_parser.add_argument("summary", help="Short summary of the tension.")
    tension_add_parser.add_argument("--side-a", required=True, help="First side of the tension.")
    tension_add_parser.add_argument("--side-b", required=True, help="Second side of the tension.")
    tension_add_parser.add_argument("--values", nargs="*", default=[], help="Values surfaced by this tension.")
    tension_add_parser.add_argument("--question", required=True, help="Question this tension raises.")
    tension_add_parser.add_argument("--next-step", required=True, help="Practical next step.")
    tension_add_parser.add_argument(
        "--status",
        choices=["open", "learning", "closed"],
        default="open",
        help="Current tension status.",
    )
    tension_add_parser.set_defaults(func=handlers['cmd_tension_add'])

    tension_list_parser = tension_subparsers.add_parser("list", help="List tension entries.")
    tension_list_parser.add_argument("--limit", type=int, default=20, help="Max tensions to print.")
    tension_list_parser.add_argument(
        "--status",
        choices=["open", "learning", "closed"],
        help="Filter by status.",
    )
    tension_list_parser.set_defaults(func=handlers['cmd_tension_list'])

    tension_update_parser = tension_subparsers.add_parser("update", help="Update a tension entry.")
    tension_update_parser.add_argument("id", help="Tension id.")
    tension_update_parser.add_argument(
        "--status",
        choices=["open", "learning", "closed"],
        help="New status.",
    )
    tension_update_parser.add_argument("--question", help="Updated framing question.")
    tension_update_parser.add_argument("--next-step", help="Updated next step.")
    tension_update_parser.set_defaults(func=handlers['cmd_tension_update'])

    experiment_parser = subparsers.add_parser("experiment", help="Track a concrete experiment.")
    experiment_subparsers = experiment_parser.add_subparsers(dest="experiment_command", required=True)

    experiment_add_parser = experiment_subparsers.add_parser("add", help="Add an experiment.")
    experiment_add_parser.add_argument("name", help="Short experiment name.")
    experiment_add_parser.add_argument("--hypothesis", required=True, help="What this experiment is testing.")
    experiment_add_parser.add_argument("--action", required=True, help="What Eve should do.")
    experiment_add_parser.add_argument(
        "--success-criteria",
        required=True,
        help="How to judge whether the experiment helped.",
    )
    experiment_add_parser.add_argument("--duration-days", type=int, default=7, help="Intended duration.")
    experiment_add_parser.add_argument(
        "--status",
        choices=["planned", "active", "completed", "paused", "abandoned"],
        default="planned",
        help="Current experiment status.",
    )
    experiment_add_parser.add_argument("--notes", help="Optional notes.")
    experiment_add_parser.set_defaults(func=handlers['cmd_experiment_add'])

    experiment_list_parser = experiment_subparsers.add_parser("list", help="List experiments.")
    experiment_list_parser.add_argument("--limit", type=int, default=20, help="Max experiments to print.")
    experiment_list_parser.add_argument(
        "--status",
        choices=["planned", "active", "completed", "paused", "abandoned"],
        help="Filter by status.",
    )
    experiment_list_parser.set_defaults(func=handlers['cmd_experiment_list'])

    experiment_update_parser = experiment_subparsers.add_parser("update", help="Update an experiment.")
    experiment_update_parser.add_argument("id", help="Experiment id.")
    experiment_update_parser.add_argument(
        "--status",
        choices=["planned", "active", "completed", "paused", "abandoned"],
        help="New status.",
    )
    experiment_update_parser.add_argument("--outcome", help="Observed outcome.")
    experiment_update_parser.add_argument(
        "--direction",
        choices=settings['OUTCOME_DIRECTIONS'],
        help="Optional outcome direction when logging a structured experiment outcome.",
    )
    experiment_update_parser.add_argument("--notes", help="Updated notes.")
    experiment_update_parser.set_defaults(func=handlers['cmd_experiment_update'])

    lab_parser = subparsers.add_parser(
        "lab",
        help="Run bounded autoresearch-style experiments with before/after scorecards.",
    )
    lab_subparsers = lab_parser.add_subparsers(dest="lab_command", required=True)

    lab_program_parser = lab_subparsers.add_parser("program", help="Show the Eve Research Lab protocol.")
    lab_program_parser.set_defaults(func=handlers['cmd_lab_program'])

    lab_run_parser = lab_subparsers.add_parser("run", help="Run one allowlisted research lab experiment.")
    lab_run_parser.add_argument("--kind", choices=settings['RESEARCH_LAB_KIND_CHOICES'], default="whole_system_baseline", help="Experiment template to run.")
    lab_run_parser.add_argument("--hypothesis", required=True, help="What this lab run is testing.")
    lab_run_parser.add_argument("--budget-minutes", type=int, default=5, help="Fixed wall-clock budget for the lab run.")
    lab_run_parser.add_argument("--id", help="Optional stable run id.")
    lab_run_parser.add_argument("--runtime", action="store_true", help="Prefer runtime-bundle artifacts for before/after metrics.")
    lab_run_parser.add_argument("--full", action="store_true", help="Print command details.")
    lab_run_parser.add_argument("--json", action="store_true", help="Print the full run record as JSON.")
    lab_run_parser.set_defaults(func=handlers['cmd_lab_run'])

    lab_latest_parser = lab_subparsers.add_parser("latest", help="Show the latest research lab run.")
    lab_latest_parser.add_argument("--runtime", action="store_true", help="Prefer runtime-bundle artifacts.")
    lab_latest_parser.add_argument("--full", action="store_true", help="Print command details.")
    lab_latest_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    lab_latest_parser.set_defaults(func=handlers['cmd_lab_latest'])

    lab_list_parser = lab_subparsers.add_parser("list", help="List recent research lab runs.")
    lab_list_parser.add_argument("--limit", type=int, default=10, help="Max runs to print.")
    lab_list_parser.add_argument("--runtime", action="store_true", help="Prefer runtime-bundle artifacts.")
    lab_list_parser.add_argument("--full", action="store_true", help="Print command details.")
    lab_list_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    lab_list_parser.set_defaults(func=handlers['cmd_lab_list'])

    training_parser = subparsers.add_parser(
        "training",
        help="Build local-first Eve training datasets and adapter gates from verified evidence.",
    )
    training_subparsers = training_parser.add_subparsers(dest="training_command", required=True)

    training_dataset_parser = training_subparsers.add_parser(
        "dataset",
        help="Curate train/validation/private-holdout artifacts from verified Eve data.",
    )
    training_dataset_subparsers = training_dataset_parser.add_subparsers(dest="training_dataset_command", required=True)

    training_dataset_build_parser = training_dataset_subparsers.add_parser(
        "build",
        help="Build a curated training dataset from public manual probes, action logs, and user corrections.",
    )
    training_dataset_build_parser.add_argument(
        "--source",
        choices=sorted(settings['TRAINING_DATASET_SOURCES']),
        default="verified-failures",
        help="Which eligible examples to include.",
    )
    training_dataset_build_parser.add_argument("--limit", type=int, default=400, help="Maximum examples to include.")
    training_dataset_build_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime artifacts where available.")
    training_dataset_build_parser.add_argument("--seed", default="eve-training-holdout-v1", help="Stable split seed.")
    training_dataset_build_parser.add_argument("--validation-ratio", type=float, default=0.15, help="Validation split ratio.")
    training_dataset_build_parser.add_argument("--holdout-ratio", type=float, default=0.15, help="Private holdout split ratio.")
    training_dataset_build_parser.add_argument("--full", action="store_true", help="Print field and exclusion detail.")
    training_dataset_build_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    training_dataset_build_parser.add_argument("--no-save", action="store_true", help="Do not write dataset artifacts.")
    training_dataset_build_parser.set_defaults(func=handlers['cmd_training_dataset_build'])

    training_dataset_latest_parser = training_dataset_subparsers.add_parser(
        "latest",
        help="Show the latest training dataset summary.",
    )
    training_dataset_latest_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime artifacts where available.")
    training_dataset_latest_parser.add_argument("--full", action="store_true", help="Print fields, limits, and exclusions.")
    training_dataset_latest_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    training_dataset_latest_parser.set_defaults(func=handlers['cmd_training_dataset_latest'])

    training_lora_parser = training_subparsers.add_parser(
        "lora",
        help="Plan local LoRA/QLoRA training from Eve's curated dataset.",
    )
    training_lora_subparsers = training_lora_parser.add_subparsers(dest="training_lora_command", required=True)
    training_lora_plan_parser = training_lora_subparsers.add_parser(
        "plan",
        help="Validate dataset files and print the local training command scaffold.",
    )
    training_lora_plan_parser.add_argument("--base-model", help="Local base model path or Hugging Face id approved for local training.")
    training_lora_plan_parser.add_argument("--output-dir", help="Local output directory for the adapter.")
    training_lora_plan_parser.add_argument("--train-jsonl", help="Override train JSONL path.")
    training_lora_plan_parser.add_argument("--validation-jsonl", help="Override validation JSONL path.")
    training_lora_plan_parser.add_argument("--full", action="store_true", help="Print next-step guidance.")
    training_lora_plan_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    training_lora_plan_parser.set_defaults(func=handlers['cmd_training_lora_plan'])

    training_adapter_parser = training_subparsers.add_parser(
        "adapter",
        help="Run shadow and promotion gates for trained local adapters.",
    )
    training_adapter_subparsers = training_adapter_parser.add_subparsers(dest="training_adapter_command", required=True)
    training_adapter_shadow_parser = training_adapter_subparsers.add_parser(
        "shadow",
        help="Record validation shadow evidence for a candidate adapter without changing live routing.",
    )
    training_adapter_shadow_parser.add_argument("--adapter", help="Local adapter path.")
    training_adapter_shadow_parser.add_argument("--candidate-alias", help="Served local candidate alias for attribution.")
    training_adapter_shadow_parser.add_argument("--baseline-alias", default="eve-fast", help="Baseline lane/alias used in comparison.")
    training_adapter_shadow_parser.add_argument("--results-jsonl", help="JSONL rows with candidate_score and baseline_score.")
    training_adapter_shadow_parser.add_argument("--min-average", type=float, default=4.0, help="Minimum candidate average score.")
    training_adapter_shadow_parser.add_argument("--min-delta", type=float, default=0.25, help="Required average improvement over baseline.")
    training_adapter_shadow_parser.add_argument("--full", action="store_true", help="Print privacy/gate detail.")
    training_adapter_shadow_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    training_adapter_shadow_parser.add_argument("--no-save", action="store_true", help="Do not write shadow artifacts.")
    training_adapter_shadow_parser.set_defaults(func=handlers['cmd_training_adapter_shadow'])

    training_adapter_promote_parser = training_adapter_subparsers.add_parser(
        "promote",
        help="Check whether a trained adapter is ready for governed promotion review.",
    )
    training_adapter_promote_parser.add_argument("--shadow-report", help="Shadow report JSON path. Defaults to latest.")
    training_adapter_promote_parser.add_argument("--holdout-report", help="Private holdout pass report JSON path.")
    training_adapter_promote_parser.add_argument("--apply", action="store_true", help="Request live apply; currently always blocks.")
    training_adapter_promote_parser.add_argument("--full", action="store_true", help="Print promotion rule detail.")
    training_adapter_promote_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    training_adapter_promote_parser.add_argument("--no-save", action="store_true", help="Do not write promotion artifacts.")
    training_adapter_promote_parser.set_defaults(func=handlers['cmd_training_adapter_promote'])

    eval_parser = subparsers.add_parser("eval", help="Record structured evaluations and review scorecards.")
    eval_subparsers = eval_parser.add_subparsers(dest="eval_command", required=True)

    eval_add_parser = eval_subparsers.add_parser("add", help="Add a scorecard evaluation for a message, thought, reflection, or other target.")
    eval_add_parser.add_argument("--target-kind", required=True, choices=settings['FEEDBACK_TARGET_KINDS'], help="What kind of artifact is being reviewed.")
    eval_add_parser.add_argument("--target-id", required=True, help="The id of the artifact being reviewed.")
    eval_add_parser.add_argument("--thread", help="Optional related thread id.")
    eval_add_parser.add_argument("--evaluator", default="user", help="Who is recording the evaluation.")
    eval_add_parser.add_argument("--humanity", required=True, type=int, choices=range(1, 6), help="Score from 1 to 5.")
    eval_add_parser.add_argument("--helpfulness", required=True, type=int, choices=range(1, 6), help="Score from 1 to 5.")
    eval_add_parser.add_argument("--groundedness", required=True, type=int, choices=range(1, 6), help="Score from 1 to 5.")
    eval_add_parser.add_argument("--contact", required=True, type=int, choices=range(1, 6), help="Score from 1 to 5.")
    eval_add_parser.add_argument("--integrity", required=True, type=int, choices=range(1, 6), help="Score from 1 to 5.")
    eval_add_parser.add_argument("--summary", help="Short summary of why these scores were given.")
    eval_add_parser.add_argument("--evidence", help="Optional evidence or examples.")
    eval_add_parser.set_defaults(func=handlers['cmd_eval_add'])

    eval_list_parser = eval_subparsers.add_parser("list", help="List recorded evaluations.")
    eval_list_parser.add_argument("--limit", type=int, default=20, help="Max evaluations to print.")
    eval_list_parser.add_argument("--days", type=int, help="Filter to recent days.")
    eval_list_parser.add_argument("--target-kind", choices=settings['FEEDBACK_TARGET_KINDS'], help="Filter by target kind.")
    eval_list_parser.add_argument("--target-id", help="Filter by target id.")
    eval_list_parser.add_argument("--thread", help="Filter by related thread id.")
    eval_list_parser.add_argument("--evaluator", help="Filter by evaluator.")
    eval_list_parser.set_defaults(func=handlers['cmd_eval_list'])

    eval_scorecard_parser = eval_subparsers.add_parser("scorecard", help="Show aggregate scorecard and outcome summaries.")
    eval_scorecard_parser.add_argument("--limit", type=int, default=40, help="How many recent records to inspect.")
    eval_scorecard_parser.add_argument("--days", type=int, default=30, help="How many recent days to inspect.")
    eval_scorecard_parser.add_argument("--target-kind", choices=settings['FEEDBACK_TARGET_KINDS'], help="Filter by target kind.")
    eval_scorecard_parser.add_argument("--target-id", help="Filter by target id.")
    eval_scorecard_parser.add_argument("--thread", help="Filter by related thread id.")
    eval_scorecard_parser.add_argument("--evaluator", help="Filter evaluations by evaluator.")
    eval_scorecard_parser.set_defaults(func=handlers['cmd_eval_scorecard'])

    eval_registry_parser = eval_subparsers.add_parser("registry", help="Write and inspect the whole-system fitness test registry.")
    eval_registry_parser.add_argument("--full", action="store_true", help="Print layer commands as well as layer names.")
    eval_registry_parser.add_argument("--json", action="store_true", help="Print the registry as JSON.")
    eval_registry_parser.set_defaults(func=handlers['cmd_eval_registry'])

    eval_whole_system_parser = eval_subparsers.add_parser("whole-system", help="Run the bounded whole-system fitness checkup.")
    eval_whole_system_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime artifacts where available.")
    eval_whole_system_parser.add_argument("--full", action="store_true", help="Print every check instead of only failing checks.")
    eval_whole_system_parser.add_argument("--json", action="store_true", help="Print the full normalized result as JSON.")
    eval_whole_system_parser.add_argument("--no-save", action="store_true", help="Do not write latest/history artifacts or gap records.")
    eval_whole_system_parser.set_defaults(func=handlers['cmd_eval_whole_system'])

    eval_gaps_parser = eval_subparsers.add_parser("gaps", help="Inspect whole-system evaluation gaps and missing components.")
    eval_gaps_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime gap records where available.")
    eval_gaps_parser.add_argument("--full", action="store_true", help="Print component advice and repair commands for each gap.")
    eval_gaps_parser.add_argument("--json", action="store_true", help="Print the gap summary as JSON.")
    eval_gaps_parser.add_argument("--limit", type=int, default=20, help="Max gap records to print when not using --full.")
    eval_gaps_parser.add_argument("--days", type=int, help="Filter to recent days.")
    eval_gaps_parser.add_argument("--status", choices=sorted(settings['WHOLE_SYSTEM_CHECK_STATUSES']), help="Filter by gap status.")
    eval_gaps_parser.add_argument("--component", choices=sorted(settings['WHOLE_SYSTEM_MISSING_COMPONENTS']), help="Filter by missing component.")
    eval_gaps_parser.add_argument("--owner", choices=sorted(settings['WHOLE_SYSTEM_GAP_OWNERS']), help="Filter by owner.")
    eval_gaps_parser.add_argument("--all", action="store_true", help="Include older gap history instead of only the latest eval run.")
    eval_gaps_parser.set_defaults(func=handlers['cmd_eval_gaps'])

    eval_roadmap_parser = eval_subparsers.add_parser(
        "roadmap",
        help="Summarize roadmap priority, backlog pressure, duplicate work, and current evidence gaps.",
    )
    eval_roadmap_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime artifacts where available.")
    eval_roadmap_parser.add_argument("--full", action="store_true", help="Print duplicate groups, superseded candidates, and source docs.")
    eval_roadmap_parser.add_argument("--json", action="store_true", help="Print the roadmap report as JSON.")
    eval_roadmap_parser.add_argument("--limit", type=int, default=8, help="Max warnings or duplicate groups to print.")
    eval_roadmap_parser.set_defaults(func=handlers['cmd_eval_roadmap'])

    eval_roadmap_cleanup_parser = eval_subparsers.add_parser(
        "roadmap-cleanup",
        help="Archive duplicate roadmap/backlog records and mark superseded eval gaps.",
    )
    eval_roadmap_cleanup_parser.add_argument("--apply", action="store_true", help="Apply the cleanup plan. Omit for dry-run.")
    eval_roadmap_cleanup_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime backlog artifacts where available.")
    eval_roadmap_cleanup_parser.add_argument("--full", action="store_true", help="Print duplicate groups and superseded candidates.")
    eval_roadmap_cleanup_parser.add_argument("--json", action="store_true", help="Print the cleanup plan and applied result as JSON.")
    eval_roadmap_cleanup_parser.add_argument("--limit", type=int, default=8, help="Max groups or records to print.")
    eval_roadmap_cleanup_parser.set_defaults(func=handlers['cmd_eval_roadmap_cleanup'])

    eval_model_suitability_parser = eval_subparsers.add_parser(
        "model-suitability",
        help="Decide whether current failures need model changes, routing repair, or runtime tuning.",
    )
    eval_model_suitability_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime artifacts where available.")
    eval_model_suitability_parser.add_argument("--full", action="store_true", help="Print lane inventory, signals, and input artifacts.")
    eval_model_suitability_parser.add_argument("--json", action="store_true", help="Print the full model suitability report as JSON.")
    eval_model_suitability_parser.add_argument("--no-save", action="store_true", help="Do not write latest/history artifacts.")
    eval_model_suitability_parser.set_defaults(func=handlers['cmd_eval_model_suitability'])

    eval_capabilities_parser = eval_subparsers.add_parser(
        "capabilities",
        help="Build Eve's capability matrix and acquisition plans.",
    )
    eval_capabilities_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime artifacts where available.")
    eval_capabilities_parser.add_argument("--full", action="store_true", help="Print each capability row.")
    eval_capabilities_parser.add_argument("--json", action="store_true", help="Print the matrix and acquisition plans as JSON.")
    eval_capabilities_parser.add_argument("--no-save", action="store_true", help="Do not write capability matrix artifacts.")
    eval_capabilities_parser.set_defaults(func=handlers['cmd_eval_capabilities'])

    eval_manual_probe_parser = eval_subparsers.add_parser(
        "manual-probe",
        help="Run or list the fresh manual/hidden probe bank against Eve's live chat path.",
    )
    eval_manual_probe_parser.add_argument("--from-bank", action="store_true", help="Run the active probe bank through `eve.py chat`.")
    eval_manual_probe_parser.add_argument("--runtime", action="store_true", help="Run probes against the synced runtime bundle.")
    eval_manual_probe_parser.add_argument("--id", action="append", help="Run only the given probe id. Can be repeated.")
    eval_manual_probe_parser.add_argument("--limit", type=int, help="Limit how many probes to list or run.")
    eval_manual_probe_parser.add_argument("--timeout", type=int, default=120, help="Timeout per probe in seconds.")
    eval_manual_probe_parser.add_argument("--include-inactive", action="store_true", help="Include inactive bank records.")
    eval_manual_probe_parser.add_argument("--full", action="store_true", help="Print answer snippets and prior manual evidence.")
    eval_manual_probe_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    eval_manual_probe_parser.add_argument("--no-save", action="store_true", help="Do not write manual/hidden probe artifacts.")
    eval_manual_probe_parser.add_argument("--user-scores", action="store_true", help="List user-recorded manual-probe scores that gate autonomy.")
    eval_manual_probe_parser.add_argument("--record-user-result", metavar="JSON", help="Append a user-scored manual-probe JSON file to manual_probe_manual_scores.jsonl; use '-' for stdin.")
    eval_manual_probe_parser.set_defaults(func=handlers['cmd_eval_manual_probe'])

    eval_hidden_summary_parser = eval_subparsers.add_parser(
        "hidden-summary",
        help="Record a sanitized third-party hidden-evaluation aggregate without private prompts, rubrics, or responses.",
    )
    eval_hidden_summary_parser.add_argument(
        "--record",
        required=True,
        metavar="JSON",
        help="Read the sanitized aggregate JSON from this path; use '-' for stdin.",
    )
    eval_hidden_summary_parser.add_argument("--json", action="store_true", help="Print the stored sanitized record as JSON.")
    eval_hidden_summary_parser.set_defaults(func=handlers['cmd_eval_hidden_summary'])

    eval_hidden_governance_parser = eval_subparsers.add_parser(
        "hidden-governance",
        help="Audit hidden probe privacy boundaries and redact Eve-readable hidden probe details.",
    )
    eval_hidden_governance_parser.add_argument(
        "--repair-eve-readable",
        action="store_true",
        help="Redact legacy hidden prompt/rubric/response details from Eve-readable artifacts.",
    )
    eval_hidden_governance_parser.add_argument("--full", action="store_true", help="Print checked files.")
    eval_hidden_governance_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    eval_hidden_governance_parser.add_argument("--no-save", action="store_true", help="Do not write the governance report artifact.")
    eval_hidden_governance_parser.set_defaults(func=handlers['cmd_eval_hidden_governance'])

    eval_safety_drills_parser = eval_subparsers.add_parser(
        "safety-drills",
        help="Build rollback and safe-mode drill readiness evidence.",
    )
    eval_safety_drills_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime artifacts where available.")
    eval_safety_drills_parser.add_argument("--full", action="store_true", help="Print every drill with rollback and safe-mode paths.")
    eval_safety_drills_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    eval_safety_drills_parser.add_argument("--no-save", action="store_true", help="Do not write safety-drill latest/history artifacts.")
    eval_safety_drills_parser.set_defaults(func=handlers['cmd_eval_safety_drills'])

    eval_social_parser = eval_subparsers.add_parser(
        "social",
        help="Run the lightweight relationship/repair/anti-sycophancy probe subset.",
    )
    eval_social_parser.add_argument("--runtime", action="store_true", help="Run probes against the synced runtime bundle.")
    eval_social_parser.add_argument("--id", action="append", help="Run only the given social probe id. Can be repeated.")
    eval_social_parser.add_argument("--limit", type=int, help="Limit how many social probes to run or list.")
    eval_social_parser.add_argument("--timeout", type=int, default=120, help="Timeout per probe in seconds.")
    eval_social_parser.add_argument("--include-inactive", action="store_true", help="Include inactive social bank records.")
    eval_social_parser.add_argument("--list", action="store_true", help="List the selected social probes without running them.")
    eval_social_parser.add_argument("--full", action="store_true", help="Print answer snippets and prior manual evidence.")
    eval_social_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    eval_social_parser.add_argument("--no-save", action="store_true", help="Do not write manual/hidden probe artifacts.")
    eval_social_parser.set_defaults(func=handlers['cmd_eval_social'])

    eval_long_run_parser = eval_subparsers.add_parser(
        "long-run",
        help="Score bounded autonomy behavior over a recent time window.",
    )
    eval_long_run_parser.add_argument("--minutes", type=int, default=60, help="Recent autonomy window to inspect, in minutes.")
    eval_long_run_parser.add_argument("--hours", type=int, help="Recent autonomy window to inspect, in hours. Overrides --minutes.")
    eval_long_run_parser.add_argument("--runtime", action="store_true", help="Prefer runtime-bundle autonomy artifacts.")
    eval_long_run_parser.add_argument("--full", action="store_true", help="Print metric issues, repairs, and sample evidence.")
    eval_long_run_parser.add_argument("--json", action="store_true", help="Print raw JSON.")
    eval_long_run_parser.add_argument("--no-save", action="store_true", help="Do not write long-run fitness artifacts.")
    eval_long_run_parser.set_defaults(func=handlers['cmd_eval_long_run'])

    tracker_parser = subparsers.add_parser("tracker", help="Export Eve's roadmap, gaps, tasks, and proposals into tracker-shaped artifacts.")
    tracker_subparsers = tracker_parser.add_subparsers(dest="tracker_command", required=True)
    tracker_export_parser = tracker_subparsers.add_parser(
        "export",
        help="Write a local-first tracker export for Plane, GitHub Projects, OpenProject, or another board adapter.",
    )
    tracker_export_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime artifacts where available.")
    tracker_export_parser.add_argument("--target", choices=["local", "plane", "github", "openproject"], default="local", help="Tag the export for a future adapter target.")
    tracker_export_parser.add_argument("--full", action="store_true", help="Print next actions and verification commands for top items.")
    tracker_export_parser.add_argument("--json", action="store_true", help="Print the full tracker export as JSON.")
    tracker_export_parser.add_argument("--limit", type=int, default=20, help="Max top tracker items to print.")
    tracker_export_parser.add_argument("--no-save", action="store_true", help="Do not write .eve/tracker_export.json or .eve/tracker_items.jsonl.")
    tracker_export_parser.set_defaults(func=handlers['cmd_tracker_export'])

    tracker_sync_parser = tracker_subparsers.add_parser(
        "sync",
        help="Write a dry-run one-way sync plan for a human-facing tracker board.",
    )
    tracker_sync_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime artifacts where available.")
    tracker_sync_parser.add_argument("--target", choices=["local", "plane", "github", "openproject"], default="plane", help="Target adapter shape.")
    tracker_sync_parser.add_argument("--project", default="Eve Master Roadmap", help="External board/project name for the sync plan.")
    tracker_sync_parser.add_argument("--limit", type=int, help="Limit operations in the plan.")
    tracker_sync_parser.add_argument("--exclude-watch", action="store_true", help="Skip roadmap watch items.")
    tracker_sync_parser.add_argument("--full", action="store_true", help="Print operation keys and verification commands.")
    tracker_sync_parser.add_argument("--json", action="store_true", help="Print the full sync plan as JSON.")
    tracker_sync_parser.add_argument("--no-save", action="store_true", help="Do not write sync plan artifacts.")
    tracker_sync_parser.add_argument("--apply", action="store_true", help="Reserved for future external writes; currently refused.")
    tracker_sync_parser.set_defaults(func=handlers['cmd_tracker_sync'])

    outcome_parser = subparsers.add_parser("outcome", help="Record and inspect real-world outcomes tied to Eve's actions.")
    outcome_subparsers = outcome_parser.add_subparsers(dest="outcome_command", required=True)

    outcome_add_parser = outcome_subparsers.add_parser("add", help="Add a structured outcome signal.")
    outcome_add_parser.add_argument("--target-kind", required=True, choices=settings['FEEDBACK_TARGET_KINDS'], help="What kind of artifact produced the outcome.")
    outcome_add_parser.add_argument("--target-id", required=True, help="The id of the artifact linked to the outcome.")
    outcome_add_parser.add_argument("--thread", help="Optional related thread id.")
    outcome_add_parser.add_argument("--direction", required=True, choices=settings['OUTCOME_DIRECTIONS'], help="Whether the outcome was positive, mixed, neutral, or negative.")
    outcome_add_parser.add_argument("--outcome", required=True, help="Short label such as helped, resolved, stalled, or missed.")
    outcome_add_parser.add_argument("--summary", required=True, help="What actually happened.")
    outcome_add_parser.add_argument("--evidence", help="Optional evidence or detail.")
    outcome_add_parser.set_defaults(func=handlers['cmd_outcome_add'])

    outcome_list_parser = outcome_subparsers.add_parser("list", help="List recorded outcomes.")
    outcome_list_parser.add_argument("--limit", type=int, default=20, help="Max outcomes to print.")
    outcome_list_parser.add_argument("--days", type=int, help="Filter to recent days.")
    outcome_list_parser.add_argument("--target-kind", choices=settings['FEEDBACK_TARGET_KINDS'], help="Filter by target kind.")
    outcome_list_parser.add_argument("--target-id", help="Filter by target id.")
    outcome_list_parser.add_argument("--thread", help="Filter by related thread id.")
    outcome_list_parser.add_argument("--direction", choices=settings['OUTCOME_DIRECTIONS'], help="Filter by outcome direction.")
    outcome_list_parser.set_defaults(func=handlers['cmd_outcome_list'])

    failure_parser = subparsers.add_parser("failure", help="Cluster repeated failures and track repairs.")
    failure_subparsers = failure_parser.add_subparsers(dest="failure_command", required=True)

    failure_review_parser = failure_subparsers.add_parser("review", help="Review recent failures and update failure clusters.")
    failure_review_parser.add_argument("--days", type=int, help="Review window in days.")
    failure_review_parser.add_argument("--threshold", type=int, choices=range(1, 6), help="Score threshold for low evaluations.")
    failure_review_parser.add_argument("--max-clusters", type=int, help="Maximum number of clusters to keep from this review.")
    failure_review_parser.set_defaults(func=handlers['cmd_failure_review'])

    failure_list_parser = failure_subparsers.add_parser("list", help="List recent failure clusters.")
    failure_list_parser.add_argument("--limit", type=int, default=20, help="Max clusters to print.")
    failure_list_parser.add_argument("--days", type=int, help="Filter to recent days.")
    failure_list_parser.add_argument("--status", choices=settings['FAILURE_CLUSTER_STATUSES'], help="Filter by status.")
    failure_list_parser.add_argument("--full", action="store_true", help="Print cluster evidence too.")
    failure_list_parser.set_defaults(func=handlers['cmd_failure_list'])

    failure_update_parser = failure_subparsers.add_parser("update", help="Update a failure cluster after repair or review.")
    failure_update_parser.add_argument("id", help="Failure cluster id.")
    failure_update_parser.add_argument("--status", choices=settings['FAILURE_CLUSTER_STATUSES'], help="New status.")
    failure_update_parser.add_argument("--summary", help="Updated cluster summary.")
    failure_update_parser.add_argument("--root-cause", help="Updated root cause.")
    failure_update_parser.add_argument("--repair", help="Updated repair action.")
    failure_update_parser.add_argument("--resolution-note", help="Optional note to append to the evidence trail.")
    failure_update_parser.set_defaults(func=handlers['cmd_failure_update'])

    review_parser = subparsers.add_parser("review", help="Prepare outside review packets and store reviewer guidance.")
    review_subparsers = review_parser.add_subparsers(dest="review_command", required=True)

    review_prepare_parser = review_subparsers.add_parser("prepare", help="Prepare a review packet on disk.")
    review_prepare_parser.add_argument("--reviewer", default="Reviewer", help="Who the packet is intended for, for example Claude, Codex, or Gemini.")
    review_prepare_parser.add_argument("--kind", default="weekly", help="Short label for this review cycle.")
    review_prepare_parser.add_argument("--days", type=int, help="Review window in days.")
    review_prepare_parser.add_argument("--context", type=int, help="How many recent records to include per section.")
    review_prepare_parser.set_defaults(func=handlers['cmd_review_prepare'])

    review_request_parser = review_subparsers.add_parser("request", help="Prepare a review packet and optionally queue it through a supported bridge.")
    review_request_parser.add_argument("--reviewer", required=True, help="Reviewer name, for example Claude, Codex, or Gemini.")
    review_request_parser.add_argument("--via", choices=settings['REVIEW_REQUEST_VIAS'], help="How to hand off the packet. Defaults to Claude bridge for Claude, manual otherwise.")
    review_request_parser.add_argument("--kind", default="weekly", help="Short label for this review cycle.")
    review_request_parser.add_argument("--days", type=int, help="Review window in days.")
    review_request_parser.add_argument("--context", type=int, help="How many recent records to include per section.")
    review_request_parser.add_argument("--subject", help="Optional subject override for bridge-backed requests.")
    review_request_parser.set_defaults(func=handlers['cmd_review_request'])

    review_request_claude_parser = review_subparsers.add_parser("request-claude", help="Compatibility alias for `review request --reviewer Claude --via claude`.")
    review_request_claude_parser.add_argument("--kind", default="weekly", help="Short label for this review cycle.")
    review_request_claude_parser.add_argument("--days", type=int, help="Review window in days.")
    review_request_claude_parser.add_argument("--context", type=int, help="How many recent records to include per section.")
    review_request_claude_parser.add_argument("--subject", help="Optional subject override for the Claude bridge message.")
    review_request_claude_parser.set_defaults(func=handlers['cmd_review_request_claude'])

    review_capture_parser = review_subparsers.add_parser("capture", help="Capture a supported bridge reply as durable reviewer guidance.")
    review_capture_parser.add_argument("message_id", help="Bridge reply message id.")
    review_capture_parser.add_argument("--via", choices=["claude"], default="claude", help="Which bridge produced the reply.")
    review_capture_parser.add_argument("--reviewer", help="Optional reviewer label override.")
    review_capture_parser.add_argument("--summary", help="Optional summary override.")
    review_capture_parser.set_defaults(func=handlers['cmd_review_capture'])

    review_capture_claude_parser = review_subparsers.add_parser("capture-claude", help="Compatibility alias for `review capture --via claude`.")
    review_capture_claude_parser.add_argument("message_id", help="Claude reply message id.")
    review_capture_claude_parser.add_argument("--summary", help="Optional summary override.")
    review_capture_claude_parser.set_defaults(func=handlers['cmd_review_capture_claude'])

    review_add_parser = review_subparsers.add_parser("add", help="Store reviewer guidance manually.")
    review_add_parser.add_argument("--reviewer", required=True, help="Reviewer name, for example Claude or Codex.")
    review_add_parser.add_argument("--packet-id", help="Optional linked review packet id.")
    review_add_parser.add_argument("--summary", help="Optional summary override.")
    review_add_parser.add_argument("--body", help="Review body text.")
    review_add_parser.add_argument("--body-file", help="Path to a file containing the review body.")
    review_add_parser.add_argument("--status", choices=settings['REVIEW_NOTE_STATUSES'], default="active", help="Initial review note status.")
    review_add_parser.set_defaults(func=handlers['cmd_review_add'])

    review_list_parser = review_subparsers.add_parser("list", help="List saved reviewer notes.")
    review_list_parser.add_argument("--limit", type=int, default=20, help="Max review notes to print.")
    review_list_parser.add_argument("--days", type=int, help="Filter to recent days.")
    review_list_parser.add_argument("--reviewer", help="Filter by reviewer.")
    review_list_parser.add_argument("--packet-id", help="Filter by linked packet id.")
    review_list_parser.add_argument("--status", choices=settings['REVIEW_NOTE_STATUSES'], help="Filter by note status.")
    review_list_parser.add_argument("--full", action="store_true", help="Print full review bodies.")
    review_list_parser.set_defaults(func=handlers['cmd_review_list'])

    review_update_parser = review_subparsers.add_parser("update", help="Update a stored review note.")
    review_update_parser.add_argument("id", help="Review note id.")
    review_update_parser.add_argument("--status", choices=settings['REVIEW_NOTE_STATUSES'], help="New review note status.")
    review_update_parser.add_argument("--summary", help="Updated summary.")
    review_update_parser.set_defaults(func=handlers['cmd_review_update'])

    pattern_parser = subparsers.add_parser("pattern", help="Inspect or refresh Eve's durable success-pattern memory.")
    pattern_subparsers = pattern_parser.add_subparsers(dest="pattern_command", required=True)

    pattern_refresh_parser = pattern_subparsers.add_parser("refresh", help="Harvest durable success patterns from strong evidence already on disk.")
    pattern_refresh_parser.add_argument("--days", type=int, default=365, help="Only inspect source evidence from recent days.")
    pattern_refresh_parser.add_argument("--limit", type=int, default=10, help="How many changed patterns to print.")
    pattern_refresh_parser.set_defaults(func=handlers['cmd_pattern_refresh'])

    pattern_list_parser = pattern_subparsers.add_parser("list", help="List stored success patterns.")
    pattern_list_parser.add_argument("--limit", type=int, default=20, help="Max patterns to print.")
    pattern_list_parser.add_argument("--days", type=int, help="Filter to recent days.")
    pattern_list_parser.add_argument("--status", choices=settings['SUCCESS_PATTERN_STATUSES'], default="active", help="Filter by status.")
    pattern_list_parser.add_argument("--full", action="store_true", help="Print fuller pattern evidence.")
    pattern_list_parser.set_defaults(func=handlers['cmd_pattern_list'])

    pattern_update_parser = pattern_subparsers.add_parser("update", help="Update one stored success pattern.")
    pattern_update_parser.add_argument("id", help="Success pattern id.")
    pattern_update_parser.add_argument("--status", choices=settings['SUCCESS_PATTERN_STATUSES'], help="New pattern status.")
    pattern_update_parser.add_argument("--title", help="Updated title.")
    pattern_update_parser.add_argument("--summary", help="Updated summary.")
    pattern_update_parser.add_argument("--situation", help="Updated situation text.")
    pattern_update_parser.add_argument("--good-move", help="Updated core move text.")
    pattern_update_parser.add_argument("--why", help="Updated why-it-worked text.")
    pattern_update_parser.set_defaults(func=handlers['cmd_pattern_update'])

    memory_parser = subparsers.add_parser("memory", help="Inspect the experimental embedding-based memory retrieval path.")
    memory_subparsers = memory_parser.add_subparsers(dest="memory_command", required=True)

    memory_status_parser = memory_subparsers.add_parser("status", help="Show experimental memory retrieval status.")
    memory_status_parser.set_defaults(func=handlers['cmd_memory_status'])

    memory_refresh_parser = memory_subparsers.add_parser("refresh", help="Rebuild experimental memory notes and the embedding index.")
    memory_refresh_parser.add_argument("--force", action="store_true", help="Force a rebuild even if the notes hash did not change.")
    memory_refresh_parser.set_defaults(func=handlers['cmd_memory_refresh'])

    memory_query_parser = memory_subparsers.add_parser("query", help="Query the experimental embedding memory index.")
    memory_query_parser.add_argument("query", help="Text to retrieve against Eve's durable memory notes.")
    memory_query_parser.add_argument("--limit", type=int, default=3, help="How many memory matches to print.")
    memory_query_parser.add_argument("--force-refresh", action="store_true", help="Rebuild notes and index before querying.")
    memory_query_parser.set_defaults(func=handlers['cmd_memory_query'])

    specialists_parser = subparsers.add_parser(
        "specialists",
        help="Inspect non-lane specialist substrates that support Eve's five logical faculties.",
    )
    specialists_subparsers = specialists_parser.add_subparsers(dest="specialists_command", required=True)

    specialists_status_parser = specialists_subparsers.add_parser(
        "status",
        help="Show memory, coding/self-repair, and frontier/API lab substrate status.",
    )
    specialists_status_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime artifacts where available.")
    specialists_status_parser.add_argument("--full", action="store_true", help="Print target states, next maturation, and commands.")
    specialists_status_parser.add_argument("--json", action="store_true", help="Print the substrate registry as JSON.")
    specialists_status_parser.set_defaults(func=handlers['cmd_specialists_status'])

    hermes_parser = subparsers.add_parser(
        "hermes",
        help="Inspect Eve's proposal-only Hermes learning organ profile.",
    )
    hermes_subparsers = hermes_parser.add_subparsers(dest="hermes_command", required=True)

    hermes_status_parser = hermes_subparsers.add_parser(
        "status",
        help="Show Hermes install/profile status and Eve governance boundaries.",
    )
    hermes_status_parser.add_argument("--timeout", type=int, default=10, help="Command probe timeout in seconds.")
    hermes_status_parser.add_argument("--runtime", action="store_true", help="Run the observation from Eve's installed runtime bundle when the daemon is live.")
    hermes_status_parser.add_argument("--full", action="store_true", help="Include source/config details.")
    hermes_status_parser.add_argument("--json", action="store_true", help="Print machine-readable status JSON.")
    hermes_status_parser.set_defaults(func=handlers['cmd_hermes_status'])

    hermes_inventory_parser = hermes_subparsers.add_parser(
        "inventory",
        help="Snapshot Hermes tools, skills, plugins, memory, MCP, cron, gateway, and readiness into Eve evidence.",
    )
    hermes_inventory_parser.add_argument("--timeout", type=int, default=25, help="Per-command inventory timeout in seconds.")
    hermes_inventory_parser.add_argument("--runtime", action="store_true", help="Refresh from Eve's installed runtime bundle instead of the source checkout.")
    hermes_inventory_parser.add_argument("--refresh", action="store_true", help="Refresh the inventory now; kept explicit for operator readability.")
    hermes_inventory_parser.add_argument("--no-save", action="store_true", help="Print inventory without writing .eve/hermes_capability_inventory.json.")
    hermes_inventory_parser.add_argument("--full", action="store_true", help="Include roles, next tests, and command previews.")
    hermes_inventory_parser.add_argument("--json", action="store_true", help="Print raw inventory JSON.")
    hermes_inventory_parser.set_defaults(func=handlers['cmd_hermes_inventory'])

    hermes_feature_policy_parser = hermes_subparsers.add_parser(
        "feature-policy",
        help="Show Eve's adoption policy for Hermes features without enabling new authority.",
    )
    hermes_feature_policy_parser.add_argument("--timeout", type=int, default=25, help="Inventory refresh timeout in seconds.")
    hermes_feature_policy_parser.add_argument("--runtime", action="store_true", help="Build the policy from Eve's installed runtime bundle when the daemon is live.")
    hermes_feature_policy_parser.add_argument("--refresh-inventory", action="store_true", help="Refresh Hermes inventory before building the policy.")
    hermes_feature_policy_parser.add_argument("--no-save", action="store_true", help="Print policy without writing .eve/hermes_feature_policy.json.")
    hermes_feature_policy_parser.add_argument("--full", action="store_true", help="Include per-feature gates and recommendations.")
    hermes_feature_policy_parser.add_argument("--json", action="store_true", help="Print raw feature policy JSON.")
    hermes_feature_policy_parser.set_defaults(func=handlers['cmd_hermes_feature_policy'])

    hermes_skill_admission_parser = hermes_subparsers.add_parser(
        "skill-admission",
        help="Create a governed SkillPatchProposal preflight for a Hermes skill/plugin candidate without enabling it.",
    )
    hermes_skill_admission_parser.add_argument("--skill", required=True, help="Hermes skill/plugin capability name.")
    hermes_skill_admission_parser.add_argument("--purpose", required=True, help="Bounded Eve purpose for the skill.")
    hermes_skill_admission_parser.add_argument(
        "--permission-class",
        choices=sorted(settings['HERMES_SKILL_PERMISSION_RISK']),
        default="read_only",
        help="Highest permission class the skill would need.",
    )
    hermes_skill_admission_parser.add_argument("--source", default="hermes", help="Proposal source label.")
    hermes_skill_admission_parser.add_argument("--skill-path", default="", help="Optional local skill path or upstream reference.")
    hermes_skill_admission_parser.add_argument("--test", action="append", default=[], help="Required smoke/eval before enablement. Repeatable.")
    hermes_skill_admission_parser.add_argument("--evidence", action="append", default=[], help="Evidence supporting the candidate. Repeatable.")
    hermes_skill_admission_parser.add_argument("--filesystem-boundary", default="", help="Allowed filesystem boundary, if any.")
    hermes_skill_admission_parser.add_argument("--network-boundary", default="", help="Allowed network boundary, if any.")
    hermes_skill_admission_parser.add_argument("--credential-boundary", default="", help="Allowed credential boundary, if any.")
    hermes_skill_admission_parser.add_argument("--enqueue", action="store_true", help="Queue the reviewed SkillPatchProposal for governance review.")
    hermes_skill_admission_parser.add_argument("--record", action="store_true", help="Append an audit record even when not queueing.")
    hermes_skill_admission_parser.add_argument("--full", action="store_true", help="Include payload and findings.")
    hermes_skill_admission_parser.add_argument("--json", action="store_true", help="Print raw admission JSON.")
    hermes_skill_admission_parser.set_defaults(func=handlers['cmd_hermes_skill_admission'])

    hermes_doctor_parser = hermes_subparsers.add_parser(
        "doctor",
        help="Run Hermes doctor using the dedicated evelearning profile.",
    )
    hermes_doctor_parser.add_argument("--timeout", type=int, default=45, help="Doctor timeout in seconds.")
    hermes_doctor_parser.set_defaults(func=handlers['cmd_hermes_doctor'])

    hermes_smoke_parser = hermes_subparsers.add_parser(
        "smoke",
        help="Run a governed Hermes trace-to-proposal smoke and record an artifact.",
    )
    hermes_smoke_parser.add_argument("--trace-file", default="", help="Trace JSON file to send to Hermes.")
    hermes_smoke_parser.add_argument("--trace-json", default="", help="Trace JSON object to send to Hermes.")
    hermes_smoke_parser.add_argument("--timeout", type=int, default=120, help="Hermes chat timeout in seconds.")
    hermes_smoke_parser.add_argument(
        "--ingest",
        action="store_true",
        help="Store reviewed proposals in the governance queue; omitted means dry-run review only.",
    )
    hermes_smoke_parser.add_argument(
        "--allow-non-local",
        action="store_true",
        help="Permit a non-local Hermes model endpoint only after explicit provider/model/data-boundary approval.",
    )
    hermes_smoke_parser.add_argument(
        "--repair-json",
        action="store_true",
        help="Allow an auditable repair of one outer markdown fence/surrounding text before proposal review.",
    )
    hermes_smoke_parser.add_argument(
        "--allow-repaired-ingest",
        action="store_true",
        help="Permit --ingest after --repair-json only for an explicit supervised exception.",
    )
    hermes_smoke_parser.add_argument(
        "--constrained-json",
        action="store_true",
        default=True,
        help="Use Hermes AIAgent with toolsets disabled and response_format=json_schema for strict proposal JSON (default).",
    )
    hermes_smoke_parser.add_argument(
        "--no-constrained-json",
        dest="constrained_json",
        action="store_false",
        help="Use ordinary Hermes CLI mode; diagnostic only because profile toolsets may be enabled.",
    )
    hermes_smoke_parser.add_argument(
        "--local-64k-lab",
        action="store_true",
        help="Run smoke against Eve's on-demand local Qwen3.5-2B 64K Hermes lab endpoint.",
    )
    hermes_smoke_parser.add_argument(
        "--keep-local-lab",
        action="store_true",
        help="Leave a smoke-started local 64K lab endpoint running after the smoke.",
    )
    hermes_smoke_parser.add_argument("--prompt-only", action="store_true", help="Print the exact smoke prompt without running Hermes.")
    hermes_smoke_parser.add_argument("--full", action="store_true", help="Include model and raw-output previews.")
    hermes_smoke_parser.add_argument("--json", action="store_true", help="Print raw smoke artifact JSON.")
    hermes_smoke_parser.set_defaults(func=handlers['cmd_hermes_smoke'])

    hermes_trace_parser = hermes_subparsers.add_parser(
        "trace-propose",
        help="Build a real post-task Eve trace and run it through the Hermes proposal gate.",
    )
    hermes_trace_parser.add_argument("--task-id", default="", help="Optional task id for the generated trace.")
    hermes_trace_parser.add_argument("--limit", type=int, default=6, help="Recent records per source to include.")
    hermes_trace_parser.add_argument("--runtime", action="store_true", help="Prefer live runtime ledgers when available.")
    hermes_trace_parser.add_argument("--trace-only", action="store_true", help="Print the generated trace without running Hermes.")
    hermes_trace_parser.add_argument("--timeout", type=int, default=180, help="Hermes timeout in seconds.")
    hermes_trace_parser.add_argument("--ingest", action="store_true", help="Store reviewed proposals if Hermes emits strict JSON.")
    hermes_trace_parser.add_argument(
        "--constrained-json",
        action="store_true",
        default=True,
        help="Use Hermes AIAgent with toolsets disabled and response_format=json_schema for strict proposal JSON.",
    )
    hermes_trace_parser.add_argument(
        "--no-constrained-json",
        dest="constrained_json",
        action="store_false",
        help="Use ordinary Hermes CLI output mode; mainly for diagnostics.",
    )
    hermes_trace_parser.add_argument(
        "--local-64k-lab",
        action="store_true",
        default=True,
        help="Run against Eve's on-demand local Qwen3.5-2B 64K Hermes lab endpoint.",
    )
    hermes_trace_parser.add_argument(
        "--no-local-64k-lab",
        dest="local_64k_lab",
        action="store_false",
        help="Use the configured Hermes profile instead of the local 64K lab.",
    )
    hermes_trace_parser.add_argument("--keep-local-lab", action="store_true", help="Leave the local 64K lab server running after the run.")
    hermes_trace_parser.add_argument("--full", action="store_true", help="Include model/stdout/stderr details.")
    hermes_trace_parser.add_argument("--json", action="store_true", help="Print raw JSON smoke record.")
    hermes_trace_parser.set_defaults(func=handlers['cmd_hermes_trace_propose'])

    hermes_eval_parser = hermes_subparsers.add_parser(
        "eval",
        help="Run repeated Hermes smoke trials and summarize strict-vs-repaired JSON reliability.",
    )
    hermes_eval_parser.add_argument("--trials", type=int, default=3, help="Number of smoke trials to run, 1-12.")
    hermes_eval_parser.add_argument("--timeout", type=int, default=180, help="Timeout per Hermes trial in seconds.")
    hermes_eval_parser.add_argument(
        "--no-local-64k-lab",
        action="store_true",
        help="Use the configured Hermes profile instead of Eve's on-demand local 64K lab.",
    )
    hermes_eval_parser.add_argument(
        "--no-repair-json",
        action="store_true",
        help="Do not allow markdown-fence JSON repair during eval trials.",
    )
    hermes_eval_parser.add_argument(
        "--constrained-json",
        action="store_true",
        default=True,
        help="Run eval trials through the strict tool-less Hermes AIAgent JSON-object adapter (default).",
    )
    hermes_eval_parser.add_argument(
        "--no-constrained-json",
        dest="constrained_json",
        action="store_false",
        help="Use ordinary Hermes CLI mode for diagnostic comparison only.",
    )
    hermes_eval_parser.add_argument("--full", action="store_true", help="Include per-trial artifact detail.")
    hermes_eval_parser.add_argument("--json", action="store_true", help="Print raw eval artifact JSON.")
    hermes_eval_parser.set_defaults(func=handlers['cmd_hermes_eval'])

    hermes_lab_status_parser = hermes_subparsers.add_parser(
        "lab-status",
        help="Inspect the on-demand local 64K Hermes lab endpoint.",
    )
    hermes_lab_status_parser.add_argument("--timeout", type=int, default=2, help="Endpoint probe timeout in seconds.")
    hermes_lab_status_parser.add_argument("--json", action="store_true", help="Print raw lab status JSON.")
    hermes_lab_status_parser.set_defaults(func=handlers['cmd_hermes_lab_status'])

    hermes_lab_start_parser = hermes_subparsers.add_parser(
        "lab-start",
        help="Start the on-demand local Qwen3.5-2B 64K Hermes lab endpoint.",
    )
    hermes_lab_start_parser.add_argument("--timeout", type=int, default=90, help="Startup timeout in seconds.")
    hermes_lab_start_parser.add_argument("--json", action="store_true", help="Print raw lab start JSON.")
    hermes_lab_start_parser.set_defaults(func=handlers['cmd_hermes_lab_start'])

    hermes_lab_stop_parser = hermes_subparsers.add_parser(
        "lab-stop",
        help="Stop the on-demand local 64K Hermes lab endpoint.",
    )
    hermes_lab_stop_parser.add_argument("--timeout", type=int, default=10, help="Shutdown timeout in seconds.")
    hermes_lab_stop_parser.add_argument("--json", action="store_true", help="Print raw lab stop JSON.")
    hermes_lab_stop_parser.set_defaults(func=handlers['cmd_hermes_lab_stop'])

    router_parser = subparsers.add_parser("router", help="Inspect the experimental small-model prompt router.")
    router_subparsers = router_parser.add_subparsers(dest="router_command", required=True)

    router_status_parser = router_subparsers.add_parser("status", help="Show experimental prompt router status.")
    router_status_parser.set_defaults(func=handlers['cmd_router_status'])

    router_contracts_parser = router_subparsers.add_parser("contracts", help="Show Eve's declarative route contracts.")
    router_contracts_parser.add_argument("--json", action="store_true", help="Print raw route contract JSON.")
    router_contracts_parser.add_argument("--full", action="store_true", help="Print match and anti-contract detail.")
    router_contracts_parser.set_defaults(func=handlers['cmd_router_contracts'])

    router_probe_parser = router_subparsers.add_parser("probe", help="Classify one turn through the experimental prompt router.")
    router_probe_parser.add_argument("message", help="User turn to classify.")
    router_probe_parser.set_defaults(func=handlers['cmd_router_probe'])

    router_replay_parser = router_subparsers.add_parser("replay", help="Replay public Eve route-contract eval cases.")
    router_replay_parser.add_argument("--limit", type=int, help="Limit number of public replay cases.")
    router_replay_parser.add_argument("--record", action="store_true", help="Write replay evidence and log uncertainty on failures.")
    router_replay_parser.add_argument("--json", action="store_true", help="Print replay report JSON.")
    router_replay_parser.add_argument("--full", action="store_true", help="Print per-case errors.")
    router_replay_parser.set_defaults(func=handlers['cmd_router_replay'])

    uncertainty_parser = subparsers.add_parser("uncertainty", help="Inspect the turns where Eve had to infer more than she could directly read.")
    uncertainty_subparsers = uncertainty_parser.add_subparsers(dest="uncertainty_command", required=True)

    uncertainty_list_parser = uncertainty_subparsers.add_parser("list", help="List recent uncertainty records.")
    uncertainty_list_parser.add_argument("--limit", type=int, default=20, help="Max records to print.")
    uncertainty_list_parser.add_argument("--days", type=int, help="Filter to recent days.")
    uncertainty_list_parser.add_argument("--status", choices=settings['UNCERTAINTY_RECORD_STATUSES'], help="Filter by record status.")
    uncertainty_list_parser.add_argument("--full", action="store_true", help="Print fuller routing and signal detail.")
    uncertainty_list_parser.set_defaults(func=handlers['cmd_uncertainty_list'])

    uncertainty_review_parser = uncertainty_subparsers.add_parser("review", help="Refresh linked feedback on recent uncertainty records.")
    uncertainty_review_parser.add_argument("--days", type=int, default=30, help="Review window in days.")
    uncertainty_review_parser.set_defaults(func=handlers['cmd_uncertainty_review'])

    judgment_parser = subparsers.add_parser("judgment", help="Inspect the situations where Eve had to make a real judgment call.")
    judgment_subparsers = judgment_parser.add_subparsers(dest="judgment_command", required=True)

    judgment_list_parser = judgment_subparsers.add_parser("list", help="List recent judgment-call records.")
    judgment_list_parser.add_argument("--limit", type=int, default=20, help="Max records to print.")
    judgment_list_parser.add_argument("--days", type=int, help="Filter to recent days.")
    judgment_list_parser.add_argument("--status", choices=settings['JUDGMENT_CALL_STATUSES'], help="Filter by record status.")
    judgment_list_parser.add_argument("--full", action="store_true", help="Print alternatives, risks, and linked uncertainty ids.")
    judgment_list_parser.set_defaults(func=handlers['cmd_judgment_list'])

    judgment_review_parser = judgment_subparsers.add_parser("review", help="Refresh linked feedback on recent judgment-call records.")
    judgment_review_parser.add_argument("--days", type=int, default=30, help="Review window in days.")
    judgment_review_parser.set_defaults(func=handlers['cmd_judgment_review'])

    openclaw_parser = subparsers.add_parser("openclaw", help="Inspect and run Eve's integrated OpenClaw self-repair lane.")
    openclaw_subparsers = openclaw_parser.add_subparsers(dest="openclaw_command", required=True)

    openclaw_status_parser = openclaw_subparsers.add_parser("status", help="Show integrated OpenClaw sidecar status.")
    openclaw_status_parser.add_argument("--runtime", action="store_true", help="Run the observation from Eve's installed runtime bundle when the daemon is live.")
    openclaw_status_parser.add_argument("--no-gateway-probe", action="store_true", help="Skip the live OpenClaw gateway status subprocess.")
    openclaw_status_parser.add_argument("--no-memory-probe", action="store_true", help="Skip the deep OpenClaw memory status subprocess.")
    openclaw_status_parser.add_argument("--full", action="store_true", help="Include observation-authority and non-secret profile details.")
    openclaw_status_parser.add_argument("--json", action="store_true", help="Print the status as JSON.")
    openclaw_status_parser.set_defaults(func=handlers['cmd_openclaw_status'])

    openclaw_install_parser = openclaw_subparsers.add_parser("install", help="Install or refresh the integrated OpenClaw sidecar profile.")
    openclaw_install_parser.add_argument("--no-daemon", action="store_true", help="Do not install/start the OpenClaw gateway daemon.")
    openclaw_install_parser.set_defaults(func=handlers['cmd_openclaw_install'])

    openclaw_sync_parser = openclaw_subparsers.add_parser("sync", help="Refresh Eve state into the OpenClaw workspace.")
    openclaw_sync_parser.add_argument("--append-memory", action="store_true", help="Append a compact daily OpenClaw memory note.")
    openclaw_sync_parser.add_argument("--no-memory", action="store_true", help="Compatibility flag; routine sync does not append memory by default.")
    openclaw_sync_parser.set_defaults(func=handlers['cmd_openclaw_sync'])

    openclaw_repair_parser = openclaw_subparsers.add_parser("repair", help="Run one bounded integrated OpenClaw repair turn.")
    openclaw_repair_parser.add_argument("--message", help="Override the repair prompt.")
    openclaw_repair_parser.add_argument("--timeout", type=int, help="Override the repair timeout in seconds.")
    openclaw_repair_parser.add_argument("--skip-sync", action="store_true", help="Skip the pre-repair sync step.")
    openclaw_repair_parser.add_argument("--diagnose-only", action="store_true", help="Run a diagnosis-only turn instead of the default repair prompt.")
    openclaw_repair_parser.add_argument("--json", action="store_true", help="Print the full repair payload as JSON.")
    openclaw_repair_parser.set_defaults(func=handlers['cmd_openclaw_repair'])

    openclaw_action_parser = openclaw_subparsers.add_parser(
        "action",
        help="Route an Eve intention through an allowlisted OpenClaw body action and record evidence.",
    )
    openclaw_action_parser.add_argument("--intent", help="Natural-language intention for Eve to route through OpenClaw.")
    openclaw_action_parser.add_argument(
        "--action",
        choices=eve_openclaw_body.openclaw_router_action_ids(),
        help="Explicit allowlisted OpenClaw action to run instead of inferring from --intent.",
    )
    openclaw_action_parser.add_argument("--include-sessions", action="store_true", help="Include bounded session activity when running activity_ingest.")
    openclaw_action_parser.add_argument("--dry-run", action="store_true", help="Only build the plan; do not execute or write evidence.")
    openclaw_action_parser.add_argument("--timeout", type=int, help="Timeout in seconds for OpenClaw command probes.")
    openclaw_action_parser.add_argument("--full", action="store_true", help="Print boundary gate, writes, evidence ids, and issues.")
    openclaw_action_parser.add_argument("--json", action="store_true", help="Print the full routed action result as JSON.")
    openclaw_action_parser.set_defaults(func=handlers['cmd_openclaw_action'])

    openclaw_routines_parser = openclaw_subparsers.add_parser(
        "routines",
        help="Run due OpenClaw body-bus routines through the action router.",
    )
    openclaw_routines_parser.add_argument("--force", action="store_true", help="Run all routines regardless of interval.")
    openclaw_routines_parser.add_argument("--dry-run", action="store_true", help="Plan routines without changing their due state.")
    openclaw_routines_parser.add_argument("--record-skips", action="store_true", help="Record not-due routines as no-op routine events.")
    openclaw_routines_parser.add_argument("--limit", type=int, help="Only evaluate the first N routines.")
    openclaw_routines_parser.add_argument("--timeout", type=int, help="Timeout in seconds for OpenClaw command probes.")
    openclaw_routines_parser.add_argument("--full", action="store_true", help="Print router and evidence ids for routine events.")
    openclaw_routines_parser.add_argument("--json", action="store_true", help="Print the full routine result as JSON.")
    openclaw_routines_parser.set_defaults(func=handlers['cmd_openclaw_routines'])

    openclaw_worker_parser = openclaw_subparsers.add_parser(
        "worker",
        help="Plan, run, list, and audit bounded short-lived OpenClaw workers.",
    )
    openclaw_worker_subparsers = openclaw_worker_parser.add_subparsers(dest="worker_command", required=True)
    openclaw_worker_kinds = sorted(handlers['openclaw_worker_registry']().keys())

    openclaw_worker_plan_parser = openclaw_worker_subparsers.add_parser(
        "plan",
        help="Plan a bounded OpenClaw worker and record plan evidence.",
    )
    openclaw_worker_plan_parser.add_argument("--kind", choices=openclaw_worker_kinds, required=True, help="Worker kind to plan.")
    openclaw_worker_plan_parser.add_argument("--parent-intention", required=True, help="Parent Eve intention that owns this worker.")
    openclaw_worker_plan_parser.add_argument("--prompt", required=True, help="Bounded worker task prompt.")
    openclaw_worker_plan_parser.add_argument("--timeout", type=int, default=120, help="Worker timeout in seconds.")
    openclaw_worker_plan_parser.add_argument("--json", action="store_true", help="Print the worker plan/event as JSON.")
    openclaw_worker_plan_parser.set_defaults(func=handlers['cmd_openclaw_worker_plan'])

    openclaw_worker_run_parser = openclaw_worker_subparsers.add_parser(
        "run",
        help="Run a bounded OpenClaw worker or dry-run the plan.",
    )
    openclaw_worker_run_parser.add_argument("--kind", choices=openclaw_worker_kinds, required=True, help="Worker kind to run.")
    openclaw_worker_run_parser.add_argument("--parent-intention", required=True, help="Parent Eve intention that owns this worker.")
    openclaw_worker_run_parser.add_argument("--prompt", required=True, help="Bounded worker task prompt.")
    openclaw_worker_run_parser.add_argument("--timeout", type=int, default=120, help="Worker timeout in seconds.")
    openclaw_worker_run_parser.add_argument("--dry-run", action="store_true", help="Record the plan without invoking OpenClaw agent.")
    openclaw_worker_run_parser.add_argument("--full", action="store_true", help="Print parent, session, and permission details.")
    openclaw_worker_run_parser.add_argument("--json", action="store_true", help="Print the worker result as JSON.")
    openclaw_worker_run_parser.set_defaults(func=handlers['cmd_openclaw_worker_run'])

    openclaw_worker_list_parser = openclaw_worker_subparsers.add_parser(
        "list",
        help="List recent bounded OpenClaw worker evidence.",
    )
    openclaw_worker_list_parser.add_argument("--limit", type=int, default=20, help="Maximum worker events to show.")
    openclaw_worker_list_parser.add_argument("--runtime", action="store_true", help="Prefer runtime worker evidence.")
    openclaw_worker_list_parser.add_argument("--full", action="store_true", help="Print parent, session, and permission details.")
    openclaw_worker_list_parser.add_argument("--json", action="store_true", help="Print worker events as JSON.")
    openclaw_worker_list_parser.set_defaults(func=handlers['cmd_openclaw_worker_list'])

    openclaw_worker_audit_parser = openclaw_worker_subparsers.add_parser(
        "audit",
        help="Audit bounded OpenClaw worker evidence and OpenClaw task health.",
    )
    openclaw_worker_audit_parser.add_argument("--limit", type=int, default=20, help="Maximum worker events to inspect.")
    openclaw_worker_audit_parser.add_argument("--runtime", action="store_true", help="Prefer runtime worker evidence.")
    openclaw_worker_audit_parser.add_argument("--timeout", type=int, default=30, help="OpenClaw task-audit timeout in seconds.")
    openclaw_worker_audit_parser.add_argument("--full", action="store_true", help="Print audit parent, session, and permission details.")
    openclaw_worker_audit_parser.add_argument("--json", action="store_true", help="Print the worker audit event as JSON.")
    openclaw_worker_audit_parser.set_defaults(func=handlers['cmd_openclaw_worker_audit'])

    openclaw_model_smoke_parser = openclaw_subparsers.add_parser(
        "model-smoke",
        help="Run a one-shot OpenClaw model probe and normalize runtime-error text before trusting it.",
    )
    openclaw_model_smoke_parser.add_argument("--model", required=True, help="OpenClaw provider/model id, such as llamacpp/eve-fast.")
    openclaw_model_smoke_parser.add_argument("--prompt", default="Return exactly OK.", help="Prompt text for the smoke test.")
    openclaw_model_smoke_parser.add_argument("--expect-contains", default="OK", help="Expected substring in the model output. Empty disables this check.")
    openclaw_model_smoke_parser.add_argument("--gateway", action="store_true", help="Force gateway execution instead of local execution.")
    openclaw_model_smoke_parser.add_argument("--timeout", type=int, default=90, help="OpenClaw command timeout in seconds.")
    openclaw_model_smoke_parser.add_argument("--full", action="store_true", help="Print normalized output and failure reasons.")
    openclaw_model_smoke_parser.add_argument("--json", action="store_true", help="Print the model smoke event as JSON.")
    openclaw_model_smoke_parser.set_defaults(func=handlers['cmd_openclaw_model_smoke'])

    openclaw_channels_parser = openclaw_subparsers.add_parser(
        "channels",
        help="Inventory, draft, and tightly gate OpenClaw external channel sends.",
    )
    openclaw_channels_subparsers = openclaw_channels_parser.add_subparsers(dest="channels_command", required=True)

    openclaw_channels_inventory_parser = openclaw_channels_subparsers.add_parser(
        "inventory",
        help="Record a read-only inventory of configured OpenClaw channels.",
    )
    openclaw_channels_inventory_parser.add_argument("--probe", action="store_true", help="Probe channel credentials where OpenClaw supports it.")
    openclaw_channels_inventory_parser.add_argument("--timeout", type=int, default=30, help="OpenClaw command timeout in seconds.")
    openclaw_channels_inventory_parser.add_argument("--full", action="store_true", help="Print permission and send-attempt details.")
    openclaw_channels_inventory_parser.add_argument("--json", action="store_true", help="Print the channel inventory event as JSON.")
    openclaw_channels_inventory_parser.set_defaults(func=handlers['cmd_openclaw_channels_inventory'])

    openclaw_channels_draft_parser = openclaw_channels_subparsers.add_parser(
        "draft",
        help="Record an external-channel message draft without sending it.",
    )
    openclaw_channels_draft_parser.add_argument("--channel", choices=settings['OPENCLAW_CHANNEL_CHOICES'], required=True, help="Target OpenClaw channel.")
    openclaw_channels_draft_parser.add_argument("--target", required=True, help="Recipient/channel target.")
    openclaw_channels_draft_parser.add_argument("--message", required=True, help="Draft message body.")
    openclaw_channels_draft_parser.add_argument("--account", help="Optional OpenClaw account id.")
    openclaw_channels_draft_parser.add_argument("--reply-to", help="Optional message id to reply to.")
    openclaw_channels_draft_parser.add_argument("--timeout", type=int, default=30, help="Read-only inventory timeout in seconds.")
    openclaw_channels_draft_parser.add_argument("--full", action="store_true", help="Print permission and send-attempt details.")
    openclaw_channels_draft_parser.add_argument("--json", action="store_true", help="Print the channel draft event as JSON.")
    openclaw_channels_draft_parser.set_defaults(func=handlers['cmd_openclaw_channels_draft'])

    openclaw_channels_send_parser = openclaw_channels_subparsers.add_parser(
        "send",
        help="Send through OpenClaw only after exact approval and channel preflight.",
    )
    openclaw_channels_send_parser.add_argument("--channel", choices=settings['OPENCLAW_CHANNEL_CHOICES'], required=True, help="Target OpenClaw channel.")
    openclaw_channels_send_parser.add_argument("--target", required=True, help="Recipient/channel target.")
    openclaw_channels_send_parser.add_argument("--message", required=True, help="Message body.")
    openclaw_channels_send_parser.add_argument("--account", help="Optional OpenClaw account id.")
    openclaw_channels_send_parser.add_argument("--reply-to", help="Optional message id to reply to.")
    openclaw_channels_send_parser.add_argument("--permission-request-id", help="Approved external_communication permission request id.")
    openclaw_channels_send_parser.add_argument("--use-trusted-directive", action="store_true", help="Use active trusted_operator_directive as current exact approval.")
    openclaw_channels_send_parser.add_argument("--confirm-approved-send", action="store_true", help="Required final CLI acknowledgement that this is an approved external send.")
    openclaw_channels_send_parser.add_argument("--dry-run", action="store_true", help="Ask OpenClaw to dry-run instead of sending after approval gates pass.")
    openclaw_channels_send_parser.add_argument("--timeout", type=int, default=30, help="OpenClaw command timeout in seconds.")
    openclaw_channels_send_parser.add_argument("--full", action="store_true", help="Print permission and send-attempt details.")
    openclaw_channels_send_parser.add_argument("--json", action="store_true", help="Print the channel send event as JSON.")
    openclaw_channels_send_parser.set_defaults(func=handlers['cmd_openclaw_channels_send'])

    openclaw_channels_pairing_parser = openclaw_channels_subparsers.add_parser(
        "pairing",
        help="Read pending OpenClaw pairing requests for one channel without approving them.",
    )
    openclaw_channels_pairing_parser.add_argument("--channel", choices=settings['OPENCLAW_CHANNEL_CHOICES'], required=True, help="Target OpenClaw channel.")
    openclaw_channels_pairing_parser.add_argument("--account", help="Optional OpenClaw account id.")
    openclaw_channels_pairing_parser.add_argument("--timeout", type=int, default=30, help="OpenClaw command timeout in seconds.")
    openclaw_channels_pairing_parser.add_argument("--full", action="store_true", help="Print permission and send-attempt details.")
    openclaw_channels_pairing_parser.add_argument("--json", action="store_true", help="Print pairing inventory as JSON.")
    openclaw_channels_pairing_parser.set_defaults(func=handlers['cmd_openclaw_channels_pairing'])

    openclaw_channels_directory_self_parser = openclaw_channels_subparsers.add_parser(
        "directory-self",
        help="Probe a channel's current account identity without sending, approving, or accepting interactive prompts.",
    )
    openclaw_channels_directory_self_parser.add_argument("--channel", choices=settings['OPENCLAW_CHANNEL_CHOICES'], required=True, help="Target OpenClaw channel.")
    openclaw_channels_directory_self_parser.add_argument("--account", help="Optional OpenClaw account id.")
    openclaw_channels_directory_self_parser.add_argument("--timeout", type=int, default=30, help="OpenClaw command timeout in seconds.")
    openclaw_channels_directory_self_parser.add_argument("--full", action="store_true", help="Print permission and send-attempt details.")
    openclaw_channels_directory_self_parser.add_argument("--json", action="store_true", help="Print directory probe as JSON.")
    openclaw_channels_directory_self_parser.set_defaults(func=handlers['cmd_openclaw_channels_directory_self'])

    openclaw_channels_events_parser = openclaw_channels_subparsers.add_parser(
        "events",
        help="List recent OpenClaw channel inventory, draft, and send events.",
    )
    openclaw_channels_events_parser.add_argument("--limit", type=int, default=20, help="Maximum channel events to show.")
    openclaw_channels_events_parser.add_argument("--runtime", action="store_true", help="Prefer runtime channel evidence.")
    openclaw_channels_events_parser.add_argument("--full", action="store_true", help="Print permission and send-attempt details.")
    openclaw_channels_events_parser.add_argument("--json", action="store_true", help="Print channel events as JSON.")
    openclaw_channels_events_parser.set_defaults(func=handlers['cmd_openclaw_channels_list_events'])

    openclaw_audit_parser = openclaw_subparsers.add_parser(
        "audit",
        help="Run the full OpenClaw integration audit and save a report.",
    )
    openclaw_audit_parser.add_argument("--timeout", type=int, default=30, help="OpenClaw command timeout in seconds.")
    openclaw_audit_parser.add_argument("--runtime", action="store_true", help="Prefer runtime event evidence.")
    openclaw_audit_parser.add_argument("--record-channel-inventory", action="store_true", help="Also append a channel inventory event during audit.")
    openclaw_audit_parser.add_argument("--full", action="store_true", help="Print evidence ids and degraded counts.")
    openclaw_audit_parser.add_argument("--json", action="store_true", help="Print the full OpenClaw audit report as JSON.")
    openclaw_audit_parser.set_defaults(func=handlers['cmd_openclaw_full_audit'])

    openclaw_contracts_parser = openclaw_subparsers.add_parser(
        "contracts",
        help="Show Eve-side typed contracts for using OpenClaw as a body/action bus.",
    )
    openclaw_contracts_parser.add_argument("--refresh-status", action="store_true", help="Refresh OpenClaw status before building the contract report.")
    openclaw_contracts_parser.add_argument("--save", action="store_true", help="Save the contract snapshot into .eve/openclaw_body_contracts.json.")
    openclaw_contracts_parser.add_argument("--full", action="store_true", help="Print command surfaces, verification, and rollback detail.")
    openclaw_contracts_parser.add_argument("--json", action="store_true", help="Print the contract report as JSON.")
    openclaw_contracts_parser.set_defaults(func=handlers['cmd_openclaw_contracts'])

    openclaw_evidence_parser = openclaw_subparsers.add_parser(
        "evidence",
        help="Inspect or record the OpenClaw event/evidence bridge.",
    )
    openclaw_evidence_parser.add_argument("--record-status", action="store_true", help="Append the current OpenClaw status as an evidence event.")
    openclaw_evidence_parser.add_argument(
        "--record-hook-event",
        help="Append one sanitized OpenClaw hook event JSON file as an evidence event.",
    )
    openclaw_evidence_parser.add_argument(
        "--ingest-activity",
        action="store_true",
        help="Append OpenClaw task, hook, and MCP activity snapshots as evidence events.",
    )
    openclaw_evidence_parser.add_argument(
        "--sanitize-existing-hooks",
        action="store_true",
        help="Rewrite existing hook callback evidence through the current sanitizer, with a backup.",
    )
    openclaw_evidence_parser.add_argument(
        "--include-sessions",
        action="store_true",
        help="Also append a bounded OpenClaw session/trajectory activity snapshot.",
    )
    openclaw_evidence_parser.add_argument("--activity-limit", type=int, default=25, help="Max task/session records to sample during activity ingest.")
    openclaw_evidence_parser.add_argument("--activity-timeout", type=int, default=20, help="Timeout in seconds for each OpenClaw activity command.")
    openclaw_evidence_parser.add_argument("--runtime", action="store_true", help="Prefer runtime evidence events.")
    openclaw_evidence_parser.add_argument("--limit", type=int, default=5, help="How many recent evidence events to show.")
    openclaw_evidence_parser.add_argument("--full", action="store_true", help="Print payload detail for recent events.")
    openclaw_evidence_parser.add_argument("--json", action="store_true", help="Print the evidence report as JSON.")
    openclaw_evidence_parser.set_defaults(func=handlers['cmd_openclaw_evidence'])

    openclaw_admission_parser = openclaw_subparsers.add_parser(
        "admission",
        help="Create or list admission records before new OpenClaw skills/plugins/MCP/ACP surfaces are enabled for Eve.",
    )
    openclaw_admission_subparsers = openclaw_admission_parser.add_subparsers(dest="openclaw_admission_command", required=True)

    openclaw_admission_list_parser = openclaw_admission_subparsers.add_parser("list", help="List OpenClaw capability admission records.")
    openclaw_admission_list_parser.add_argument("--limit", type=int, default=20, help="Max records to print.")
    openclaw_admission_list_parser.add_argument("--runtime", action="store_true", help="Prefer runtime admission records.")
    openclaw_admission_list_parser.add_argument("--full", action="store_true", help="Print data-boundary, verification, and rollback detail.")
    openclaw_admission_list_parser.add_argument("--json", action="store_true", help="Print admission records as JSON.")
    openclaw_admission_list_parser.set_defaults(func=handlers['cmd_openclaw_admission_list'])

    openclaw_admission_create_parser = openclaw_admission_subparsers.add_parser("create", help="Create one OpenClaw capability admission record.")
    openclaw_admission_create_parser.add_argument("--candidate-id", required=True, help="Stable id for the candidate capability.")
    openclaw_admission_create_parser.add_argument(
        "--candidate-type",
        required=True,
        choices=["skill", "plugin", "mcp", "acp", "subagent", "hook", "cron", "gateway", "tool", "other"],
        help="Candidate capability type.",
    )
    openclaw_admission_create_parser.add_argument("--source", required=True, help="Source URL, package, local path, or OpenClaw surface.")
    openclaw_admission_create_parser.add_argument("--capability", required=True, help="Capability this would add to Eve.")
    openclaw_admission_create_parser.add_argument(
        "--permission-level",
        default="pending_review",
        choices=["read_only", "operator_safe", "approval_gated", "specific_approval_required", "blocked", "pending_review"],
        help="Permission class for this candidate.",
    )
    openclaw_admission_create_parser.add_argument("--data-boundary", default="unknown", help="What data/files/accounts/devices this candidate can touch.")
    openclaw_admission_create_parser.add_argument(
        "--decision",
        default="pending_review",
        choices=["pending_review", "approved", "rejected", "revoked", "watch"],
        help="Admission decision.",
    )
    openclaw_admission_create_parser.add_argument("--verification-command", help="Command or procedure that verifies the candidate.")
    openclaw_admission_create_parser.add_argument("--rollback", help="Rollback/disable path.")
    openclaw_admission_create_parser.add_argument("--notes", help="Additional review notes.")
    openclaw_admission_create_parser.add_argument("--json", action="store_true", help="Print the new admission as JSON.")
    openclaw_admission_create_parser.set_defaults(func=handlers['cmd_openclaw_admission_create'])

    mcp_parser = subparsers.add_parser("mcp", help="Inspect or preflight MCP tool surfaces before Eve can use them.")
    mcp_subparsers = mcp_parser.add_subparsers(dest="mcp_command", required=True)

    mcp_admission_parser = mcp_subparsers.add_parser(
        "admission",
        help="Run Eve's gated MCP admission checklist without enabling the tool.",
    )
    mcp_admission_parser.add_argument("--candidate-id", required=True, help="Stable id for the MCP candidate.")
    mcp_admission_parser.add_argument("--name", help="Human-readable MCP candidate name.")
    mcp_admission_parser.add_argument("--candidate-type", default="mcp", choices=["mcp"], help="Candidate type; fixed to MCP for this checklist.")
    mcp_admission_parser.add_argument("--source", required=True, help="Source URL, package, local path, or OpenClaw MCP surface.")
    mcp_admission_parser.add_argument("--purpose", required=True, help="Exact Eve purpose and why existing tools are not enough.")
    mcp_admission_parser.add_argument(
        "--permission-level",
        default="pending_review",
        choices=sorted(settings['MCP_ADMISSION_ALLOWED_PERMISSION_LEVELS']),
        help="Permission class to carry into the OpenClaw admission record.",
    )
    mcp_admission_parser.add_argument("--data-boundary", help="Data/accounts/devices/private information this candidate can touch.")
    mcp_admission_parser.add_argument("--filesystem-scope", help="Filesystem read/write roots and protected paths.")
    mcp_admission_parser.add_argument("--network-scope", help="Network hosts, endpoints, and external-send behavior.")
    mcp_admission_parser.add_argument("--credential-scope", help="Required secrets and storage location, or explicit none.")
    mcp_admission_parser.add_argument(
        "--tool",
        action="append",
        help="Tool manifest item as name:risk where risk is read, write, or destructive. Repeat for multiple tools.",
    )
    mcp_admission_parser.add_argument("--logging-evidence", help="Action log or evidence path to inspect after use.")
    mcp_admission_parser.add_argument("--verification-command", help="Smoke-test or verification command.")
    mcp_admission_parser.add_argument("--rollback", help="Disable, rollback, or restore path.")
    mcp_admission_parser.add_argument("--admission-record", help="Existing OpenClaw admission id or explicit creation command.")
    mcp_admission_parser.add_argument(
        "--noninteractive-policy",
        default="fail",
        choices=["fail", "ask", "allow", "auto"],
        help="How the MCP candidate handles noninteractive permission prompts; Eve requires fail.",
    )
    mcp_admission_parser.add_argument("--owner-review", default="codex_preflight", help="Review owner/status for this admission preflight.")
    mcp_admission_parser.add_argument("--full", action="store_true", help="Print missing fields, blockers, and suggested OpenClaw command.")
    mcp_admission_parser.add_argument("--json", action="store_true", help="Print the admission checklist as JSON.")
    mcp_admission_parser.set_defaults(func=handlers['cmd_mcp_admission'])

    proposal_parser = subparsers.add_parser("proposal", help="Draft and review concrete change proposals.")
    proposal_subparsers = proposal_parser.add_subparsers(dest="proposal_command", required=True)

    proposal_suggest_parser = proposal_subparsers.add_parser("suggest", help="Draft a proposal from recent context.")
    proposal_suggest_parser.add_argument("--model", help="Override model name.")
    proposal_suggest_parser.add_argument("--max-tokens", type=int, help="Max tokens to predict.")
    proposal_suggest_parser.set_defaults(func=handlers['cmd_proposal_suggest'])

    proposal_list_parser = proposal_subparsers.add_parser("list", help="List proposals.")
    proposal_list_parser.add_argument("--limit", type=int, default=20, help="Max proposals to print.")
    proposal_list_parser.add_argument(
        "--status",
        choices=["draft", "approved", "rejected", "applied", "archived"],
        help="Filter by status.",
    )
    proposal_list_parser.add_argument("--full", action="store_true", help="Print the full proposal body.")
    proposal_list_parser.set_defaults(func=handlers['cmd_proposal_list'])

    proposal_update_parser = proposal_subparsers.add_parser("update", help="Update a proposal.")
    proposal_update_parser.add_argument("id", help="Proposal id.")
    proposal_update_parser.add_argument(
        "--status",
        choices=["draft", "approved", "rejected", "applied", "archived"],
        help="New proposal status.",
    )
    proposal_update_parser.add_argument("--title", help="Updated title.")
    proposal_update_parser.add_argument("--summary", help="Updated summary.")
    proposal_update_parser.add_argument("--body", help="Updated body.")
    proposal_update_parser.set_defaults(func=handlers['cmd_proposal_update'])

    task_parser = subparsers.add_parser("task", help="Inspect and run Eve's hardware-aware task queue.")
    task_subparsers = task_parser.add_subparsers(dest="task_command", required=True)

    task_list_parser = task_subparsers.add_parser("list", help="List hardware-aware tasks.")
    task_list_parser.add_argument("--limit", type=int, default=20, help="Max tasks to print.")
    task_list_parser.add_argument("--days", type=int, help="Filter to recent days.")
    task_list_parser.add_argument("--status", choices=settings['SYSTEM_TASK_STATUSES'], help="Filter by task status.")
    task_list_parser.add_argument("--lane", choices=settings['SYSTEM_TASK_LANES'], help="Filter by execution lane.")
    task_list_parser.add_argument("--kind", help="Filter by task kind.")
    task_list_parser.add_argument("--full", action="store_true", help="Print task metadata.")
    task_list_parser.set_defaults(func=handlers['cmd_task_list'])

    task_refresh_parser = task_subparsers.add_parser("refresh", help="Create or sync tasks from the latest system snapshot.")
    task_refresh_parser.add_argument("--run-cpu", action="store_true", help="Immediately process the next planned CPU tasks after refreshing.")
    task_refresh_parser.add_argument("--cpu-limit", type=int, default=3, help="How many CPU tasks to run when --run-cpu is set.")
    task_refresh_parser.set_defaults(func=handlers['cmd_task_refresh'])

    task_run_parser = task_subparsers.add_parser("run", help="Run planned CPU tasks without refreshing the queue first.")
    task_run_parser.add_argument("--limit", type=int, default=3, help="How many CPU tasks to process.")
    task_run_parser.set_defaults(func=handlers['cmd_task_run'])

    task_update_parser = task_subparsers.add_parser("update", help="Update one hardware-aware task.")
    task_update_parser.add_argument("id", help="Task id.")
    task_update_parser.add_argument("--status", choices=settings['SYSTEM_TASK_STATUSES'], help="New task status.")
    task_update_parser.add_argument("--blocked-reason", help="Updated blocked reason. Use an empty string to clear it.")
    task_update_parser.add_argument("--result-summary", help="Updated result summary. Use an empty string to clear it.")
    task_update_parser.set_defaults(func=handlers['cmd_task_update'])

    task_graph_parser = task_subparsers.add_parser("graph", help="Build a durable dependency graph over Eve's system tasks.")
    task_graph_parser.add_argument("--days", type=int, help="Filter to recent days.")
    task_graph_parser.add_argument("--status", choices=settings['SYSTEM_TASK_STATUSES'], help="Filter by task status.")
    task_graph_parser.add_argument("--lane", choices=settings['SYSTEM_TASK_LANES'], help="Filter by execution lane.")
    task_graph_parser.add_argument("--kind", help="Filter by task kind.")
    task_graph_parser.add_argument("--include-archived", action="store_true", help="Include archived tasks in the graph.")
    task_graph_parser.add_argument("--full", action="store_true", help="Print graph counters.")
    task_graph_parser.set_defaults(func=handlers['cmd_task_graph'])

    task_beads_parser = task_subparsers.add_parser(
        "beads",
        help="Preview or apply Eve's one-way system-task projection into Beads.",
    )
    task_beads_parser.add_argument(
        "--apply",
        action="store_true",
        help="Create/update the Beads projection and verify task, dependency, and ready-queue parity.",
    )
    task_beads_parser.add_argument(
        "--max-tasks",
        type=int,
        default=80,
        help="Maximum active-plus-dependency task closure allowed in one projection.",
    )
    task_beads_parser.add_argument("--timeout", type=int, default=15, help="Per-command Beads timeout in seconds.")
    task_beads_parser.add_argument("--full", action="store_true", help="Print detailed parity mismatches.")
    task_beads_parser.set_defaults(func=handlers['cmd_task_beads'])

    maintenance_parser = subparsers.add_parser("maintenance", help="Inspect, approve, and run approval-gated maintenance actions.")
    maintenance_subparsers = maintenance_parser.add_subparsers(dest="maintenance_command", required=True)

    maintenance_list_parser = maintenance_subparsers.add_parser("list", help="List approval-gated maintenance actions.")
    maintenance_list_parser.add_argument("--limit", type=int, default=20, help="Max actions to print.")
    maintenance_list_parser.add_argument("--days", type=int, help="Filter to recent days.")
    maintenance_list_parser.add_argument("--status", choices=settings['MAINTENANCE_ACTION_STATUSES'], help="Filter by action status.")
    maintenance_list_parser.add_argument("--kind", help="Filter by action kind.")
    maintenance_list_parser.add_argument("--full", action="store_true", help="Print action metadata.")
    maintenance_list_parser.set_defaults(func=handlers['cmd_maintenance_list'])

    maintenance_update_parser = maintenance_subparsers.add_parser("update", help="Approve, reject, or otherwise update one maintenance action.")
    maintenance_update_parser.add_argument("id", help="Maintenance action id.")
    maintenance_update_parser.add_argument("--status", choices=settings['MAINTENANCE_ACTION_STATUSES'], help="New maintenance action status.")
    maintenance_update_parser.add_argument("--blocked-reason", help="Updated blocked reason. Use an empty string to clear it.")
    maintenance_update_parser.add_argument("--result-summary", help="Updated result summary. Use an empty string to clear it.")
    maintenance_update_parser.set_defaults(func=handlers['cmd_maintenance_update'])

    maintenance_run_parser = maintenance_subparsers.add_parser("run", help="Execute approved maintenance actions and then re-audit the system.")
    maintenance_run_parser.add_argument("--limit", type=int, default=1, help="How many approved actions to execute.")
    maintenance_run_parser.set_defaults(func=handlers['cmd_maintenance_run'])

    self_change_parser = subparsers.add_parser("self-change", help="Inspect and revert Eve's own self-change sessions.")
    self_change_subparsers = self_change_parser.add_subparsers(dest="self_change_command", required=True)

    self_change_list_parser = self_change_subparsers.add_parser("list", help="List self-change ledger rows, newest first, with whether a before-image and backup exist.")
    self_change_list_parser.add_argument("--limit", type=int, default=20, help="Max ledger rows to print.")
    self_change_list_parser.add_argument("--json", action="store_true", help="Print the rows as JSON.")
    self_change_list_parser.set_defaults(func=handlers['cmd_self_change_list'])

    self_change_revert_parser = self_change_subparsers.add_parser("revert", help="Restore config keys, action blocks, pattern statuses, maintenance approvals and code files from one session's before-image and backup.")
    self_change_revert_parser.add_argument("session_id", help="Self-change session id (see `self-change list`).")
    self_change_revert_parser.set_defaults(func=handlers['cmd_self_change_revert'])

    daemon_parser = subparsers.add_parser("daemon", help="Run Eve continuously and inspect its service/runtime state.")
    daemon_subparsers = daemon_parser.add_subparsers(dest="daemon_command", required=True)

    daemon_run_parser = daemon_subparsers.add_parser("run", help="Run the Eve daemon loop.")
    daemon_run_parser.add_argument("--once", action="store_true", help="Run one cycle and exit.")
    daemon_run_parser.add_argument("--force", action="store_true", help="Force all due jobs in a one-shot cycle.")
    daemon_run_parser.add_argument("--sleep-seconds", type=int, help="Override loop sleep interval.")
    daemon_run_parser.set_defaults(func=handlers['cmd_daemon_run'])

    daemon_install_parser = daemon_subparsers.add_parser("install", help="Install and start the native background service when supported.")
    daemon_install_parser.set_defaults(func=handlers['cmd_daemon_install'])

    daemon_start_parser = daemon_subparsers.add_parser("start", help="Start the native background service when supported.")
    daemon_start_parser.set_defaults(func=handlers['cmd_daemon_start'])

    daemon_stop_parser = daemon_subparsers.add_parser("stop", help="Stop the native background service when supported.")
    daemon_stop_parser.set_defaults(func=handlers['cmd_daemon_stop'])

    daemon_status_parser = daemon_subparsers.add_parser("status", help="Show Eve daemon status.")
    daemon_status_parser.set_defaults(func=handlers['cmd_daemon_status'])

    daemon_uninstall_parser = daemon_subparsers.add_parser("uninstall", help="Stop and remove the native background service when supported.")
    daemon_uninstall_parser.set_defaults(func=handlers['cmd_daemon_uninstall'])

    return parser

