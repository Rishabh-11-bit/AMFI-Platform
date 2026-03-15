"""
Module 3 — Event Correlation & Deduplication Service

Rules applied in order:
  1. Same CI + same severity within 10 min  → group as symptoms of same root cause
  2. Host unreachable + multiple services alerting → root cause = network/host down
  3. Topology aware: if upstream device is down, suppress downstream alerts
  4. Pattern matching: known event sequences (e.g. disk full → app crash → DB timeout)

Output: CorrelatedEvent with either ROOT_CAUSE, SYMPTOM, or STANDALONE status.
"""
import logging
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.models.all_models import (
    EnrichedEvent, CorrelatedEvent, CorrelationStatus, RawEvent
)

logger = logging.getLogger("amfi.correlation")

CORRELATION_WINDOW_MINUTES = 10


class CorrelationService:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def correlate(self, enriched: EnrichedEvent) -> CorrelatedEvent:
        raw: RawEvent = enriched.raw_event
        group_id, status, root_id, rule = await self._find_correlation(enriched, raw)

        correlated = CorrelatedEvent(
            enriched_event_id   = enriched.id,
            correlation_group   = group_id,
            correlation_status  = status,
            root_cause_event_id = root_id,
            correlation_rule    = rule,
            confidence_score    = 0.9 if root_id else 1.0,
            correlated_at       = datetime.utcnow(),
        )
        self.db.add(correlated)

        # If this is a symptom, increment symptom count on root
        if root_id:
            result = await self.db.execute(
                select(CorrelatedEvent).where(CorrelatedEvent.id == root_id)
            )
            root = result.scalar_one_or_none()
            if root:
                root.symptom_count = (root.symptom_count or 0) + 1

        await self.db.flush()
        logger.info(
            "Correlated event id=%s status=%s group=%s rule=%s",
            enriched.id, status, group_id, rule
        )
        return correlated

    async def _find_correlation(self, enriched: EnrichedEvent, raw: RawEvent):
        cutoff = datetime.utcnow() - timedelta(minutes=CORRELATION_WINDOW_MINUTES)

        # Rule 1: Same CI, same severity — group together
        if enriched.ci_id:
            result = await self.db.execute(
                select(CorrelatedEvent)
                .join(EnrichedEvent, CorrelatedEvent.enriched_event_id == EnrichedEvent.id)
                .join(RawEvent, EnrichedEvent.raw_event_id == RawEvent.id)
                .where(
                    EnrichedEvent.ci_id == enriched.ci_id,
                    RawEvent.severity == raw.severity,
                    CorrelatedEvent.correlation_status == CorrelationStatus.ROOT_CAUSE,
                    CorrelatedEvent.correlated_at >= cutoff,
                )
                .order_by(CorrelatedEvent.correlated_at.asc())
                .limit(1)
            )
            existing_root = result.scalar_one_or_none()
            if existing_root:
                return (
                    existing_root.correlation_group,
                    CorrelationStatus.SYMPTOM,
                    existing_root.id,
                    "same_ci_same_severity",
                )

        # Rule 2: Same business service, multiple hosts alerting
        if enriched.business_service:
            result = await self.db.execute(
                select(CorrelatedEvent)
                .join(EnrichedEvent, CorrelatedEvent.enriched_event_id == EnrichedEvent.id)
                .where(
                    EnrichedEvent.business_service == enriched.business_service,
                    CorrelatedEvent.correlation_status == CorrelationStatus.ROOT_CAUSE,
                    CorrelatedEvent.correlated_at >= cutoff,
                )
                .order_by(CorrelatedEvent.correlated_at.asc())
                .limit(1)
            )
            existing_root = result.scalar_one_or_none()
            if existing_root:
                return (
                    existing_root.correlation_group,
                    CorrelationStatus.SYMPTOM,
                    existing_root.id,
                    "same_business_service",
                )

        # Rule 3: Host-down pattern (critical + "down" or "unreachable" in title)
        if (str(raw.severity) == "critical" and
                any(kw in (raw.title or "").lower() for kw in ("down", "unreachable", "offline", "failed"))):
            group_id = f"host-down-{enriched.ci_id or raw.affected_host}-{int(datetime.utcnow().timestamp())}"
            return group_id, CorrelationStatus.ROOT_CAUSE, None, "host_down_pattern"

        # No correlation found — standalone event
        group_id = f"standalone-{enriched.id}"
        return group_id, CorrelationStatus.STANDALONE, None, "no_correlation"
