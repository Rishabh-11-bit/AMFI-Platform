"""
AMFI v4 — Inbound Webhook Router
Receives push alerts from all monitoring platforms and creates incidents.

Supported sources:
  - Datadog           POST /webhook/datadog
  - Nagios / Icinga2  POST /webhook/nagios
  - New Relic         POST /webhook/newrelic
  - Dynatrace         POST /webhook/dynatrace
  - Grafana           POST /webhook/grafana
  - Splunk            POST /webhook/splunk
  - Elastic           POST /webhook/elastic
  - PRTG              POST /webhook/prtg

All endpoints return {"created": N, "incident_ids": [...], "skipped": M}
"""
import asyncio
import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from backend.database import get_db
from backend.models.models import Incident, IncidentStatus
from backend.config import get_settings

logger   = logging.getLogger("amfi.webhooks")
settings = get_settings()
router   = APIRouter(prefix="/webhook", tags=["webhooks"])


# ── Shared helpers ─────────────────────────────────────────────────────────────

async def _is_duplicate(source: str, source_id: str, db: AsyncSession) -> bool:
    r = await db.execute(
        select(Incident).where(
            Incident.source == source,
            Incident.source_alert_id == source_id,
            Incident.status.notin_(["resolved", "closed", "false_positive"]),
        )
    )
    return r.scalar_one_or_none() is not None


async def _create_incident(
    db:         AsyncSession,
    title:      str,
    description: str,
    host:       str,
    service:    str,
    source:     str,
    source_id:  str,
    raw_alert:  dict,
    priority:   Optional[str] = None,
) -> Optional[Incident]:
    """Create incident if not a duplicate. Returns the new Incident or None."""
    if await _is_duplicate(source, source_id, db):
        return None

    from sqlalchemy.exc import IntegrityError
    from backend.agent.classifier import classify as _classify

    # Auto-classify
    cat, prio = _classify(title, description or "")
    final_priority = priority or prio.value

    # SLA
    from backend.models.models import SLAPolicy
    from datetime import timedelta
    sla_r = await db.execute(
        select(SLAPolicy).where(SLAPolicy.priority == final_priority, SLAPolicy.customer == None)
    )
    sla_policy        = sla_r.scalar_one_or_none()
    _now              = datetime.utcnow()
    sla_response_due  = _now + timedelta(minutes=sla_policy.response_minutes) if sla_policy else None
    sla_resolve_due   = _now + timedelta(minutes=sla_policy.resolve_minutes)  if sla_policy else None

    for _retry in range(5):
        count_r = await db.execute(select(func.count(Incident.id)))
        count   = count_r.scalar() or 0
        number  = f"INC-{count + 1:04d}"
        inc = Incident(
            number           = number,
            title            = title[:500],
            description      = description[:2000] if description else None,
            affected_host    = host[:255] if host else None,
            affected_service = service[:255] if service else None,
            source           = source,
            source_alert_id  = source_id,
            fault_category   = cat.value,
            priority         = final_priority,
            status           = IncidentStatus.NEW,
            sla_response_due = sla_response_due,
            sla_resolve_due  = sla_resolve_due,
            raw_alert        = raw_alert,
        )
        db.add(inc)
        try:
            await db.commit()
            await db.refresh(inc)
            logger.info("Webhook: created %s from %s: %s", number, source, title[:60])
            return inc
        except IntegrityError:
            await db.rollback()
            await asyncio.sleep(0.05 * (_retry + 1))
            continue
    return None


async def _run_agent(inc_id: int) -> None:
    from backend.database import AsyncSessionLocal
    from backend.agent.executor import AgentExecutor
    async with AsyncSessionLocal() as db:
        executor = AgentExecutor()
        await executor.run(inc_id, db)


# ── GET /webhook/health ────────────────────────────────────────────────────────

