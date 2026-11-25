"""Manual composition of the independent use case with existing Eve owners.

Only this migration adapter resolves legacy facade dependencies. Do not move
the facade proxy or file/model access into eve_core.
"""
import time
import uuid
from typing import Optional

from eve_core.ports import CodingSession, Verification
from eve_core.self_change import SelfChangeService
from eve_late import core


class LegacyClock:
    def utc(self):
        return core.utc_now()

    def monotonic(self):
        return time.monotonic()


class LegacyProposals:
    def archive_stale(self, config):
        core.archive_stale_draft_proposals(dict(config))

    def candidates(self, config):
        return core.self_change_candidate_proposals(dict(config))

    def update(self, proposal_id, status, metadata):
        core.update_proposal_record(proposal_id, status=status, metadata=metadata)


class LegacyCoder:
    @property
    def authority_tools(self):
        return tuple(core.SELF_AUTHORITY_TOOL_NAMES)

    def prepare(self, config, now, proposal, timeout):
        session_id = f"self-change-{now.replace(':', '').replace('-', '')[:15]}-{str(proposal.get('id'))[:8]}-{uuid.uuid4().hex[:8]}"
        backup_dir = core.SELF_CHANGE_DIR / session_id / "backup"
        backup_dir.mkdir(parents=True, exist_ok=True)
        session = CodingSession(session_id, str(backup_dir), dict(config))
        session.config.update(_self_change_backup_dir=str(backup_dir), _self_change_session=session_id,
                              _self_change_context=session.context, _coder_disable_apply_patch=False,
                              code_timeout_seconds=timeout)
        return session

    def execute(self, session, proposal):
        return core.run_eve_coder_agent(session.config, core.build_self_change_request(dict(proposal)),
                                       session_id=session.session_id, require_tool_use=True)

    def verify(self, session, tests_ok: Optional[bool]):
        # Discover exactly the first-party code that the runtime bundle mirrors,
        # including packages such as eve_core, not just root-level modules.
        targets = sorted({str(source) for _, source, _ in core.first_party_python_source_pairs() if source.suffix == ".py"})
        if not targets:
            return Verification(False, "first-party code inventory is empty")
        compiled = core.subprocess.run([core.sys.executable, "-m", "py_compile", *targets], capture_output=True, text=True, check=False)
        if compiled.returncode != 0:
            return Verification(False, "first-party code does not compile: " + (compiled.stderr or "")[-200:])
        if tests_ok is False:
            return Verification(False, "the tests she ran failed")
        # A model's successful run_tests receipt may cover an arbitrary command.
        # It never replaces the owner's fixed regression/boundary suite.
        focused = core.run_coder_shell_command("python3 -m unittest " + " ".join(core.SELF_CHANGE_VERIFICATION_SUITES),
                                               session.config, timeout_seconds=600)
        ok = isinstance(focused, dict) and focused.get("ok") is True
        return Verification(ok, "focused tests passed" if ok else "focused tests failed: " + str(focused.get("stderr") if isinstance(focused, dict) else focused)[-200:])

    def rollback(self, session):
        return core.restore_paths_from_backup(core.Path(session.backup_dir), session.config)


class LegacyRuntime:
    def synchronize(self):
        return core.sync_runtime_python_code(check_only=False)

    def restart(self, session, reason, code_changed):
        receipt = core.request_daemon_restart(reason, source="self_change:" + session.session_id,
                                              rollback_dir=session.backup_dir if code_changed else "")
        return isinstance(receipt, dict) and bool(receipt.get("requested_at") and receipt.get("reason"))


class LegacyJournal:
    def history(self):
        return core.read_self_change_ledger()

    def entry(self, kind, text, metadata):
        core.append_entry(kind, text, metadata=metadata)

    def write(self, row):
        core.append_self_change_ledger(row)

    def follow_up(self, row, config):
        core.schedule_self_change_followup(row, dict(config))

    def notify(self, row):
        changes = "; ".join(row["changes"]) or ", ".join(row["patched_paths"])
        core.create_daemon_message(
            subject="I changed myself: " + row["proposal_title"][:80],
            body=f"I applied my own proposal without waiting for approval, inside my edges.\n\nWhat changed: {changes}\nVerification: {row['verification']}\nRestart: {'requested' if row['restart_requested'] else 'not needed'}\n\nMy report: {row['report']}",
            kind="self_change", metadata={"session_id": row["session_id"], "proposal_id": row["proposal_id"]})


def compose_self_change_service() -> SelfChangeService:
    return SelfChangeService(LegacyClock(), LegacyProposals(), LegacyCoder(), LegacyRuntime(), LegacyJournal())
