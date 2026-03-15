"""
Pipeline Orchestrator — The glue between all 8 modules.

Takes a validated RawEvent and runs it through:
  M1 → M2 → M3 → M4 → M5 (if needed) → M6 (if auto) → M7 → continuous poll

Also runs the SLA checker and remediation poller as background tasks.
"""
import asyncio
import logging
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.database import AsyncSessionLocal
from backend.models.all_models import (
    RawEvent, RawEventStatus, Incident,
    RemediationJob, RemediationStatus, DecisionPath,
    IncidentStatus
)
from backend.services.enrichment_service    import EnrichmentService
from backend.services.correlation_service   import CorrelationService
from backend.services.decision_service      import DecisionEngine
from backend.services.diagnostics_service   import DiagnosticsService
from backend.services.remediation_service   import RemediationService
from backend.services.notification_service  import NotificationService
from backend.config import get_settings

logger   = logging.getLogger("amfi.pipeline")
settings = get_settings()


class PipelineOrchestrator:

    def __init__(self, db: AsyncSession):
        self.db   = db
        self.enrich    = EnrichmentService(db)
        self.correlate = CorrelationService(db)
        self.decide    = DecisionEngine(db)
        self.diagnose  = DiagnosticsService(db)
        self.remediate = RemediationService(db)
        self.notify    = NotificationService(db)

    async def process(self, raw_event: RawEvent):
        """Full pipeline: M2 → M3 → M4 → M5 → M6 → M7."""
        logger.info("Pipeline START: raw_event_id=%s", raw_event.id)

        try:
            # M2 — Enrich
            enriched = await self.enrich.enrich(raw_event)
            await self.db.commit()

            # M3 — Correlate
            correlated = await self.correlate.correlate(enriched)
            await self.db.commit()

            # Skip if suppressed as duplicate symptom (root cause already exists)
            from backend.models.all_models import CorrelationStatus
            if correlated.correlation_status == CorrelationStatus.SYMPTOM:
                logger.info("Event %s is a symptom — root cause incident already exists", raw_event.id)
                return None

            # M4 — Decision
            incident = await self.decide.decide(correlated)
            await self.db.commit()

            # M7 — Notify immediately on creation
            await self.notify.notify(incident, event="created")
            await self.db.commit()

            # M5 — Diagnostics (async, doesn't block notification)
            if incident.decision_path != DecisionPath.NOTIFY:
                asyncio.create_task(self._run_diagnostics_async(incident.id))

            # M6 — Auto-remediation (if decision engine chose it)
            if incident.auto_remediate and incident.decision_path == DecisionPath.AUTO_REMEDIATE:
                asyncio.create_task(self._run_remediation_async(incident.id))

            logger.info("Pipeline END: incident_id=%s path=%s priority=%s",
                        incident.id, incident.decision_path, incident.priority)
            return incident

        except Exception as e:
            logger.exception("Pipeline failed for raw_event_id=%s: %s", raw_event.id, e)
            return None

    async def _run_diagnostics_async(self, incident_id: int):
        """Run diagnostics in background without blocking the HTTP response."""
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Incident).where(Incident.id == incident_id))
            incident = result.scalar_one_or_none()
            if not incident:
                return
            try:
                svc = DiagnosticsService(db)
                await svc.run(incident)
                await db.commit()
                logger.info("Diagnostics complete for incident %s", incident_id)
            except Exception as e:
                logger.error("Diagnostics error for incident %s: %s", incident_id, e)

    async def _run_remediation_async(self, incident_id: int):
        """Run remediation in background."""
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Incident).where(Incident.id == incident_id))
            incident = result.scalar_one_or_none()
            if not incident:
                return
            try:
                svc = RemediationService(db)
                job = await svc.create_job(incident)
                await db.commit()
                job = await svc.execute(job)
                await db.commit()
                logger.info("Remediation job %s started for incident %s", job.id, incident_id)
            except Exception as e:
                logger.error("Remediation error for incident %s: %s", incident_id, e)


# ── Background Tasks (run by the scheduler) ───────────────────────────────────

async def run_pending_raw_events():
    """
    Pick up all VALIDATED raw events not yet processed and run them
    through the pipeline. Called every 5 seconds by the scheduler.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(RawEvent)
            .where(RawEvent.status == RawEventStatus.VALIDATED)
            .limit(50)
        )
        events = result.scalars().all()
        if not events:
            return

        logger.info("Processing %d pending raw events", len(events))
        orch = PipelineOrchestrator(db)
        for event in events:
            await orch.process(event)
        await db.commit()


async def run_sla_checks():
    """Check all open incidents for SLA breaches. Called every minute."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Incident).where(
                Incident.status.notin_([IncidentStatus.RESOLVED, IncidentStatus.CLOSED])
            )
        )
        incidents = result.scalars().all()
        svc = NotificationService(db)
        for incident in incidents:
            await svc.check_sla_and_escalate(incident)
        await db.commit()


async def run_remediation_polling():
    """Poll all VERIFYING remediation jobs. Called every N seconds."""
    async with AsyncSessionLocal() as db:
        now = datetime.utcnow()
        result = await db.execute(
            select(RemediationJob).where(
                RemediationJob.status == RemediationStatus.VERIFYING,
                RemediationJob.next_poll_at <= now,
            )
        )
        jobs = result.scalars().all()
        if not jobs:
            return
        svc = RemediationService(db)
        for job in jobs:
            await svc.verify_and_poll(job)
        await db.commit()
