"""
Module 4 — Decision Engine

Evaluates rules in order and routes each incident to one of four paths:
  Path A — Ticket:         create incident, assign to team
  Path B — Auto Remediate: run Ansible/SSH/Terraform fix
  Path C — Notify:         alert via Slack/Teams/PagerDuty
  Path D — Escalate:       SLA breach → escalate to L2/L3

Rules evaluated (priority order):
  1. If severity=CRITICAL and known auto-fix exists → Path B
  2. If severity=CRITICAL and no auto-fix → Path A + Path C + Path D
  3. If blast_radius > 5 → Path A + Path C (multi-service impact)
  4. If severity=WARNING and business_hours → Path A (ticket only)
  5. If severity=INFO → Path C (notification only)
  6. Default → Path A

Also sets:
  - Incident priority based on severity + impact_score
  - SLA deadline based on priority
  - requires_approval flag for risky remediations
"""
import logging
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.all_models import (
    CorrelatedEvent, EnrichedEvent, RawEvent, Incident,
    IncidentStatus, IncidentPriority, DecisionPath, Severity
)
from backend.config import get_settings

logger = logging.getLogger("amfi.decision")
settings = get_settings()


# Known auto-remediable conditions: (keyword_in_title, action, type, requires_approval)
AUTO_REMEDIATION_RULES = [
    ("high cpu",         "reduce_cpu_load",      "ansible",    False),
    ("cpu usage",        "reduce_cpu_load",      "ansible",    False),
    ("disk full",        "clear_disk_space",     "python_ssh", False),
    ("disk almost",      "clear_disk_space",     "python_ssh", False),
    ("memory",           "clear_memory_cache",   "python_ssh", False),
    ("oom",              "clear_memory_cache",   "python_ssh", False),
    ("service down",     "restart_service",      "ansible",    False),
    ("service failed",   "restart_service",      "ansible",    False),
    ("nginx",            "restart_service",      "ansible",    False),
    ("apache",           "restart_service",      "ansible",    False),
    ("connection refused","restart_service",     "ansible",    False),
    ("port unreachable", "bounce_port",          "python_ssh", True),   # needs approval
    ("instance down",    "check_and_restart_vm", "terraform",  True),   # needs approval
    ("interface down",   "bounce_interface",     "ansible",    True),   # needs approval
]

PRIORITY_MAP = {
    Severity.CRITICAL: IncidentPriority.CRITICAL,
    Severity.MAJOR:    IncidentPriority.HIGH,
    Severity.MINOR:    IncidentPriority.MEDIUM,
    Severity.WARNING:  IncidentPriority.MEDIUM,
    Severity.INFO:     IncidentPriority.LOW,
    Severity.UNKNOWN:  IncidentPriority.LOW,
}


class DecisionEngine:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def decide(self, correlated: CorrelatedEvent) -> Incident:
        enriched: EnrichedEvent = correlated.enriched_event
        raw: RawEvent           = enriched.raw_event

        severity     = raw.severity
        impact_score = enriched.impact_score or 0.0
        blast_radius = enriched.blast_radius or 0
        title        = raw.title or ""
        title_lower  = title.lower()

        # ── Determine priority ────────────────────────────────────────────────
        priority = PRIORITY_MAP.get(severity, IncidentPriority.MEDIUM)
        # Bump priority if high impact score
        if impact_score >= 8.0 and priority != IncidentPriority.CRITICAL:
            priority = IncidentPriority.HIGH

        # ── Check for auto-remediation match ──────────────────────────────────
        auto_fix     = None
        fix_type     = None
        needs_approval = False
        for keyword, action, rem_type, req_approval in AUTO_REMEDIATION_RULES:
            if keyword in title_lower:
                auto_fix       = action
                fix_type       = rem_type
                needs_approval = req_approval
                break

        # ── Decide path ───────────────────────────────────────────────────────
        if auto_fix and severity in (Severity.CRITICAL, Severity.MAJOR):
            path   = DecisionPath.AUTO_REMEDIATE
            reason = f"Auto-fix available: {auto_fix} (type={fix_type})"
        elif blast_radius > 5:
            path   = DecisionPath.TICKET
            reason = f"High blast radius ({blast_radius} services) — manual review needed"
        elif severity == Severity.INFO:
            path   = DecisionPath.NOTIFY
            reason = "Informational — notification only"
        else:
            path   = DecisionPath.TICKET
            reason = "Standard ticket workflow"

        # ── SLA deadline ──────────────────────────────────────────────────────
        sla_minutes = {
            IncidentPriority.CRITICAL: settings.sla_critical_minutes,
            IncidentPriority.HIGH:     settings.sla_high_minutes,
            IncidentPriority.MEDIUM:   settings.sla_medium_minutes,
            IncidentPriority.LOW:      settings.sla_low_minutes,
        }.get(priority, settings.sla_medium_minutes)
        sla_deadline = datetime.utcnow() + timedelta(minutes=sla_minutes)

        # ── Assign team ───────────────────────────────────────────────────────
        team = self._assign_team(enriched, raw)

        incident = Incident(
            correlated_event_id = correlated.id,
            title               = title,
            description         = raw.message,
            status              = IncidentStatus.NEW,
            priority            = priority,
            source              = str(raw.source),
            decision_path       = path,
            decision_reason     = reason,
            auto_remediate      = (auto_fix is not None),
            requires_approval   = needs_approval,
            assigned_team       = team,
            sla_deadline        = sla_deadline,
            created_by          = "system",
        )
        self.db.add(incident)
        await self.db.flush()

        logger.info(
            "Decision: incident_id=%s priority=%s path=%s team=%s auto_fix=%s",
            incident.id, priority, path, team, auto_fix
        )
        return incident

    def _assign_team(self, enriched: EnrichedEvent, raw: RawEvent) -> str:
        ci_type = (enriched.ci_type or "").lower()
        title   = (raw.title or "").lower()
        if any(k in ci_type for k in ("switch", "router", "firewall", "aci", "sdwan")):
            return "network-ops"
        if any(k in ci_type for k in ("san", "storage")):
            return "storage-ops"
        if any(k in title for k in ("database", "mysql", "postgres", "oracle")):
            return "dba-team"
        if any(k in title for k in ("kubernetes", "docker", "container", "k8s")):
            return "platform-team"
        return "server-ops"