@router.get("/health", tags=["webhooks"])
async def webhook_health():
    """Returns which webhook endpoints are active and configured inbound sources."""
    return {
        "endpoints": {
            "datadog":   "/webhook/datadog",
            "nagios":    "/webhook/nagios",
            "newrelic":  "/webhook/newrelic",
            "dynatrace": "/webhook/dynatrace",
            "grafana":   "/webhook/grafana",
            "splunk":    "/webhook/splunk",
            "elastic":   "/webhook/elastic",
            "prtg":      "/webhook/prtg",
        },
        "configured": {
            "datadog":   bool(settings.datadog_api_key),
            "nagios":    bool(settings.nagios_url or settings.icinga2_url),
            "newrelic":  bool(settings.newrelic_api_key),
            "dynatrace": bool(settings.dynatrace_url),
            "grafana":   bool(settings.grafana_url),
            "splunk":    bool(settings.splunk_hec_url),
            "elastic":   bool(settings.elastic_url),
        },
    }


# ── Datadog ────────────────────────────────────────────────────────────────────

class DatadogWebhook(BaseModel):
    id:          Optional[Any] = None
    title:       Optional[str] = None
    text:        Optional[str] = None
    alert_type:  Optional[str] = None   # error, warning, info, success
    host:        Optional[str] = None
    tags:        Optional[Any] = None   # string or list (Datadog sends both)
    aggreg_key:  Optional[str] = None
    event_type:  Optional[str] = None
    org:         Optional[dict] = None

    class Config:
        extra = "allow"


@router.post("/datadog")
async def webhook_datadog(
    payload:    DatadogWebhook,
    background: BackgroundTasks,
    db:         AsyncSession = Depends(get_db),
):
    """Receive Datadog alert webhook."""
    alert_type = (payload.alert_type or "").lower()
    if alert_type not in ("error", "warning"):
        return {"created": 0, "incident_ids": [], "skipped": 1, "reason": f"alert_type={alert_type} ignored"}

    title     = payload.title or "Datadog Alert"
    source_id = str(payload.aggreg_key or payload.id or f"dd-{title[:40]}")
    host      = payload.host or ""
    raw_tags  = payload.tags or ""
    tags      = ",".join(raw_tags) if isinstance(raw_tags, list) else str(raw_tags)

    inc = await _create_incident(
        db,
        title       = title,
        description = payload.text or "",
        host        = host,
        service     = tags[:255],
        source      = "datadog_webhook",
        source_id   = source_id,
        raw_alert   = payload.model_dump(),
        priority    = "p1" if alert_type == "error" else "p2",
    )
    if inc:
        background.add_task(_run_agent, inc.id)
        return {"created": 1, "incident_ids": [inc.id], "skipped": 0}
    return {"created": 0, "incident_ids": [], "skipped": 1}


# ── Nagios / Icinga2 ──────────────────────────────────────────────────────────

class NagiosWebhook(BaseModel):
    hostname:         Optional[str] = None
    servicedesc:      Optional[str] = None
    servicestate:     Optional[str] = None   # CRITICAL, WARNING, OK, UNKNOWN
    serviceoutput:    Optional[str] = None
    hoststate:        Optional[str] = None   # DOWN, UP, UNREACHABLE
    hostoutput:       Optional[str] = None
    notificationtype: Optional[str] = None   # PROBLEM, RECOVERY, ACKNOWLEDGEMENT
    contactemail:     Optional[str] = None
    datetime:         Optional[str] = None

    class Config:
        extra = "allow"


