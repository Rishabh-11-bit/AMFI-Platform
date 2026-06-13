"""
AMFI v4 — Agent Executor
Orchestrates the full incident lifecycle:
  classify → set SLA → load procedure → execute steps → verify → resolve / escalate
"""
import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.config import get_settings
from backend.models.models import (
    Incident, IncidentStep, IncidentStatus, Priority,
    SLAPolicy, Host, Resolution, Approval, AuditLog,
)
from backend.agent.classifier import classify
from backend.agent.procedures.library import get_procedure

logger   = logging.getLogger("amfi.executor")
settings = get_settings()


class AgentExecutor:
    """Purpose-built NOC agent — runs one incident through its full procedure."""

    # ── Public entry point ─────────────────────────────────────────────────────

    async def run(self, incident_id: int, db: AsyncSession) -> None:
        """
        Run the agent against *incident_id*.
        Safe to call multiple times — resumes from current status.
        Commits incrementally so partial progress is visible in the UI.
        """
        inc = await self._get_incident(incident_id, db)
        if inc is None:
            logger.error("Incident %d not found", incident_id)
            return

        # Don't re-run resolved/closed/false-positive incidents
        if inc.status in (
            IncidentStatus.RESOLVED, IncidentStatus.CLOSED,
            IncidentStatus.FALSE_POSITIVE, IncidentStatus.L3_ESCALATED,
        ):
            logger.info("%s already in terminal state (%s), skipping", inc.number, inc.status)
            return

        logger.info("Agent starting on %s: %s", inc.number, inc.title[:80])

        try:
            # ── Step 1: Classify ──────────────────────────────────────────────
            if not inc.fault_category:
                cat, prio = classify(inc.title, inc.description or "")
                inc.fault_category = cat.value
                if not inc.priority:
                    inc.priority = prio.value
                await db.commit()
                logger.info("%s classified as %s / %s", inc.number, cat.value, prio.value)

            # ── Step 2: Set SLA deadlines ─────────────────────────────────────
            if not inc.sla_response_due:
                await self._set_sla(inc, db)
                await db.commit()

            # ── Step 3: Load host config ──────────────────────────────────────
            host_cfg = await self._get_host(inc.affected_host, db) if inc.affected_host else None

            # If host is flagged never_touch, escalate immediately
            if host_cfg and host_cfg.never_touch:
                await self._escalate_l3(inc, db, reason="Host flagged as never_touch in CMDB")
                await db.commit()
                return

            # ── Step 4: Execute procedure ─────────────────────────────────────
            inc.status = IncidentStatus.L1_RUNNING
            inc.attempt_count = (inc.attempt_count or 0) + 1
            await db.commit()

            procedure = get_procedure(inc.fault_category or "unknown")
            resolved  = await self._run_procedure(inc, procedure, host_cfg, db)

            # ── Step 5: Finalise ──────────────────────────────────────────────
            if resolved:
                await self._mark_resolved(inc, db)
            elif inc.status not in (
                IncidentStatus.L1_WAITING, IncidentStatus.L2_WAITING,
                IncidentStatus.L3_ESCALATED,
            ):
                if inc.attempt_count >= settings.agent_max_attempts:
                    await self._escalate_l3(inc, db, reason="Max remediation attempts reached")
                else:
                    inc.status = IncidentStatus.L1_FAILED

            await db.commit()

        except Exception as e:
            logger.exception("Executor error on %s: %s", inc.number, e)
            inc.status = IncidentStatus.L1_FAILED
            await self._add_step(
                db, inc.id,
                step_type="error", action="executor_error",
                raw_output=str(e), success=False, error=str(e),
            )
            await db.commit()

    # ── Procedure runner ───────────────────────────────────────────────────────

    async def _run_procedure(
        self,
        inc:        Incident,
        procedure:  list[dict],
        host_cfg:   Optional[Host],
        db:         AsyncSession,
    ) -> bool:
        """
        Execute each step in *procedure* sequentially.
        Returns True if the incident is resolved after the procedure.

        Resume-safe: tracks completed steps by count and skips them on re-entry.
        Approval-aware: pauses on high-risk steps until a human approves.
        """
        existing_steps = await self._count_steps(inc.id, db)
        diagnostic_outputs: dict[str, str] = {}
        ai_interpretation = ""
        resolved = False

        for i, step in enumerate(procedure):
            # ── Skip already-completed steps (resume after approval) ───────────
            if i < existing_steps:
                continue

            seq        = i + 1    # 1-indexed sequence number
            fn_name    = step["fn"]
            step_type  = step["step_type"]
            step_name  = step["name"]
            required   = step.get("required", False)

            logger.info("%s step %d/%d: %s", inc.number, seq, len(procedure), step_name)

            # ── Approval gate: pause high-risk actions ─────────────────────────
            if fn_name in settings.high_risk_actions_list:
                approval = await self._get_approval(inc.id, fn_name, db)
                if approval is None or approval.status == "pending":
                    # No approval yet — request one and halt
                    await self._request_approval(inc, step, seq, db)
                    return False
                elif approval.status == "rejected":
                    # Operator rejected — record and skip this step
                    logger.warning(
                        "%s step '%s' rejected by %s: %s",
                        inc.number, fn_name,
                        approval.decided_by, approval.decision_note,
                    )
                    await self._add_step(
                        db, inc.id,
                        sequence   = seq,
                        level      = "l1",
                        step_type  = step_type,
                        action     = step_name,
                        raw_output = f"REJECTED by {approval.decided_by}: {approval.decision_note or ''}",
                        success    = False,
                        error      = "Action rejected by operator",
                    )
                    await db.commit()
                    continue   # skip to next step
                # else: status == "approved" → fall through and execute

            t0 = time.monotonic()
            result = await self._dispatch_step(
                fn_name        = fn_name,
                inc            = inc,
                host_cfg       = host_cfg,
                db             = db,
                diagnostic_outputs = diagnostic_outputs,
                ai_interpretation  = ai_interpretation,
            )
            duration_ms = int((time.monotonic() - t0) * 1000)

            # Accumulate diagnostic output for AI interpretation
            if step_type == "diagnostic":
                content = result.get("output") or result.get("error") or ""
                if content:
                    diagnostic_outputs[step_name] = content

            # Capture AI interpretation for escalation brief
            if step_type == "ai_interpret" and result.get("ai_interpretation"):
                ai_interpretation = result["ai_interpretation"]

            success    = result.get("success", True)
            raw_output = result.get("output") or result.get("ai_interpretation") or ""
            error      = result.get("error", "")

            db_step = await self._add_step(
                db             = db,
                incident_id    = inc.id,
                sequence       = seq,
                level          = "l1",
                step_type      = step_type,
                action         = step_name,
                command        = result.get("command"),
                raw_output     = raw_output[:4000],
                parsed_result  = result.get("parsed"),
                ai_interpretation = result.get("ai_interpretation"),
                success        = success,
                error          = error[:1000] if error else None,
                duration_ms    = duration_ms,
            )
            await db.commit()

            # Special case: escalate_l3 step ends the procedure
            if fn_name == "escalate_l3":
                await self._escalate_l3(inc, db, reason=ai_interpretation or "Agent escalation")
                return False

            # If a required step (ping) fails, host is unreachable — escalate
            if required and not success:
                logger.warning("%s required step failed: %s", inc.number, step_name)
                await self._escalate_l3(
                    inc, db,
                    reason=f"Host unreachable: {error or raw_output}"
                )
                return False

            # Verify steps signal resolution
            if step_type == "verify" and success:
                resolved = True

        return resolved

    # ── Step dispatcher ────────────────────────────────────────────────────────

    async def _dispatch_step(
        self,
        fn_name:           str,
        inc:               Incident,
        host_cfg:          Optional[Host],
        db:                AsyncSession,
        diagnostic_outputs: dict,
        ai_interpretation:  str,
    ) -> dict:
        """Map fn_name → actual coroutine and call it."""
        host     = inc.affected_host or "localhost"
        service  = inc.affected_service or "unknown"
        user     = host_cfg.ssh_user if host_cfg else "root"
        key_path = host_cfg.ssh_key_path if host_cfg else None
        port     = host_cfg.ssh_port if host_cfg else 22

        from backend.agent.tools.ssh          import ping_host
        from backend.agent.tools.diagnostics  import (
            check_disk, check_cpu, check_memory, check_processes,
            check_service, check_service_logs, check_network_interfaces,
            check_db_service,
        )
        from backend.agent.tools.actions      import (
            restart_service, clear_old_logs, clear_tmp_files,
            clear_memory_cache, kill_top_process,
            verify_disk_usage, verify_cpu_usage,
            verify_memory_usage, verify_service_running,
        )
        from backend.agent.llm import interpret_diagnostics

        if fn_name == "ping":
            r = await ping_host(host)
            return {
                "output":  f"Host {host}: {'reachable' if r['reachable'] else 'UNREACHABLE'} "
                           f"({r.get('latency_ms', '?')}ms via {r.get('method', '?')})",
                "success": r["reachable"],
                "error":   "" if r["reachable"] else f"Host {host} unreachable",
            }

        elif fn_name == "check_disk":
            return await check_disk(host, user, key_path, port)

        elif fn_name == "check_cpu":
            return await check_cpu(host, user, key_path, port)

        elif fn_name == "check_memory":
            return await check_memory(host, user, key_path, port)

        elif fn_name == "check_processes":
            return await check_processes(host, user, key_path, port)

        elif fn_name == "check_service":
            return await check_service(host, service, user, key_path, port)

        elif fn_name == "check_service_logs":
            return await check_service_logs(host, service, user, key_path, port)

        elif fn_name == "check_network_interfaces":
            return await check_network_interfaces(host, user, key_path, port)

        elif fn_name == "check_db_service":
            db_type = _guess_db_type(service, inc.title)
            return await check_db_service(host, db_type, user, key_path, port)

        elif fn_name == "ai_interpret":
            if not diagnostic_outputs:
                # All steps failed with no output — synthesize a summary for the AI
                diagnostic_outputs["connectivity"] = (
                    "All diagnostic steps failed. "
                    f"Host {host} appears to be unreachable (SSH connection refused or timed out)."
                )
            interpretation = await interpret_diagnostics(
                inc.fault_category or "unknown", host, diagnostic_outputs
            )
            return {"ai_interpretation": interpretation or "AI engine unavailable.", "success": True}

        elif fn_name == "clear_old_logs":
            return await clear_old_logs(host, user, key_path, port)

        elif fn_name == "clear_tmp_files":
            return await clear_tmp_files(host, user, key_path, port)

        elif fn_name == "clear_memory_cache":
            return await clear_memory_cache(host, user, key_path, port)

        elif fn_name == "kill_top_process":
            return await kill_top_process(host, user, key_path, port)

        elif fn_name == "restart_service":
            return await restart_service(host, service, user, key_path, port)

        elif fn_name == "restart_db_service":
            db_type = _guess_db_type(service, inc.title)
            svc     = {"mysql":"mysql","postgres":"postgresql","postgresql":"postgresql",
                       "mongodb":"mongod","redis":"redis-server"}.get(db_type, db_type)
            return await restart_service(host, svc, user, key_path, port)

        elif fn_name == "verify_disk":
            return await verify_disk_usage(host, user, key_path, port)

        elif fn_name == "verify_cpu":
            return await verify_cpu_usage(host, user, key_path, port)

        elif fn_name == "verify_memory":
            return await verify_memory_usage(host, user, key_path, port)

        elif fn_name == "verify_service":
            return await verify_service_running(host, service, user, key_path, port)

        elif fn_name == "escalate_l3":
            from backend.agent.llm import write_escalation_brief
            steps = await self._get_steps_summary(inc.id, db)
            brief = await write_escalation_brief(
                inc.number, inc.title, host,
                inc.fault_category or "unknown",
                steps, ai_interpretation,
            )
            return {"output": brief, "success": True}

        else:
            return {"output": f"Unknown step: {fn_name}", "success": False, "error": f"No handler for {fn_name}"}

    # ── Lifecycle helpers ──────────────────────────────────────────────────────

    async def _set_sla(self, inc: Incident, db: AsyncSession) -> None:
        """Calculate and set SLA response/resolve deadlines."""
        priority = inc.priority or "p3"
        r = await db.execute(
            select(SLAPolicy).where(
                SLAPolicy.priority == priority,
                SLAPolicy.customer == None,
            )
        )
        policy = r.scalar_one_or_none()
        if policy:
            now = datetime.utcnow()
            inc.sla_response_due = now + timedelta(minutes=policy.response_minutes)
            inc.sla_resolve_due  = now + timedelta(minutes=policy.resolve_minutes)

    async def _mark_resolved(self, inc: Incident, db: AsyncSession) -> None:
        """Mark incident resolved and record in resolutions table."""
        inc.status      = IncidentStatus.RESOLVED
        inc.resolved_at = datetime.utcnow()
        inc.resolved_by = "agent_l1"
        if not inc.resolution:
            inc.resolution = f"Resolved automatically by AMFI agent (fault: {inc.fault_category})"

        # Record in agent memory
        time_to_fix = None
        if inc.created_at:
            delta = datetime.utcnow() - inc.created_at
            time_to_fix = round(delta.total_seconds() / 60, 1)

        db.add(Resolution(
            incident_id       = inc.id,
            host              = inc.affected_host,
            fault_category    = inc.fault_category,
            fix_action        = inc.resolution[:255] if inc.resolution else None,
            success           = True,
            time_to_fix_min   = time_to_fix,
            resolved_at_level = "agent_l1",
        ))

        # Export as training data
        try:
            from backend.services.training.collector import export_resolved_incident
            await export_resolved_incident(inc.id, db)
        except Exception as e:
            logger.debug("Training export failed: %s", e)

        # Send notification
        try:
            from backend.services.notifications.sender import notify_resolved
            await notify_resolved(inc)
        except Exception as e:
            logger.debug("Notification failed: %s", e)

        logger.info("%s RESOLVED in %.0f min", inc.number, time_to_fix or 0)

    async def _escalate_l3(self, inc: Incident, db: AsyncSession, reason: str = "") -> None:
        """Escalate incident to L3 engineers."""
        inc.status = IncidentStatus.L3_ESCALATED
        if not inc.root_cause:
            inc.root_cause = reason

        # ── CRITICAL: commit status change NOW, before the Ollama call ───────
        # autoflush=True would flush dirty objects on the next SELECT, acquiring
        # a SQLite write lock.  The Ollama brief can take 30-120 s, which holds
        # that lock and times out any concurrent incident-create requests.
        # Committing here releases the lock immediately.
        await db.commit()

        # Generate escalation brief if needed (outside the write-lock window)
        if not inc.resolution:
            try:
                from backend.agent.llm import write_escalation_brief
                steps   = await self._get_steps_summary(inc.id, db)
                brief   = await write_escalation_brief(
                    inc.number, inc.title,
                    inc.affected_host or "unknown",
                    inc.fault_category or "unknown",
                    steps, reason,
                )
                inc.resolution = f"L3 ESCALATED: {brief}" if brief else f"L3 ESCALATED: {reason}"
            except Exception:
                inc.resolution = f"L3 ESCALATED: {reason}"

        try:
            from backend.services.notifications.sender import notify_escalation
            await notify_escalation(inc, reason)
        except Exception as e:
            logger.debug("Escalation notification failed: %s", e)

        # Create ITSM tickets in all configured platforms
        try:
            from backend.services.itsm.connectors import create_itsm_ticket
            ticket_refs = await create_itsm_ticket(inc)
            if ticket_refs:
                tickets_str = ", ".join(f"{k}:{v}" for k, v in ticket_refs.items())
                logger.info("%s ITSM tickets created: %s", inc.number, tickets_str)
                if inc.resolution:
                    inc.resolution += f" | Tickets: {tickets_str}"
                else:
                    inc.resolution = f"L3 ESCALATED | Tickets: {tickets_str}"
        except Exception as e:
            logger.debug("ITSM ticket creation failed: %s", e)

        logger.warning("%s ESCALATED to L3: %s", inc.number, reason[:120])

    # ── Approval helpers ───────────────────────────────────────────────────────

    async def _get_approval(
        self,
        incident_id: int,
        fn_name:     str,
        db:          AsyncSession,
    ) -> Optional[Approval]:
        """Return the most recent Approval for this incident + action, or None."""
        r = await db.execute(
            select(Approval)
            .where(Approval.incident_id == incident_id, Approval.action == fn_name)
            .order_by(Approval.created_at.desc())
        )
        return r.scalars().first()

    async def _request_approval(
        self,
        inc:     Incident,
        step:    dict,
        seq:     int,
        db:      AsyncSession,
    ) -> None:
        """Create an Approval record, set L1_WAITING, and notify operators."""
        fn_name = step["fn"]

        # Idempotent: don't create a second pending approval for the same action
        existing = await self._get_approval(inc.id, fn_name, db)
        if existing and existing.status == "pending":
            inc.status = IncidentStatus.L1_WAITING
            await db.commit()
            logger.info(
                "%s already waiting for approval of '%s' (token: %s)",
                inc.number, fn_name, existing.token,
            )
            return

        steps_so_far = await self._get_steps_summary(inc.id, db)

        approval = Approval(
            incident_id      = inc.id,
            action           = fn_name,
            host             = inc.affected_host,
            risk_level       = step.get("risk", "high"),
            reason           = step.get("reason", f"Action '{fn_name}' is high-risk and requires human approval"),
            rollback         = step.get("rollback", "Manually revert the change if it causes issues"),
            incident_summary = f"{inc.number}: {inc.title[:250]}",
            steps_so_far     = steps_so_far,
            expires_at       = datetime.utcnow() + timedelta(hours=4),
        )
        db.add(approval)
        inc.status = IncidentStatus.L1_WAITING
        await db.commit()
        await db.refresh(approval)

        logger.warning(
            "%s PAUSED at step %d — awaiting approval for '%s' (token: %s)",
            inc.number, seq, fn_name, approval.token,
        )

        # Notify operators
        try:
            from backend.services.notifications.sender import notify_approval_required
            await notify_approval_required(inc, approval)
        except Exception as e:
            logger.debug("Approval notification failed: %s", e)

        # Broadcast to WebSocket clients
        try:
            from backend.routers.ws import manager
            await manager.broadcast({
                "type": "approval_required",
                "data": {
                    "incident_id":     inc.id,
                    "incident_number": inc.number,
                    "action":          fn_name,
                    "risk_level":      approval.risk_level,
                    "token":           approval.token,
                    "host":            inc.affected_host,
                },
            })
        except Exception:
            pass

    # ── Database helpers ───────────────────────────────────────────────────────

    async def _get_incident(self, incident_id: int, db: AsyncSession) -> Optional[Incident]:
        r = await db.execute(select(Incident).where(Incident.id == incident_id))
        return r.scalar_one_or_none()

    async def _get_host(self, hostname: str, db: AsyncSession) -> Optional[Host]:
        r = await db.execute(select(Host).where(Host.hostname == hostname))
        return r.scalar_one_or_none()

    async def _count_steps(self, incident_id: int, db: AsyncSession) -> int:
        from sqlalchemy import func
        r = await db.execute(
            select(func.count(IncidentStep.id))
            .where(IncidentStep.incident_id == incident_id)
        )
        return r.scalar() or 0

    async def _add_step(self, db: AsyncSession, incident_id: int, **kwargs) -> IncidentStep:
        step = IncidentStep(incident_id=incident_id, **kwargs)
        db.add(step)
        await db.flush()
        return step

    async def _get_steps_summary(self, incident_id: int, db: AsyncSession) -> list[dict]:
        r = await db.execute(
            select(IncidentStep)
            .where(IncidentStep.incident_id == incident_id)
            .order_by(IncidentStep.sequence)
        )
        return [
            {
                "sequence":   s.sequence,
                "action":     s.action,
                "success":    s.success,
                "raw_output": (s.raw_output or "")[:300],
            }
            for s in r.scalars().all()
        ]


# ── Utilities ──────────────────────────────────────────────────────────────────

def _guess_db_type(service: str, title: str) -> str:
    """Infer database type from service name or alert title."""
    text = f"{service} {title}".lower()
    for db_type in ("mysql", "postgresql", "postgres", "mongodb", "redis", "cassandra", "oracle"):
        if db_type in text:
            return db_type
    return "postgresql"  # default
