"""Self-change application service. Effects are explicit injected ports.

This module can execute with plain fakes when the Eve facade is unavailable.
It neither imports infrastructure nor grants any additional tool authority.
"""
from typing import Dict, Mapping, Optional

from .changes import bounded_integer, collect_change_evidence, compact_text
from .ports import Clock, Coder, Journal, Proposals, Runtime


class SelfChangeService:
    def __init__(self, clock: Clock, proposals: Proposals, coder: Coder, runtime: Runtime, journal: Journal):
        self.clock = clock
        self.proposals = proposals
        self.coder = coder
        self.runtime = runtime
        self.journal = journal

    def run(self, config: Mapping[str, object], *, source: str, timeout_seconds: Optional[int] = None, proposal_id: Optional[str] = None) -> Dict[str, object]:
        now = self.clock.utc()
        if str(config.get("self_change_enabled", True)).strip().lower() in {"false", "0", "no", "off"}:
            return {"executed": False, "ok": False, "summary": "Self-change is disabled in config."}
        try:
            history = self.journal.history()
        except Exception as exc:
            return {"executed": False, "ok": False, "summary": "Self-change history unavailable: " + compact_text(exc)}
        done_today = sum(1 for row in history if str(row.get("started_at") or "").startswith(now[:10]))
        budget = bounded_integer(config.get("self_change_max_per_day"), 12, 1, 100)
        if done_today >= budget:
            return {"executed": False, "ok": False, "summary": f"Self-change budget for today is spent ({done_today}/{budget})."}
        try:
            self.proposals.archive_stale(config)
        except Exception:
            # Existing housekeeping policy: stale archival does not block work.
            pass
        try:
            candidates = self.proposals.candidates(config)
        except Exception as exc:
            return {"executed": False, "ok": False, "summary": "Self-change candidates unavailable: " + compact_text(exc)}
        if proposal_id:
            candidates = [item for item in candidates if str(item.get("id")) == proposal_id]
        if not candidates:
            return {"executed": False, "ok": False, "summary": "No draft proposal of Eve's is waiting to be applied."}
        proposal = candidates[0]
        default_timeout = bounded_integer(config.get("self_change_timeout_seconds"), 900, 60, 1800)
        timeout = bounded_integer(timeout_seconds, default_timeout, 60, 1800)
        try:
            session = self.coder.prepare(config, now, proposal, timeout)
        except Exception as exc:
            return {"executed": False, "ok": False, "summary": "Self-change preparation failed: " + compact_text(exc), "error": compact_text(exc)}
        title = compact_text(proposal.get("title"), limit=160)
        try:
            self.journal.entry("self_change_started", "Eve is applying her proposal: " + title,
                               {"source": source, "proposal_id": proposal.get("id"), "session_id": session.session_id})
        except Exception as exc:
            return {"executed": False, "ok": False, "summary": "Self-change start could not be recorded: " + compact_text(exc)}
        started, error, agent = self.clock.monotonic(), "", {}
        try:
            agent = self.coder.execute(session, proposal)
        except (Exception, SystemExit) as exc:
            error = compact_text(exc, "coder session failed", 300)
        evidence = collect_change_evidence(agent, self.coder.authority_tools)
        if evidence.errors:
            error = "; ".join(filter(None, (error, *evidence.errors)))[:600]
        verified, verification, rollback = not bool(error), "no code changed", []
        runtime_synced, restart_requested, source_restored = False, False, None
        if evidence.paths:
            try:
                check = self.coder.verify(session, evidence.tests_ok)
                verified = check.ok is True and not error
                verification = check.detail
            except Exception as exc:
                verified, verification = False, "verification failed: " + compact_text(exc)
        elif evidence.tests_ok is False:
            verified, verification = False, "the tests she ran failed"
        if error:
            verification = "; ".join((verification, error))
        restart_reason = str(session.context.get("restart_requested") or "")
        if evidence.paths and verified:
            try:
                receipt = self.runtime.synchronize()
                if not isinstance(receipt, Mapping) or receipt.get("verified") is not True:
                    raise ValueError("runtime synchronization returned no verified installation receipt")
                runtime_synced = True
                restart_reason = restart_reason or f"self-change {session.session_id}: code changed"
            except Exception as exc:
                verified = False
                error = compact_text(exc, "runtime synchronization failed", 300)
                verification += "; runtime sync failed: " + error
        if evidence.paths and not verified:
            try:
                rollback = self.coder.rollback(session)
                source_restored = isinstance(rollback, list) and set(evidence.paths).issubset(rollback)
                if not source_restored:
                    error = "; ".join(filter(None, (error, "source rollback incomplete")))
                    verification += "; source rollback incomplete"
            except Exception as exc:
                source_restored = False
                error = "; ".join(filter(None, (error, "rollback failed: " + compact_text(exc))))
                verification += "; source rollback failed"
        applied = verified and not error and bool(evidence.changes or evidence.paths)
        if restart_reason and applied:
            try:
                restart_requested = self.runtime.restart(session, restart_reason, bool(evidence.paths)) is True
                if not restart_requested:
                    raise ValueError("restart request was not acknowledged")
            except Exception as exc:
                # A synchronized bundle is not undone by a failed restart request.
                # Keep the before-image and report partial effects, never success.
                error = "restart failed: " + compact_text(exc)
                applied = False
                verification += "; " + error
        deferred = evidence.deferred_only and not error
        metadata = dict(proposal.get("metadata") or {}) if isinstance(proposal.get("metadata"), Mapping) else {}
        previous = bounded_integer(metadata.get("self_change_attempts"), 0, 0, 1000000)
        attempts = previous if deferred else previous + 1
        metadata.update(self_change_attempts=attempts, self_change_session=session.session_id, self_change_at=now)
        report = compact_text(agent.get("response") if isinstance(agent, Mapping) else None, error or "no report", 400)
        holder = evidence.deferred[0] if deferred else ""
        if applied:
            outcome, status = "applied", "applied"
            metadata.update(applied_by="eve_self_change", applied_summary=report[:300])
        elif deferred:
            outcome, status = "deferred_claim", "draft"
            metadata.update(self_change_deferred_claim=holder, self_change_deferred_at=now)
            verification = f"deferred: paths claimed by {holder} on the coordination board"
        elif error or not verified:
            outcome = "failed"
            limit = bounded_integer(config.get("self_change_max_attempts_per_proposal"), 2, 1, 5)
            status = "archived" if attempts >= limit else "draft"
            metadata["self_change_last_error"] = (error or verification)[:300]
        else:
            outcome, status = "no_change", "archived"
            metadata["self_change_verdict"] = report[:300]
        row = {
            "started_at": now, "finished_at": self.clock.utc(),
            "elapsed_seconds": round(max(0, self.clock.monotonic() - started), 1),
            "source": source, "session_id": session.session_id, "proposal_id": proposal.get("id"),
            "proposal_title": title, "outcome": outcome, "changes": list(evidence.changes),
            "patched_paths": list(evidence.paths), "verified": verified, "verification": verification,
            "rollback": rollback, "restart_requested": restart_requested, "runtime_synced": runtime_synced,
            "source_restored": source_restored,
            "partial_effects": outcome == "failed" and bool(evidence.changes or runtime_synced or (evidence.paths and source_restored is not True)),
            "error": error, "report": report, "deferred_claim": holder,
        }
        # The existing stores are separate files, not an atomic transaction. If
        # persistence fails, surface it even if source/runtime effects succeeded.
        try:
            self.proposals.update(str(proposal.get("id")), status, metadata)
            self.journal.write(row)
            self.journal.entry("self_change_" + outcome, f"Self-change {outcome}: {title}. {verification}. {report[:200]}",
                               {key: value for key, value in row.items() if key != "report"})
        except Exception as exc:
            row.update(outcome="failed", partial_effects=bool(evidence.changes or runtime_synced or (evidence.paths and source_restored is not True)),
                       error="audit persistence failed: " + compact_text(exc))
            row["verification"] += "; " + row["error"]
        warnings = []
        if row["outcome"] == "applied":
            for name, action in (("follow-up", lambda: self.journal.follow_up(row, config)), ("notification", lambda: self.journal.notify(row))):
                try:
                    action()
                except Exception as exc:
                    warning = name + " failed: " + compact_text(exc)
                    warnings.append(warning)
                    try:
                        self.journal.entry("daemon_error", "self-change " + warning, {"source": source, "session_id": session.session_id})
                    except Exception:
                        pass  # Return the warning even when the journal itself is unavailable.
        return {
            "executed": True, "ok": row["outcome"] == "applied",
            "summary": f"Self-change {row['outcome']}: {title[:120]}. {row['verification']}.",
            **{key: row[key] for key in ("outcome", "session_id", "changes", "patched_paths", "verified", "verification", "rollback", "source_restored", "restart_requested", "runtime_synced", "partial_effects", "error", "deferred_claim")},
            "warnings": warnings,
        }
