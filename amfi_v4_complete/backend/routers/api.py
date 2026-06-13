"""
AMFI v4 — API Router
All REST endpoints consumed by the React frontend.
Prefix: /api  (mounted in main.py)
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Any

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import select, func, desc
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.config import get_settings
from backend.utils.crypto import encrypt_credential, decrypt_credential
from backend.models.models import (
    Incident, IncidentStep, IncidentStatus, Priority,
    Approval, Host, NMSSource, Resolution, SLAPolicy,
    AuditLog, User,
    MonitoredHost, MetricSample, ThresholdRule,
)

logger   = logging.getLogger("amfi.api")
settings = get_settings()
router   = APIRouter()


async def _ws_broadcast(event_type: str, data: dict):
    """Fire-and-forget WebSocket broadcast — silently swallows errors."""
    try:
        from backend.routers.ws import manager
        await manager.broadcast({"type": event_type, "data": data})
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# Pydantic schemas
# ══════════════════════════════════════════════════════════════════════════════

class IncidentCreate(BaseModel):
    title:            str
    description:      Optional[str] = None
    affected_host:    Optional[str] = None
    affected_service: Optional[str] = None
    source:           str           = "manual"
    priority:         Optional[str] = None
    fault_category:   Optional[str] = None

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("title must not be empty")
        return v.strip()

class HostCreate(BaseModel):
    hostname:          str
    ip_address:        Optional[str] = None
    os:                Optional[str] = None
    environment:       Optional[str] = "prod"
    criticality:       str           = "medium"
    business_service:  Optional[str] = None
    owner_email:       Optional[str] = None
    ssh_user:          str           = "root"
    ssh_key_path:      Optional[str] = None
    ssh_port:          int           = 22
    auto_remediate:    bool          = True
    approval_required: bool          = False
    never_touch:       bool          = False
    known_issues:      Optional[str] = None
    services:          Optional[list] = None

class NMSCreate(BaseModel):
    name:          str
    nms_type:      str
    base_url:      Optional[str] = None
    username:      Optional[str] = None
    password:      Optional[str] = None
    api_token:     Optional[str] = None
    enabled:       bool          = True
    poll_interval: int           = 300

class ApprovalDecision(BaseModel):
    decided_by:    Optional[str] = "operator"
    decision_note: Optional[str] = None

class WebhookAlertmanager(BaseModel):
    alerts:   list[dict] = []
    receiver: Optional[str] = None
    status:   Optional[str] = None


class MonitoredHostCreate(BaseModel):
    hostname:              str
    ip_address:            str
    display_name:          Optional[str] = None
    device_type:           str           = "linux"   # linux, windows, network, generic
    location:              Optional[str] = None
    environment:           str           = "prod"
    ssh_user:              str           = "root"
    ssh_port:              int           = 22
    ssh_key_path:          Optional[str] = None
    ssh_password:          Optional[str] = None       # encrypted at-rest
    snmp_community:        str           = "public"
    snmp_port:             int           = 161
    snmp_version:          str           = "2c"
    # SNMP v3 fields (only used when snmp_version == "3")
    snmp_v3_user:          Optional[str] = None
    snmp_v3_auth_protocol: str           = "SHA"
    snmp_v3_auth_key:      Optional[str] = None       # encrypted at-rest
    snmp_v3_priv_protocol: str           = "AES"
    snmp_v3_priv_key:      Optional[str] = None       # encrypted at-rest
    enabled:               bool          = True
    poll_interval:         int           = 60


class MonitoredHostUpdate(BaseModel):
    display_name:          Optional[str]  = None
    device_type:           Optional[str]  = None
    location:              Optional[str]  = None
    environment:           Optional[str]  = None
    ssh_user:              Optional[str]  = None
    ssh_port:              Optional[int]  = None
    ssh_key_path:          Optional[str]  = None
    ssh_password:          Optional[str]  = None
    snmp_community:        Optional[str]  = None
    snmp_port:             Optional[int]  = None
    snmp_version:          Optional[str]  = None
    snmp_v3_user:          Optional[str]  = None
    snmp_v3_auth_protocol: Optional[str]  = None
    snmp_v3_auth_key:      Optional[str]  = None
    snmp_v3_priv_protocol: Optional[str]  = None
    snmp_v3_priv_key:      Optional[str]  = None
    enabled:               Optional[bool] = None
    poll_interval:         Optional[int]  = None


class UserCreate(BaseModel):
    username:  str
    password:  str
    email:     Optional[str] = None
    full_name: Optional[str] = None
    role:      str           = "viewer"  # viewer | operator | admin

class UserUpdate(BaseModel):
    email:     Optional[str]  = None
    full_name: Optional[str]  = None
    role:      Optional[str]  = None
    is_active: Optional[bool] = None


class ThresholdRuleCreate(BaseModel):
    name:             str
    host_id:          Optional[int] = None
    device_type:      Optional[str] = None
    metric:           str
    operator:         str   = "gt"
    threshold:        float
    priority:         str   = "p3"
    fault_category:   str   = "unknown"
    cooldown_minutes: int   = 30
    enabled:          bool  = True


# ══════════════════════════════════════════════════════════════════════════════
# Health
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    from backend.agent.llm import check_ollama

    # Incident counts
    counts = {}
    for status in ("new", "l1_running", "l2_running", "resolved", "l3_escalated"):
        r = await db.execute(
            select(func.count(Incident.id)).where(Incident.status == status)
        )
        counts[status] = r.scalar() or 0
    counts["active"] = counts["l1_running"] + counts["l2_running"]

    # AI engine
    ollama = await check_ollama()
    ollama_running = ollama["running"]
    model_ready    = ollama.get("model_available", False)
    claude_enabled = bool(settings.anthropic_api_key)

    return {
        "status":          "ok",
        "version":         "4.0.0",
        "timestamp":       datetime.utcnow().isoformat(),
        "incident_counts": counts,
        # Shape the frontend (App.jsx Sidebar) reads: health.agent.*
        "agent": {
            "ollama_running":  ollama_running,
            "model_ready":     model_ready,
            "ollama_model":    settings.ollama_model,
            "claude_enabled":  claude_enabled,
            "ai_engine":       "ollama" if ollama_running else ("claude" if claude_enabled else "none"),
        },
        # Legacy key kept for backward compat
        "ai_status": {
            "engine":        "ollama" if ollama_running else ("claude" if claude_enabled else "none"),
            "running":       ollama_running,
            "model":         settings.ollama_model,
            "model_ready":   model_ready,
            "claude_backup": claude_enabled,
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# Dashboard
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/dashboard")
async def dashboard(db: AsyncSession = Depends(get_db)):
    from backend.agent.llm import check_ollama

    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    total_r = await db.execute(select(func.count(Incident.id)))
    total   = total_r.scalar() or 0

    resolved_r = await db.execute(
        select(func.count(Incident.id)).where(Incident.status == "resolved")
    )
    resolved = resolved_r.scalar() or 0

    resolved_today_r = await db.execute(
        select(func.count(Incident.id)).where(
            Incident.status == "resolved", Incident.resolved_at >= today,
        )
    )
    resolved_today = resolved_today_r.scalar() or 0

    open_r = await db.execute(
        select(func.count(Incident.id)).where(
            Incident.status.in_(["new", "triaging", "l1_running", "l2_running", "l1_waiting", "l2_waiting"])
        )
    )
    open_count = open_r.scalar() or 0

    sla_r = await db.execute(
        select(func.count(Incident.id)).where(Incident.sla_breached == True)
    )
    sla_breached = sla_r.scalar() or 0

    fp_r = await db.execute(
        select(func.count(Incident.id)).where(Incident.status == "false_positive")
    )
    false_positives = fp_r.scalar() or 0

    pending_appr_r = await db.execute(
        select(func.count(Approval.id)).where(Approval.status == "pending")
    )
    pending_approvals = pending_appr_r.scalar() or 0

    auto_rate = f"{round(resolved / total * 100)}%" if total > 0 else "0%"

    # Recent incidents
    recent_r = await db.execute(
        select(Incident).order_by(desc(Incident.created_at)).limit(10)
    )
    recent = [_fmt_incident(inc) for inc in recent_r.scalars().all()]

    # AI engine
    ollama         = await check_ollama()
    ollama_running = ollama["running"]
    model_ready    = ollama.get("model_available", False)
    claude_enabled = bool(settings.anthropic_api_key)

    return {
        # Shape Dashboard.jsx reads: stats.incidents.* and stats.agent.*
        "incidents": {
            "total":                total,
            "open":                 open_count,
            "resolved":             resolved,
            "resolved_today":       resolved_today,
            "sla_breached":         sla_breached,
            "false_positives":      false_positives,
            "auto_resolution_rate": auto_rate,
        },
        "pending_approvals": pending_approvals,
        "recent_incidents":  recent,
        "agent": {
            "ai_engine":     "ollama" if ollama_running else ("claude" if claude_enabled else "none"),
            "ollama_model":  settings.ollama_model,
            "model_ready":   model_ready,
            "ollama_running": ollama_running,
            "claude_enabled": claude_enabled,
            "max_attempts":  settings.agent_max_attempts,
            "auto_execute":  settings.auto_execute_low_risk,
        },
        # Flat stats kept for any code that reads stats.total_incidents etc.
        "stats": {
            "total_incidents":      total,
            "resolved_today":       resolved_today,
            "active":               open_count,
            "sla_breached":         sla_breached,
            "auto_resolution_rate": auto_rate,
            "false_positives":      false_positives,
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# Incidents
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/incidents")
async def list_incidents(
    status:   Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    search:   Optional[str] = Query(None),
    limit:    int           = Query(50, le=200),
    offset:   int           = Query(0),
    db:       AsyncSession  = Depends(get_db),
):
    q = select(Incident).order_by(desc(Incident.created_at))
    if status:
        q = q.where(Incident.status == status)
    if priority:
        q = q.where(Incident.priority == priority)
    if search:
        like = f"%{search}%"
        q = q.where(
            Incident.title.ilike(like)
            | Incident.number.ilike(like)
            | Incident.affected_host.ilike(like)
        )
    q = q.offset(offset).limit(limit)
    r = await db.execute(q)
    return [_fmt_incident(inc) for inc in r.scalars().all()]


@router.post("/incidents", status_code=201)
async def create_incident(
    body:       IncidentCreate,
    background: BackgroundTasks,
    db:         AsyncSession = Depends(get_db),
):
    # ── Classify & set SLA inline (fast, pure-Python / one small DB read) ─────
    # Doing this here rather than in the background agent means fault_category,
    # priority, and SLA deadlines are available immediately in the API response.
    from backend.agent.classifier import classify as _classify
    _cat, _prio = _classify(body.title, body.description or "")

    # Body overrides take precedence for fault_category.
    # For priority: if caller explicitly provided any value, use it;
    # otherwise fall back to the classifier's result.
    final_fault     = body.fault_category or _cat.value
    final_priority  = body.priority or _prio.value

    # SLA deadlines
    sla_r = await db.execute(
        select(SLAPolicy).where(
            SLAPolicy.priority == final_priority,
            SLAPolicy.customer == None,        # noqa: E711
        )
    )
    sla_policy       = sla_r.scalar_one_or_none()
    _now             = datetime.utcnow()
    sla_response_due = _now + timedelta(minutes=sla_policy.response_minutes) if sla_policy else None
    sla_resolve_due  = _now + timedelta(minutes=sla_policy.resolve_minutes)  if sla_policy else None

    # ── Insert with retry on INC number collision ─────────────────────────────
    inc = None
    for _retry in range(5):
        count_r = await db.execute(select(func.count(Incident.id)))
        count   = count_r.scalar() or 0
        number  = f"INC-{count + 1:04d}"

        inc = Incident(
            number           = number,
            title            = body.title,
            description      = body.description,
            affected_host    = body.affected_host,
            affected_service = body.affected_service,
            source           = body.source,
            priority         = final_priority,
            fault_category   = final_fault,
            sla_response_due = sla_response_due,
            sla_resolve_due  = sla_resolve_due,
            status           = IncidentStatus.NEW,
        )
        db.add(inc)
        try:
            await db.commit()
            await db.refresh(inc)
            break          # success
        except IntegrityError:
            await db.rollback()
            await asyncio.sleep(0.05 * (_retry + 1))   # brief back-off
            inc = None
            continue
    else:
        raise HTTPException(500, "Could not create incident — number collision after retries")

    # Kick off the full diagnostic agent in the background
    background.add_task(_run_agent_background, inc.id)

    # Broadcast new incident to all connected WebSocket clients
    background.add_task(_ws_broadcast, "incident_created", {
        "id": inc.id, "number": inc.number, "title": inc.title,
        "priority": inc.priority, "status": inc.status,
        "fault_category": inc.fault_category,
    })

    return _fmt_incident(inc)


@router.get("/incidents/{incident_id}")
async def get_incident(incident_id: int, db: AsyncSession = Depends(get_db)):
    inc = await _fetch_incident(incident_id, db)
    return _fmt_incident(inc)


@router.get("/incidents/{incident_id}/steps")
async def get_incident_steps(incident_id: int, db: AsyncSession = Depends(get_db)):
    await _fetch_incident(incident_id, db)  # 404 guard
    r = await db.execute(
        select(IncidentStep)
        .where(IncidentStep.incident_id == incident_id)
        .order_by(IncidentStep.sequence)
    )
    return [_fmt_step(s) for s in r.scalars().all()]


@router.post("/incidents/{incident_id}/run")
async def run_agent(
    incident_id: int,
    background:  BackgroundTasks,
    db:          AsyncSession = Depends(get_db),
):
    inc = await _fetch_incident(incident_id, db)
    if inc.status in ("resolved", "closed", "l3_escalated"):
        raise HTTPException(400, f"Incident is already {inc.status}")
    if inc.status in ("l1_running", "l2_running"):
        raise HTTPException(400, f"Agent already running for this incident (status={inc.status})")

    # Reset to NEW so executor picks it up
    inc.status = IncidentStatus.NEW
    await db.commit()

    background.add_task(_run_agent_background, incident_id)
    return {"message": "Agent started", "incident_id": incident_id, "number": inc.number}


# ══════════════════════════════════════════════════════════════════════════════
# Approvals
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/approvals")
async def list_approvals(
    status: Optional[str] = Query("pending"),   # pending | approved | rejected | all
    db:     AsyncSession  = Depends(get_db),
):
    q = select(Approval).order_by(desc(Approval.created_at))
    if status and status != "all":
        q = q.where(Approval.status == status)
    r = await db.execute(q)
    return [_fmt_approval(a) for a in r.scalars().all()]


@router.post("/approvals/{token}/approve")
async def approve_action(
    token:      str,
    background: BackgroundTasks,
    db:         AsyncSession = Depends(get_db),
    # Accept either query param (frontend) or JSON body (Swagger / direct callers)
    note:       Optional[str] = Query(None),
    decided_by: Optional[str] = Query(None),
):
    approval = await _fetch_approval(token, db)
    approval.status        = "approved"
    approval.decided_by    = decided_by or "operator"
    approval.decision_note = note
    approval.decided_at    = datetime.utcnow()
    await db.commit()

    background.add_task(_run_agent_background, approval.incident_id)
    return {"message": "Approved", "token": token}


@router.post("/approvals/{token}/reject")
async def reject_action(
    token:      str,
    db:         AsyncSession = Depends(get_db),
    reason:     Optional[str] = Query(None),
    decided_by: Optional[str] = Query(None),
):
    approval = await _fetch_approval(token, db)
    approval.status        = "rejected"
    approval.decided_by    = decided_by or "operator"
    approval.decision_note = reason
    approval.decided_at    = datetime.utcnow()

    r   = await db.execute(select(Incident).where(Incident.id == approval.incident_id))
    inc = r.scalar_one_or_none()
    if inc:
        inc.status = IncidentStatus.L1_FAILED

    await db.commit()
    return {"message": "Rejected", "token": token}


# ══════════════════════════════════════════════════════════════════════════════
# Hosts / CMDB
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/hosts")
async def list_hosts(db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(Host).order_by(Host.hostname))
    return [_fmt_host(h) for h in r.scalars().all()]


@router.post("/hosts", status_code=201)
async def create_host(body: HostCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(Host).where(Host.hostname == body.hostname))
    if existing.scalar_one_or_none():
        raise HTTPException(409, f"Host '{body.hostname}' already exists")
    h = Host(**body.model_dump())
    db.add(h)
    await db.commit()
    await db.refresh(h)
    return _fmt_host(h)


@router.delete("/hosts/{host_id}", status_code=204)
async def delete_host(host_id: int, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(Host).where(Host.id == host_id))
    h = r.scalar_one_or_none()
    if not h:
        raise HTTPException(404, "Host not found")
    await db.delete(h)
    await db.commit()


# ══════════════════════════════════════════════════════════════════════════════
# NMS Sources
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/nms")
async def list_nms(db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(NMSSource).order_by(NMSSource.name))
    return [_fmt_nms(n) for n in r.scalars().all()]


@router.post("/nms", status_code=201)
async def create_nms(body: NMSCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(NMSSource).where(NMSSource.name == body.name))
    if existing.scalar_one_or_none():
        raise HTTPException(409, f"NMS source '{body.name}' already exists")
    n = NMSSource(**body.model_dump())
    db.add(n)
    await db.commit()
    await db.refresh(n)
    return _fmt_nms(n)


@router.delete("/nms/{nms_id}", status_code=204)
async def delete_nms(nms_id: int, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(NMSSource).where(NMSSource.id == nms_id))
    n = r.scalar_one_or_none()
    if not n:
        raise HTTPException(404, "NMS source not found")
    await db.delete(n)
    await db.commit()


# ══════════════════════════════════════════════════════════════════════════════
# Resolutions (agent memory)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/resolutions")
async def list_resolutions(
    limit:  int = Query(100, le=500),
    db:     AsyncSession = Depends(get_db),
):
    r = await db.execute(
        select(Resolution).order_by(desc(Resolution.created_at)).limit(limit)
    )
    return [_fmt_resolution(res) for res in r.scalars().all()]


# ══════════════════════════════════════════════════════════════════════════════
# Webhook — Alertmanager
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/webhook/alertmanager")
async def webhook_alertmanager(
    payload:    WebhookAlertmanager,
    background: BackgroundTasks,
    db:         AsyncSession = Depends(get_db),
):
    """Receive Prometheus Alertmanager webhook and create incidents."""
    from backend.services.nms.connectors import _create_incident

    created = []
    for alert in payload.alerts:
        if alert.get("status") == "resolved":
            continue

        labels      = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        alert_name  = labels.get("alertname", "Unknown")
        instance    = (labels.get("instance", "") or "").split(":")[0]
        severity    = labels.get("severity", "warning")
        source_id   = f"webhook-{alert_name}-{instance}-{severity}"

        inc = await _create_incident(
            db,
            title       = annotations.get("summary") or alert_name,
            description = annotations.get("description", ""),
            host        = instance or labels.get("node", "") or labels.get("host", ""),
            service     = labels.get("job", ""),
            source      = "alertmanager_webhook",
            source_id   = source_id,
            raw_alert   = alert,
        )
        if inc:
            created.append(inc.id)

    await db.commit()

    for inc_id in created:
        background.add_task(_run_agent_background, inc_id)

    return {"created": len(created), "incident_ids": created}


# ══════════════════════════════════════════════════════════════════════════════
# Background task helper
# ══════════════════════════════════════════════════════════════════════════════

# Semaphore: max 3 agents running simultaneously (prevents SQLite lock pileup)
# Lazy-init inside the event loop to avoid Python asyncio event loop binding issues
_AGENT_SEM = None

def _get_sem():
    global _AGENT_SEM
    if _AGENT_SEM is None:
        import asyncio as _asyncio
        # Allow up to 5 concurrent agents.
        # With the executor fix (commit before Ollama), each agent holds the DB
        # lock for only ~300ms total out of a 10-20s run, so contention is negligible.
        _AGENT_SEM = _asyncio.Semaphore(settings.max_concurrent_agents)
    return _AGENT_SEM


async def _run_agent_background(incident_id: int) -> None:
    """Run the agent in a background task with its own DB session.

    If the semaphore is saturated (all slots busy), we give up after 90 s so
    queued tasks cannot pile up indefinitely and starve the HTTP event loop.
    The incident remains 'new' and can be retried manually or by the next
    auto-trigger.
    """
    import asyncio as _aio
    from backend.database import AsyncSessionLocal
    from backend.agent.executor import AgentExecutor

    try:
        async with _aio.timeout(90):          # abandon if queue wait exceeds 90 s
            async with _get_sem():
                executor = AgentExecutor()
                try:
                    async with AsyncSessionLocal() as db:
                        await executor.run(incident_id, db)
                        await db.commit()
                except Exception as e:
                    logger.error("Background agent failed on incident %d: %s", incident_id, e)
    except _aio.TimeoutError:
        logger.warning(
            "Agent for incident %d dropped — semaphore wait exceeded 90 s "
            "(incident stays 'new' for retry)",
            incident_id,
        )


# ══════════════════════════════════════════════════════════════════════════════
# Format helpers — convert ORM objects to dicts
# ══════════════════════════════════════════════════════════════════════════════

def _fmt_incident(inc: Incident) -> dict:
    return {
        "id":               inc.id,
        "number":           inc.number,
        "title":            inc.title,
        "description":      inc.description,
        "affected_host":    inc.affected_host,
        "affected_service": inc.affected_service,
        "source":           inc.source,
        "source_alert_id":  inc.source_alert_id,
        "fault_category":   inc.fault_category,
        "priority":         inc.priority,
        "status":           inc.status,
        "sla_response_due": inc.sla_response_due.isoformat() if inc.sla_response_due else None,
        "sla_resolve_due":  inc.sla_resolve_due.isoformat() if inc.sla_resolve_due else None,
        "sla_breached":     inc.sla_breached,
        "resolution":       inc.resolution,
        "root_cause":       inc.root_cause,
        "resolved_by":      inc.resolved_by,
        "attempt_count":    inc.attempt_count,
        "created_at":       inc.created_at.isoformat() if inc.created_at else None,
        "resolved_at":      inc.resolved_at.isoformat() if inc.resolved_at else None,
    }


def _fmt_step(s: IncidentStep) -> dict:
    # success → "success"/"failed"/"pending" status string the frontend checks
    if s.success is True:
        status_str = "success"
    elif s.success is False:
        status_str = "failed"
    else:
        status_str = s.status or "pending"

    return {
        "id":                s.id,
        "incident_id":       s.incident_id,
        "sequence":          s.sequence,
        "level":             s.level,
        # Both names for compat — frontend reads s.type, backend stores step_type
        "step_type":         s.step_type,
        "type":              s.step_type,
        "status":            status_str,
        "action":            s.action,
        "command":           s.command,
        "raw_output":        s.raw_output,
        # Both names — frontend reads s.result.issues, backend stores parsed_result
        "parsed_result":     s.parsed_result,
        "result":            s.parsed_result,
        # Both names — frontend reads s.ai_interpret, backend stores ai_interpretation
        "ai_interpretation": s.ai_interpretation,
        "ai_interpret":      s.ai_interpretation,
        "success":           s.success,
        "error":             s.error,
        "duration_ms":       s.duration_ms,
        "created_at":        s.created_at.isoformat() if s.created_at else None,
    }


def _fmt_approval(a: Approval) -> dict:
    return {
        "id":               a.id,
        "incident_id":      a.incident_id,
        "token":            a.token,
        "action":           a.action,
        "host":             a.host,
        "risk_level":       a.risk_level,
        "reason":           a.reason,
        "rollback":         a.rollback,
        "incident_summary": a.incident_summary,
        "status":           a.status,
        "decided_by":       a.decided_by,
        "decision_note":    a.decision_note,
        "decided_at":       a.decided_at.isoformat() if a.decided_at else None,
        "expires_at":       a.expires_at.isoformat() if a.expires_at else None,
        "created_at":       a.created_at.isoformat() if a.created_at else None,
    }


def _fmt_host(h: Host) -> dict:
    return {
        "id":               h.id,
        "hostname":         h.hostname,
        "ip_address":       h.ip_address,
        "os":               h.os,
        "environment":      h.environment,
        "criticality":      h.criticality,
        "business_service": h.business_service,
        "owner_email":      h.owner_email,
        "ssh_user":         h.ssh_user,
        "ssh_key_path":     h.ssh_key_path,
        "ssh_port":         h.ssh_port,
        "auto_remediate":   h.auto_remediate,
        "approval_required":h.approval_required,
        "never_touch":      h.never_touch,
        "known_issues":     h.known_issues,
        "services":         h.services,
        # Hosts.jsx checks h.ssh_available to show ✓ ssh_user
        "ssh_available":    bool(h.ssh_user and (h.ssh_key_path or True)),
        "created_at":       h.created_at.isoformat() if h.created_at else None,
    }


def _fmt_nms(n: NMSSource) -> dict:
    return {
        "id":             n.id,
        "name":           n.name,
        "nms_type":       n.nms_type,
        "base_url":       n.base_url,
        "username":       n.username,
        "enabled":        n.enabled,
        "poll_interval":  n.poll_interval,
        "last_polled_at": n.last_polled_at.isoformat() if n.last_polled_at else None,
        "last_error":     n.last_error,
        "status":         n.status,
        "created_at":     n.created_at.isoformat() if n.created_at else None,
    }


def _fmt_resolution(r: Resolution) -> dict:
    return {
        "id":               r.id,
        "incident_id":      r.incident_id,
        "host":             r.host,
        # Both names — analytics reads r.fault, r.fix, r.time_min, r.level, r.date
        "fault_category":   r.fault_category,
        "fault":            r.fault_category,
        "fix_action":       r.fix_action,
        "fix":              r.fix_action,
        "success":          r.success,
        "time_to_fix_min":  r.time_to_fix_min,
        "time_min":         r.time_to_fix_min,
        "resolved_at_level":r.resolved_at_level,
        "level":            r.resolved_at_level,
        "notes":            r.notes,
        "created_at":       r.created_at.isoformat() if r.created_at else None,
        "date":             r.created_at.strftime("%Y-%m-%d") if r.created_at else None,
    }


# ══════════════════════════════════════════════════════════════════════════════
# DB fetch helpers with 404 raising
# ══════════════════════════════════════════════════════════════════════════════

async def _fetch_incident(incident_id: int, db: AsyncSession) -> Incident:
    r = await db.execute(select(Incident).where(Incident.id == incident_id))
    inc = r.scalar_one_or_none()
    if not inc:
        raise HTTPException(404, f"Incident {incident_id} not found")
    return inc


async def _fetch_approval(token: str, db: AsyncSession) -> Approval:
    r = await db.execute(select(Approval).where(Approval.token == token))
    a = r.scalar_one_or_none()
    if not a:
        raise HTTPException(404, f"Approval token '{token}' not found")
    if a.status != "pending":
        raise HTTPException(409, f"Approval already {a.status}")
    if a.expires_at and datetime.utcnow() > a.expires_at:
        raise HTTPException(410, "Approval request has expired")
    return a


# ══════════════════════════════════════════════════════════════════════════════
# Monitored Hosts
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/monitored-hosts")
async def list_monitored_hosts(
    limit:  int           = Query(100, le=500),
    offset: int           = Query(0),
    search: Optional[str] = Query(None),
    db:     AsyncSession  = Depends(get_db),
):
    q = select(MonitoredHost).order_by(MonitoredHost.hostname)
    if search:
        term = f"%{search}%"
        from sqlalchemy import or_
        q = q.where(or_(
            MonitoredHost.hostname.ilike(term),
            MonitoredHost.display_name.ilike(term),
            MonitoredHost.ip_address.ilike(term),
        ))
    q = q.offset(offset).limit(limit)
    r = await db.execute(q)
    return [_fmt_monitored_host(h) for h in r.scalars().all()]


@router.get("/monitored-hosts/{host_id}")
async def get_monitored_host(host_id: int, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(MonitoredHost).where(MonitoredHost.id == host_id))
    h = r.scalar_one_or_none()
    if not h:
        raise HTTPException(404, "Monitored host not found")
    return _fmt_monitored_host(h)


@router.post("/monitored-hosts", status_code=201)
async def create_monitored_host(body: MonitoredHostCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(
        select(MonitoredHost).where(MonitoredHost.hostname == body.hostname)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, f"Monitored host '{body.hostname}' already exists")

    data = body.model_dump()
    # Encrypt sensitive credentials before storage
    _enc = lambda v: encrypt_credential(v, settings.secret_key, settings.encryption_key) if v else v
    data["ssh_password"]     = _enc(data.get("ssh_password"))
    data["snmp_v3_auth_key"] = _enc(data.get("snmp_v3_auth_key"))
    data["snmp_v3_priv_key"] = _enc(data.get("snmp_v3_priv_key"))

    h = MonitoredHost(**data)
    db.add(h)
    await db.commit()
    await db.refresh(h)
    return _fmt_monitored_host(h)


@router.put("/monitored-hosts/{host_id}")
async def update_monitored_host(
    host_id: int,
    body:    MonitoredHostUpdate,
    db:      AsyncSession = Depends(get_db),
):
    r = await db.execute(select(MonitoredHost).where(MonitoredHost.id == host_id))
    h = r.scalar_one_or_none()
    if not h:
        raise HTTPException(404, "Monitored host not found")

    _enc = lambda v: encrypt_credential(v, settings.secret_key, settings.encryption_key) if v else v
    updates = body.model_dump(exclude_none=True)
    # Encrypt sensitive fields before storing
    for sensitive in ("ssh_password", "snmp_v3_auth_key", "snmp_v3_priv_key"):
        if sensitive in updates:
            updates[sensitive] = _enc(updates[sensitive])

    for field, value in updates.items():
        setattr(h, field, value)
    await db.commit()
    await db.refresh(h)
    return _fmt_monitored_host(h)


@router.delete("/monitored-hosts/{host_id}", status_code=204)
async def delete_monitored_host(host_id: int, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(MonitoredHost).where(MonitoredHost.id == host_id))
    h = r.scalar_one_or_none()
    if not h:
        raise HTTPException(404, "Monitored host not found")
    await db.delete(h)
    await db.commit()


@router.post("/monitored-hosts/{host_id}/poll")
async def force_poll_host(
    host_id:    int,
    background: BackgroundTasks,
    db:         AsyncSession = Depends(get_db),
):
    """Trigger an immediate out-of-schedule poll for a specific host."""
    r = await db.execute(select(MonitoredHost).where(MonitoredHost.id == host_id))
    h = r.scalar_one_or_none()
    if not h:
        raise HTTPException(404, "Monitored host not found")
    background.add_task(_poll_and_store, host_id)
    return {"message": f"Poll triggered for {h.hostname}", "host_id": host_id}


@router.get("/monitored-hosts/{host_id}/metrics")
async def get_host_metrics(
    host_id: int,
    metric:  Optional[str] = Query(None),    # filter to one metric
    hours:   int           = Query(6, le=168),
    db:      AsyncSession  = Depends(get_db),
):
    """Return time-series metric samples for charting."""
    r = await db.execute(select(MonitoredHost).where(MonitoredHost.id == host_id))
    if not r.scalar_one_or_none():
        raise HTTPException(404, "Monitored host not found")

    since = datetime.utcnow() - timedelta(hours=hours)
    q = (
        select(MetricSample)
        .where(MetricSample.host_id == host_id, MetricSample.sampled_at >= since)
        .order_by(MetricSample.sampled_at)
    )
    if metric:
        q = q.where(MetricSample.metric == metric)

    samples = (await db.execute(q)).scalars().all()

    # Group by metric name for easy charting
    grouped: dict[str, list] = {}
    for s in samples:
        grouped.setdefault(s.metric, []).append({
            "t": s.sampled_at.isoformat(),
            "v": s.value,
        })
    return grouped


# ══════════════════════════════════════════════════════════════════════════════
# Metrics summary (dashboard tiles — latest value per host per metric)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/metrics/summary")
async def metrics_summary(db: AsyncSession = Depends(get_db)):
    """Latest metric value for every monitored host — used by dashboard stat tiles."""
    r = await db.execute(
        select(MonitoredHost).where(MonitoredHost.enabled == True).order_by(MonitoredHost.hostname)
    )
    hosts = r.scalars().all()

    result = []
    for h in hosts:
        # Get the latest value for each metric we care about
        latest_metrics: dict[str, Optional[float]] = {}
        for metric_name in ("cpu_percent", "ram_percent", "disk_percent",
                            "load_1m", "ping_ms", "ping_up",
                            "net_rx_bps", "net_tx_bps"):
            latest_r = await db.execute(
                select(MetricSample.value)
                .where(MetricSample.host_id == h.id, MetricSample.metric == metric_name)
                .order_by(MetricSample.sampled_at.desc())
                .limit(1)
            )
            val = latest_r.scalar_one_or_none()
            latest_metrics[metric_name] = val

        result.append({
            **_fmt_monitored_host(h),
            "latest": latest_metrics,
        })

    return result


# ══════════════════════════════════════════════════════════════════════════════
# Threshold Rules
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/threshold-rules")
async def list_threshold_rules(db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(ThresholdRule).order_by(ThresholdRule.metric, ThresholdRule.threshold))
    return [_fmt_threshold_rule(t) for t in r.scalars().all()]


@router.post("/threshold-rules", status_code=201)
async def create_threshold_rule(body: ThresholdRuleCreate, db: AsyncSession = Depends(get_db)):
    t = ThresholdRule(**body.model_dump())
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return _fmt_threshold_rule(t)


@router.put("/threshold-rules/{rule_id}")
async def update_threshold_rule(
    rule_id: int,
    body:    ThresholdRuleCreate,
    db:      AsyncSession = Depends(get_db),
):
    r = await db.execute(select(ThresholdRule).where(ThresholdRule.id == rule_id))
    t = r.scalar_one_or_none()
    if not t:
        raise HTTPException(404, "Threshold rule not found")
    for field, value in body.model_dump().items():
        setattr(t, field, value)
    await db.commit()
    await db.refresh(t)
    return _fmt_threshold_rule(t)


@router.delete("/threshold-rules/{rule_id}", status_code=204)
async def delete_threshold_rule(rule_id: int, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(ThresholdRule).where(ThresholdRule.id == rule_id))
    t = r.scalar_one_or_none()
    if not t:
        raise HTTPException(404, "Threshold rule not found")
    await db.delete(t)
    await db.commit()


# ══════════════════════════════════════════════════════════════════════════════
# Background poll helper (used by force_poll and scheduler)
# ══════════════════════════════════════════════════════════════════════════════

async def _poll_and_store(host_id: int) -> None:
    """Poll a single host, store samples, evaluate thresholds."""
    from backend.database import AsyncSessionLocal
    from backend.services.monitoring.collector import poll_host
    from backend.services.monitoring.thresholds import evaluate_metrics

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(MonitoredHost).where(MonitoredHost.id == host_id))
        host = r.scalar_one_or_none()
        if not host or not host.enabled:
            return

        try:
            metrics = await poll_host(host)
        except Exception as e:
            logger.error("Poll failed for host %d (%s): %s", host_id, host.hostname, e)
            host.last_error  = str(e)
            host.status      = "unknown"
            host.last_polled_at = datetime.utcnow()
            await db.commit()
            return

        now = datetime.utcnow()

        # Store samples
        for metric_name, value in metrics.items():
            db.add(MetricSample(
                host_id    = host.id,
                metric     = metric_name,
                value      = float(value),
                sampled_at = now,
            ))

        # Update host status
        ping_up = metrics.get("ping_up", 1.0)
        host.status         = "up" if ping_up >= 1.0 else "down"
        host.last_polled_at = now
        host.last_error     = None
        if ping_up >= 1.0:
            host.last_seen_at = now

        await db.commit()

        # Evaluate thresholds → create incidents if needed
        incident_ids = await evaluate_metrics(db, host, metrics)
        if incident_ids:
            await db.commit()

        # Kick off agent for any new incidents + broadcast to WS clients
        for inc_id in incident_ids:
            asyncio.create_task(_run_agent_background(inc_id))
            asyncio.create_task(_ws_broadcast("incident_created", {"id": inc_id, "source": "threshold"}))

        logger.debug(
            "Polled %s: %s | incidents=%s",
            host.hostname,
            {k: f"{v:.1f}" for k, v in metrics.items()},
            incident_ids,
        )


# ══════════════════════════════════════════════════════════════════════════════
# Monitoring format helpers
# ══════════════════════════════════════════════════════════════════════════════

def _fmt_monitored_host(h: MonitoredHost) -> dict:
    return {
        "id":             h.id,
        "hostname":       h.hostname,
        "ip_address":     h.ip_address,
        "display_name":   h.display_name or h.hostname,
        "device_type":    h.device_type,
        "location":       h.location,
        "environment":    h.environment,
        "ssh_user":       h.ssh_user,
        "ssh_port":       h.ssh_port,
        "ssh_key_path":   h.ssh_key_path,
        "snmp_community":       h.snmp_community,
        "snmp_port":            h.snmp_port,
        "snmp_version":         h.snmp_version,
        "snmp_v3_user":         getattr(h, "snmp_v3_user", None),
        "snmp_v3_auth_protocol":getattr(h, "snmp_v3_auth_protocol", "SHA"),
        "snmp_v3_priv_protocol":getattr(h, "snmp_v3_priv_protocol", "AES"),
        # Note: auth/priv keys are intentionally omitted from API responses
        "enabled":        h.enabled,
        "poll_interval":  h.poll_interval,
        "status":         h.status,
        "last_polled_at": h.last_polled_at.isoformat() if h.last_polled_at else None,
        "last_seen_at":   h.last_seen_at.isoformat() if h.last_seen_at else None,
        "last_error":     h.last_error,
        "created_at":     h.created_at.isoformat() if h.created_at else None,
    }


def _fmt_threshold_rule(t: ThresholdRule) -> dict:
    return {
        "id":               t.id,
        "name":             t.name,
        "host_id":          t.host_id,
        "device_type":      t.device_type,
        "metric":           t.metric,
        "operator":         t.operator,
        "threshold":        t.threshold,
        "priority":         t.priority,
        "fault_category":   t.fault_category,
        "cooldown_minutes": t.cooldown_minutes,
        "enabled":          t.enabled,
        "created_at":       t.created_at.isoformat() if t.created_at else None,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Training data endpoints
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/training/stats", summary="Training dataset statistics")
async def training_stats(db: AsyncSession = Depends(get_db)):
    """Returns statistics about the training JSONL file (examples count, file size, etc.)."""
    try:
        from backend.services.training.collector import get_stats
        stats = await get_stats(db)
        return stats
    except ImportError:
        return {"error": "Training module not available", "examples": 0}
    except Exception as e:
        return {"error": str(e), "examples": 0}


class SyntheticGenBody(BaseModel):
    count: int = 10


@router.post("/training/generate", summary="Generate synthetic training examples")
async def generate_synthetic(body: SyntheticGenBody):
    """Generates synthetic training examples and appends them to the JSONL file."""
    try:
        from backend.services.training.collector import generate_synthetic_examples
        n = await generate_synthetic_examples(body.count)
        return {"generated": n, "requested": body.count}
    except ImportError:
        return {"error": "Training module not available", "generated": 0}
    except Exception as e:
        raise HTTPException(500, str(e))


# ══════════════════════════════════════════════════════════════════════════════
# WebSocket info endpoint (REST)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/ws/stats", summary="WebSocket connection stats")
async def ws_stats():
    try:
        from backend.routers.ws import manager
        return {"connections": manager.connection_count}
    except Exception:
        return {"connections": 0}


# ══════════════════════════════════════════════════════════════════════════════
# Audit Log  (Fix #9)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/audit-log", summary="Query the audit log")
async def list_audit_log(
    incident_id: Optional[int] = Query(None),
    actor:       Optional[str] = Query(None),
    limit:       int           = Query(100, le=500),
    offset:      int           = Query(0),
    db:          AsyncSession  = Depends(get_db),
):
    """Return audit log entries, newest first.  Filter by incident_id or actor."""
    q = select(AuditLog).order_by(desc(AuditLog.created_at))
    if incident_id is not None:
        q = q.where(AuditLog.incident_id == incident_id)
    if actor:
        q = q.where(AuditLog.actor.ilike(f"%{actor}%"))
    q = q.offset(offset).limit(limit)
    r = await db.execute(q)
    rows = r.scalars().all()
    return [
        {
            "id":          row.id,
            "incident_id": row.incident_id,
            "actor":       row.actor,
            "action":      row.action,
            "detail":      row.detail,
            "created_at":  row.created_at,
        }
        for row in rows
    ]


# ══════════════════════════════════════════════════════════════════════════════
# User Management  (Fix #8)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/users", summary="List all users (admin only)")
async def list_users(db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(User).order_by(User.username))
    return [_fmt_user(u) for u in r.scalars().all()]


@router.post("/users", status_code=201, summary="Create a new user (admin only)")
async def create_user(body: UserCreate, db: AsyncSession = Depends(get_db)):
    import bcrypt as _bcrypt
    existing = await db.execute(select(User).where(User.username == body.username))
    if existing.scalar_one_or_none():
        raise HTTPException(409, f"Username '{body.username}' already exists")
    if len(body.password) < 8:
        raise HTTPException(422, "Password must be at least 8 characters")
    hashed = _bcrypt.hashpw(body.password.encode(), _bcrypt.gensalt()).decode()
    user = User(
        username        = body.username,
        email           = body.email,
        full_name       = body.full_name,
        hashed_password = hashed,
        role            = body.role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return _fmt_user(user)


@router.patch("/users/{user_id}", summary="Update a user (admin only)")
async def update_user(user_id: int, body: UserUpdate, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(User).where(User.id == user_id))
    u = r.scalar_one_or_none()
    if not u:
        raise HTTPException(404, "User not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(u, field, value)
    await db.commit()
    await db.refresh(u)
    return _fmt_user(u)


@router.delete("/users/{user_id}", status_code=204, summary="Delete a user (admin only)")
async def delete_user(user_id: int, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(User).where(User.id == user_id))
    u = r.scalar_one_or_none()
    if not u:
        raise HTTPException(404, "User not found")
    if u.username == "admin":
        raise HTTPException(400, "Cannot delete the default admin account")
    await db.delete(u)
    await db.commit()


def _fmt_user(u: User) -> dict:
    return {
        "id":        u.id,
        "username":  u.username,
        "email":     u.email,
        "full_name": u.full_name,
        "role":      u.role,
        "is_active": u.is_active,
        "created_at": u.created_at,
    }