@router.post("/nagios")
async def webhook_nagios(
    payload:    NagiosWebhook,
    background: BackgroundTasks,
    db:         AsyncSession = Depends(get_db),
):
    """Receive Nagios/Icinga2 notification webhook."""
    notif_type = (payload.notificationtype or "").upper()
    if notif_type in ("RECOVERY", "ACKNOWLEDGEMENT", "FLAPPINGSTART", "FLAPPINGSTOP"):
        return {"created": 0, "incident_ids": [], "skipped": 1, "reason": f"type={notif_type} ignored"}

    host    = payload.hostname or "unknown"
    service = payload.servicedesc or ""
    state   = payload.servicestate or payload.hoststate or "CRITICAL"
    output  = payload.serviceoutput or payload.hostoutput or ""

    if service:
        title     = f"{service} {state} on {host}"
        source_id = f"nagios-{host}-{service}"
    else:
        title     = f"Host {host} is {state}"
        source_id = f"nagios-host-{host}"

    priority = "p1" if state in ("CRITICAL", "DOWN", "UNREACHABLE") else "p2"

    inc = await _create_incident(
        db,
        title       = title,
        description = output,
        host        = host,
        service     = service,
        source      = "nagios_webhook",
        source_id   = source_id,
        raw_alert   = payload.model_dump(),
        priority    = priority,
    )
    if inc:
        background.add_task(_run_agent, inc.id)
        return {"created": 1, "incident_ids": [inc.id], "skipped": 0}
    return {"created": 0, "incident_ids": [], "skipped": 1}


# ── New Relic ─────────────────────────────────────────────────────────────────

class NewRelicWebhook(BaseModel):
    policy_name:   Optional[str] = None
    condition_name: Optional[str] = None
    current_state: Optional[str] = None   # open, acknowledged, closed
    details:       Optional[str] = None
    targets:       Optional[list] = None
    runbook_url:   Optional[str] = None
    severity:      Optional[str] = None   # CRITICAL, WARNING, INFO
    incident_url:  Optional[str] = None
    incident_id:   Optional[Any] = None

    class Config:
        extra = "allow"


@router.post("/newrelic")
async def webhook_newrelic(
    payload:    NewRelicWebhook,
    background: BackgroundTasks,
    db:         AsyncSession = Depends(get_db),
):
    """Receive New Relic alert webhook."""
    state = (payload.current_state or "").lower()
    if state not in ("open", "activated"):
        return {"created": 0, "incident_ids": [], "skipped": 1, "reason": f"state={state} ignored"}

    targets   = payload.targets or [{}]
    host_name = targets[0].get("name", "") if targets else ""
    title     = f"{payload.condition_name or 'Alert'} on {host_name}" if host_name else (payload.condition_name or "New Relic Alert")
    source_id = str(payload.incident_id or f"nr-{payload.policy_name}-{payload.condition_name}")
    severity  = (payload.severity or "CRITICAL").upper()
    priority  = "p1" if severity == "CRITICAL" else "p2"

    inc = await _create_incident(
        db,
        title       = title,
        description = (payload.details or "")[:2000],
        host        = host_name,
        service     = payload.policy_name or "",
        source      = "newrelic_webhook",
        source_id   = source_id,
        raw_alert   = payload.model_dump(),
        priority    = priority,
    )
    if inc:
        background.add_task(_run_agent, inc.id)
        return {"created": 1, "incident_ids": [inc.id], "skipped": 0}
    return {"created": 0, "incident_ids": [], "skipped": 1}


# ── Dynatrace ─────────────────────────────────────────────────────────────────

class DynatraceWebhook(BaseModel):
    ProblemID:          Optional[str] = None
    ProblemTitle:       Optional[str] = None
    State:              Optional[str] = None    # OPEN, RESOLVED
    ProblemSeverity:    Optional[str] = None    # AVAILABILITY, ERROR, PERFORMANCE, RESOURCE_CONTENTION
    ImpactedEntities:   Optional[list] = None
    ProblemDetailsText: Optional[str] = None
    ProblemURL:         Optional[str] = None
    Tags:               Optional[str] = None

    class Config:
        extra = "allow"


