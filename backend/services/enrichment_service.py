"""
Module 2 — Event Enrichment Service

For every validated RawEvent:
  1. CMDB Lookup      — find the CI record for the affected host
  2. History Check    — how many similar incidents in the past?
  3. Service Map      — which business service is affected?
  4. Blast Radius     — how many downstream services are impacted?
  5. Impact Score     — numeric 0-10 based on criticality + blast radius
"""
import logging
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from backend.models.all_models import (
    RawEvent, RawEventStatus, EnrichedEvent,
    ConfigItem, Incident, IncidentStatus
)

logger = logging.getLogger("amfi.enrichment")


class EnrichmentService:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def enrich(self, raw_event: RawEvent) -> EnrichedEvent:
        """Main entry: enrich a raw event and return EnrichedEvent."""

        # 1. CMDB Lookup
        ci = await self._lookup_cmdb(raw_event.affected_host)

        # 2. Historical context
        similar_count, last_similar = await self._get_history(raw_event)

        # 3. Blast radius (from CI dependencies)
        blast_radius, dependent_services = self._calc_blast_radius(ci)

        # 4. Impact score
        impact_score = self._calc_impact_score(raw_event, ci, blast_radius)

        # 5. Affected users estimate
        affected_users = self._estimate_affected_users(ci, blast_radius)

        enriched = EnrichedEvent(
            raw_event_id           = raw_event.id,
            ci_id                  = ci.ci_id if ci else None,
            ci_name                = ci.hostname if ci else raw_event.affected_host,
            ci_type                = ci.ci_type if ci else "unknown",
            ci_owner               = ci.owner if ci else None,
            ci_environment         = ci.environment if ci else "unknown",
            ci_location            = ci.location if ci else None,
            business_service       = ci.business_service if ci else None,
            service_criticality    = ci.criticality if ci else "medium",
            dependent_services     = dependent_services,
            blast_radius           = blast_radius,
            impact_score           = impact_score,
            affected_users         = affected_users,
            similar_incidents_count= similar_count,
            last_similar_incident  = last_similar,
            known_issue            = similar_count > 3,
            enriched_at            = datetime.utcnow(),
        )
        self.db.add(enriched)

        # Mark raw event as forwarded
        raw_event.status       = RawEventStatus.FORWARDED
        raw_event.forwarded_at = datetime.utcnow()

        await self.db.flush()
        logger.info(
            "Enriched event id=%s ci=%s blast_radius=%s impact=%.1f",
            raw_event.id, enriched.ci_name, blast_radius, impact_score
        )
        return enriched

    # ── CMDB lookup ───────────────────────────────────────────────────────────

    async def _lookup_cmdb(self, hostname: str) -> ConfigItem | None:
        if not hostname:
            return None
        # Try exact hostname match first, then IP
        result = await self.db.execute(
            select(ConfigItem).where(
                (ConfigItem.hostname == hostname) |
                (ConfigItem.ip_address == hostname)
            ).limit(1)
        )
        ci = result.scalar_one_or_none()
        if not ci:
            # Partial match (e.g. "server01:9100" → "server01")
            base_host = hostname.split(":")[0]
            result = await self.db.execute(
                select(ConfigItem).where(
                    ConfigItem.hostname.contains(base_host)
                ).limit(1)
            )
            ci = result.scalar_one_or_none()
        return ci

    # ── Historical context ────────────────────────────────────────────────────

    async def _get_history(self, raw_event: RawEvent):
        """How many incidents on the same host in the past 30 days?"""
        cutoff = datetime.utcnow() - timedelta(days=30)
        result = await self.db.execute(
            select(func.count(Incident.id)).where(
                Incident.created_at >= cutoff,
                Incident.source == str(raw_event.affected_host),
            )
        )
        count = result.scalar() or 0

        # Date of last similar incident
        last_result = await self.db.execute(
            select(Incident.created_at)
            .where(Incident.created_at >= cutoff)
            .order_by(Incident.created_at.desc())
            .limit(1)
        )
        last_date = last_result.scalar_one_or_none()
        return count, last_date

    # ── Blast radius ──────────────────────────────────────────────────────────

    def _calc_blast_radius(self, ci: ConfigItem | None):
        if not ci or not ci.supports:
            return 0, []
        dependents = ci.supports if isinstance(ci.supports, list) else []
        return len(dependents), dependents

    # ── Impact score 0–10 ─────────────────────────────────────────────────────

    def _calc_impact_score(self, raw_event: RawEvent, ci: ConfigItem | None, blast_radius: int) -> float:
        score = 0.0
        sev_scores = {
            "critical": 4.0, "major": 3.0, "minor": 2.0,
            "warning": 1.0, "info": 0.5, "unknown": 1.0,
        }
        score += sev_scores.get(str(raw_event.severity), 1.0)

        if ci:
            crit_scores = {"critical": 3.0, "high": 2.0, "medium": 1.0, "low": 0.5}
            score += crit_scores.get(ci.criticality or "medium", 1.0)
            if ci.environment == "prod":
                score += 2.0
            elif ci.environment == "staging":
                score += 0.5

        score += min(blast_radius * 0.3, 3.0)
        return round(min(score, 10.0), 2)

    def _estimate_affected_users(self, ci: ConfigItem | None, blast_radius: int) -> int:
        if not ci:
            return 0
        base = {"critical": 500, "high": 200, "medium": 50, "low": 10}.get(
            ci.criticality or "medium", 50
        )
        return base + (blast_radius * 20)