@router.post("/dynatrace")
async def webhook_dynatrace(
    payload:    DynatraceWebhook,
    background: BackgroundTasks,
    db:         AsyncSession = Depends(get_db),
):
    """Receive Dynatrace problem webhook."""
    state = (payload.State or "").upper()
    if state != "OPEN":
        return {"created": 0, "incident_ids": [], "skipped": 1, "reason": f"State={state} ignored"}

    entities  = payload.ImpactedEntities or [{}]
    host_name = entities[0].get("name", "") if isinstance(entities[0], dict) else str(entities[0])
    title     = payload.ProblemTitle or "Dynatrace Problem"
    severity  = (payload.ProblemSeverity or "").upper()
    source_id = payload.ProblemID or f"dt-{title[:40]}"
    priority  = "p1" if severity in ("AVAILABILITY", "ERROR") else "p2"

    inc = await _create_incident(
        db,
        title       = f"{title} [{severity}]"[:500] if severity else title,
        description = payload.ProblemDetailsText or "",
        host        = host_name,
        service     = payload.Tags or "",
        source      = "dynatrace_webhook",
        source_id   = source_id,
        raw_alert   = payload.model_dump(),
        priority    = priority,
    )
    if inc:
        background.add_task(_run_agent, inc.id)
        return {"created": 1, "incident_ids": [inc.id], "skipped": 0}
    return {"created": 0, "incident_ids": [], "skipped": 1}


# ── Grafana ────────────────────────────────────────────────────────────────────

class GrafanaAlert(BaseModel):
    status:      Optional[str] = None
    labels:      Optional[dict] = None
    annotations: Optional[dict] = None
    fingerprint: Optional[str] = None
    startsAt:    Optional[str] = None
    endsAt:      Optional[str] = None
    generatorURL: Optional[str] = None

    class Config:
        extra = "allow"


class GrafanaWebhook(BaseModel):
    receiver:         Optional[str] = None
    status:           Optional[str] = None   # firing, resolved
    alerts:           Optional[list[GrafanaAlert]] = None
    groupLabels:      Optional[dict] = None
    commonLabels:     Optional[dict] = None
    commonAnnotations: Optional[dict] = None
    externalURL:      Optional[str] = None
    version:          Optional[str] = None
    groupKey:         Optional[str] = None

    class Config:
        extra = "allow"


@router.post("/grafana")
async def webhook_grafana(
    payload:    GrafanaWebhook,
    background: BackgroundTasks,
    db:         AsyncSession = Depends(get_db),
):
    """Receive Grafana unified alerting webhook (same format as Alertmanager)."""
    alerts    = payload.alerts or []
    created   = 0
    inc_ids   = []
    skipped   = 0

    for alert in alerts:
        if (alert.status or "").lower() != "firing":
            skipped += 1
            continue

        labels      = alert.labels or {}
        annotations = alert.annotations or {}
        alert_name  = labels.get("alertname", "Grafana Alert")
        instance    = (labels.get("instance", "") or "").split(":")[0]
        fingerprint = alert.fingerprint or f"grafana-{alert_name}-{instance}"
        source_id   = f"grafana-{fingerprint}"

        title = annotations.get("summary") or alert_name
        desc  = annotations.get("description", "")

        inc = await _create_incident(
            db,
            title       = title,
            description = desc,
            host        = instance or labels.get("host", ""),
            service     = labels.get("job", labels.get("service", "")),
            source      = "grafana_webhook",
            source_id   = source_id,
            raw_alert   = alert.model_dump(),
        )
        if inc:
            background.add_task(_run_agent, inc.id)
            inc_ids.append(inc.id)
            created += 1
        else:
            skipped += 1

    return {"created": created, "incident_ids": inc_ids, "skipped": skipped}


# ── Splunk ────────────────────────────────────────────────────────────────────

class SplunkWebhook(BaseModel):
    result:       Optional[dict] = None
    search_name:  Optional[str] = None
    owner:        Optional[str] = None
    app:          Optional[str] = None
    results_link: Optional[str] = None
    sid:          Optional[str] = None

    class Config:
        extra = "allow"


@router.post("/splunk")
async def webhook_splunk(
    payload:    SplunkWebhook,
    background: BackgroundTasks,
    db:         AsyncSession = Depends(get_db),
):
    """Receive Splunk alert webhook."""
    result    = payload.result or {}
    host_name = result.get("host", "")
    title     = payload.search_name or "Splunk Alert"
    source_id = payload.sid or f"splunk-{title[:40]}"
    desc      = f"Source: {result.get('source', '')} | App: {payload.app or ''}"

    inc = await _create_incident(
        db,
        title       = title,
        description = desc,
        host        = host_name,
        service     = result.get("sourcetype", ""),
        source      = "splunk_webhook",
        source_id   = source_id,
        raw_alert   = payload.model_dump(),
    )
    if inc:
        background.add_task(_run_agent, inc.id)
        return {"created": 1, "incident_ids": [inc.id], "skipped": 0}
    return {"created": 0, "incident_ids": [], "skipped": 1}


# ── Elastic / Kibana ──────────────────────────────────────────────────────────

class ElasticWebhook(BaseModel):
    alertId:          Optional[str] = None
    alertName:        Optional[str] = None
    spaceId:          Optional[str] = None
    tags:             Optional[list] = None
    alertInstanceId:  Optional[str] = None
    context:          Optional[dict] = None
    state:            Optional[dict] = None
    rule:             Optional[dict] = None

    class Config:
        extra = "allow"


@router.post("/elastic")
async def webhook_elastic(
    payload:    ElasticWebhook,
    background: BackgroundTasks,
    db:         AsyncSession = Depends(get_db),
):
    """Receive Elastic alerting webhook."""
    context   = payload.context or {}
    title     = payload.alertName or "Elastic Alert"
    host_name = context.get("host", context.get("hostname", ""))
    source_id = payload.alertId or payload.alertInstanceId or f"elastic-{title[:40]}"
    message   = context.get("message", "")

    inc = await _create_incident(
        db,
        title       = title,
        description = message[:2000],
        host        = host_name,
        service     = payload.spaceId or "",
        source      = "elastic_webhook",
        source_id   = source_id,
        raw_alert   = payload.model_dump(),
    )
    if inc:
        background.add_task(_run_agent, inc.id)
        return {"created": 1, "incident_ids": [inc.id], "skipped": 0}
    return {"created": 0, "incident_ids": [], "skipped": 1}


# ── PRTG ──────────────────────────────────────────────────────────────────────

class PRTGWebhook(BaseModel):
    device:   Optional[str] = None
    sensor:   Optional[str] = None
    status:   Optional[str] = None    # Down, Warning, Up, Unusual
    message:  Optional[str] = None
    datetime: Optional[str] = None
    sitename: Optional[str] = None
    name:     Optional[str] = None

    class Config:
        extra = "allow"


@router.post("/prtg")
async def webhook_prtg(
    payload:    PRTGWebhook,
    background: BackgroundTasks,
    db:         AsyncSession = Depends(get_db),
):
    """Receive PRTG sensor alert webhook."""
    status = (payload.status or "").lower()
    if status in ("up", "ok", "recovered"):
        return {"created": 0, "incident_ids": [], "skipped": 1, "reason": f"status={status} ignored"}

    device    = payload.device or payload.sitename or "unknown"
    sensor    = payload.sensor or payload.name or "sensor"
    title     = f"{sensor} {payload.status} on {device}"
    source_id = f"prtg-webhook-{device}-{sensor}"
    priority  = "p1" if status == "down" else "p2"

    inc = await _create_incident(
        db,
        title       = title,
        description = payload.message or "",
        host        = device,
        service     = sensor,
        source      = "prtg_webhook",
        source_id   = source_id,
        raw_alert   = payload.model_dump(),
        priority    = priority,
    )
    if inc:
        background.add_task(_run_agent, inc.id)
        return {"created": 1, "incident_ids": [inc.id], "skipped": 0}
    return {"created": 0, "incident_ids": [], "skipped": 1}
