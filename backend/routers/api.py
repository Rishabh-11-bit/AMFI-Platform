"""
AMFI Platform — All API Routers

  /api/ingest/*         Module 1 — Event ingestion endpoints
  /api/incidents/*      Module 4 — Incident management
  /api/remediation/*    Module 6 — Remediation jobs
  /api/cmdb/*           CMDB configuration items
  /api/dashboard        Metrics dashboard
  /api/auth/*           Authentication
"""
from datetime import datetime, timedelta
from typing import Optional, List, Any
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel

from backend.database import get_db
from backend.models.all_models import (
    RawEvent, RawEventStatus, IngestionSource, Severity,
    Incident, IncidentStatus, IncidentPriority,
    RemediationJob, RemediationStatus, RemediationType,
    DiagnosticRun, NotificationLog,
    ConfigItem, AuditLog, User,
)
from backend.services.ingestion_service  import IngestionService
from backend.services.remediation_service import RemediationService
from backend.config import get_settings
import bcrypt as _bcrypt
from jose import jwt

settings    = get_settings()
def _hash_pw(p): return _bcrypt.hashpw(p.encode(), _bcrypt.gensalt()).decode()
def _verify_pw(p, h): return _bcrypt.checkpw(p.encode(), h.encode())


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTER: INGEST
# ═══════════════════════════════════════════════════════════════════════════════

ingest_router = APIRouter()

class AlertmanagerPayload(BaseModel):
    version: Optional[str] = None
    status:  Optional[str] = None
    alerts:  List[dict]    = []
    groupLabels:      dict = {}
    commonLabels:     dict = {}
    commonAnnotations:dict = {}

class ManualEventCreate(BaseModel):
    title:            str
    message:          Optional[str]  = None
    severity:         Severity       = Severity.WARNING
    affected_host:    Optional[str]  = None
    affected_service: Optional[str]  = None
    tool_name:        Optional[str]  = "manual"


@ingest_router.post("/alertmanager")
async def ingest_alertmanager(payload: AlertmanagerPayload, request: Request,
                               db: AsyncSession = Depends(get_db)):
    host = request.client.host if request.client else None
    svc  = IngestionService(db)
    events = await svc.ingest_alertmanager(payload.model_dump(), host)
    return {"received": len(events),
            "events": [{"id": e.id, "status": e.status, "title": e.title,
                        "severity": e.severity} for e in events]}

@ingest_router.post("/webhook")
async def ingest_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")
    host  = request.client.host if request.client else None
    svc   = IngestionService(db)
    event = await svc.ingest_webhook(payload, host)
    return {"id": event.id, "status": event.status, "title": event.title}

@ingest_router.post("/manual")
async def ingest_manual(data: ManualEventCreate, request: Request,
                         db: AsyncSession = Depends(get_db)):
    host  = request.client.host if request.client else "manual"
    svc   = IngestionService(db)
    event = await svc.ingest_webhook(
        {"title": data.title, "message": data.message,
         "severity": data.severity.value, "host": data.affected_host,
         "service": data.affected_service, "tool": data.tool_name}, host)
    return {"id": event.id, "status": event.status, "title": event.title}

@ingest_router.get("/events")
async def list_raw_events(
    source: Optional[str] = None, severity: Optional[str] = None,
    status: Optional[str] = None, host: Optional[str] = None,
    skip: int = 0, limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db)):
    q = select(RawEvent)
    if source:   q = q.where(RawEvent.source   == source)
    if severity: q = q.where(RawEvent.severity == severity)
    if status:   q = q.where(RawEvent.status   == status)
    if host:     q = q.where(RawEvent.affected_host.contains(host))
    q = q.order_by(RawEvent.received_at.desc()).offset(skip).limit(limit)
    r = await db.execute(q)
    events = r.scalars().all()
    return [_raw_event_dict(e) for e in events]

@ingest_router.get("/stats")
async def ingest_stats(db: AsyncSession = Depends(get_db)):
    total     = (await db.execute(select(func.count(RawEvent.id)))).scalar() or 0
    by_source = dict((await db.execute(select(RawEvent.source,   func.count(RawEvent.id)).group_by(RawEvent.source))).all())
    by_sev    = dict((await db.execute(select(RawEvent.severity, func.count(RawEvent.id)).group_by(RawEvent.severity))).all())
    by_status = dict((await db.execute(select(RawEvent.status,   func.count(RawEvent.id)).group_by(RawEvent.status))).all())
    return {"total": total,
            "by_source":   {str(k): v for k, v in by_source.items()},
            "by_severity": {str(k): v for k, v in by_sev.items()},
            "by_status":   {str(k): v for k, v in by_status.items()}}

@ingest_router.get("/health")
async def ingest_health():
    from backend.main import listener_status
    return {"api": "running", **listener_status}


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTER: INCIDENTS
# ═══════════════════════════════════════════════════════════════════════════════

incident_router = APIRouter()

class IncidentCreate(BaseModel):
    title:         str
    description:   Optional[str]           = None
    priority:      IncidentPriority        = IncidentPriority.MEDIUM
    source:        Optional[str]           = "manual"
    assigned_to:   Optional[str]           = None
    assigned_team: Optional[str]           = None

class IncidentUpdate(BaseModel):
    title:              Optional[str]           = None
    description:        Optional[str]           = None
    status:             Optional[IncidentStatus]= None
    priority:           Optional[IncidentPriority] = None
    assigned_to:        Optional[str]           = None
    assigned_team:      Optional[str]           = None
    resolution_notes:   Optional[str]           = None
    root_cause_analysis:Optional[str]           = None


@incident_router.get("")
async def list_incidents(
    status:   Optional[str] = None, priority: Optional[str] = None,
    team:     Optional[str] = None,
    skip: int = 0, limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db)):
    q = select(Incident)
    if status:   q = q.where(Incident.status   == status)
    if priority: q = q.where(Incident.priority == priority)
    if team:     q = q.where(Incident.assigned_team == team)
    q = q.order_by(Incident.created_at.desc()).offset(skip).limit(limit)
    r = await db.execute(q)
    return [_incident_dict(i) for i in r.scalars().all()]

@incident_router.post("")
async def create_incident(data: IncidentCreate, db: AsyncSession = Depends(get_db)):
    sla_map = {
        IncidentPriority.CRITICAL: settings.sla_critical_minutes,
        IncidentPriority.HIGH:     settings.sla_high_minutes,
        IncidentPriority.MEDIUM:   settings.sla_medium_minutes,
        IncidentPriority.LOW:      settings.sla_low_minutes,
    }
    inc = Incident(
        title         = data.title,
        description   = data.description,
        priority      = data.priority,
        source        = data.source,
        assigned_to   = data.assigned_to,
        assigned_team = data.assigned_team,
        sla_deadline  = datetime.utcnow() + timedelta(minutes=sla_map.get(data.priority, 240)),
        created_by    = "api",
        status        = IncidentStatus.NEW,
    )
    db.add(inc)
    await db.commit()
    await db.refresh(inc)
    return _incident_dict(inc)

@incident_router.get("/stats")
async def incident_stats(db: AsyncSession = Depends(get_db)):
    total     = (await db.execute(select(func.count(Incident.id)))).scalar() or 0
    open_inc  = (await db.execute(select(func.count(Incident.id)).where(
        Incident.status.notin_([IncidentStatus.RESOLVED, IncidentStatus.CLOSED])))).scalar() or 0
    since     = datetime.utcnow() - timedelta(days=1)
    resolved  = (await db.execute(select(func.count(Incident.id)).where(
        Incident.resolved_at >= since))).scalar() or 0
    breached  = (await db.execute(select(func.count(Incident.id)).where(
        Incident.sla_breached == True))).scalar() or 0
    by_prio   = dict((await db.execute(select(Incident.priority, func.count(Incident.id)).group_by(Incident.priority))).all())
    by_status = dict((await db.execute(select(Incident.status,   func.count(Incident.id)).group_by(Incident.status))).all())
    return {"total": total, "open": open_inc, "resolved_today": resolved,
            "sla_breached": breached,
            "by_priority": {str(k): v for k, v in by_prio.items()},
            "by_status":   {str(k): v for k, v in by_status.items()}}

@incident_router.get("/{incident_id}")
async def get_incident(incident_id: int, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(Incident).where(Incident.id == incident_id))
    inc = r.scalar_one_or_none()
    if not inc:
        raise HTTPException(404, "Incident not found")
    return _incident_dict(inc)

@incident_router.patch("/{incident_id}")
async def update_incident(incident_id: int, data: IncidentUpdate,
                           db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(Incident).where(Incident.id == incident_id))
    inc = r.scalar_one_or_none()
    if not inc:
        raise HTTPException(404, "Incident not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(inc, k, v)
    if data.status in (IncidentStatus.RESOLVED, IncidentStatus.CLOSED):
        inc.resolved_at = datetime.utcnow()
    await db.commit()
    return _incident_dict(inc)

@incident_router.delete("/{incident_id}")
async def delete_incident(incident_id: int, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(Incident).where(Incident.id == incident_id))
    inc = r.scalar_one_or_none()
    if not inc:
        raise HTTPException(404, "Incident not found")
    await db.delete(inc)
    await db.commit()
    return {"ok": True}

@incident_router.get("/{incident_id}/diagnostics")
async def get_incident_diagnostics(incident_id: int, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(DiagnosticRun).where(DiagnosticRun.incident_id == incident_id))
    return [{"id": d.id, "level": d.level, "status": d.status,
             "summary": d.summary, "recommended_action": d.recommended_action,
             "started_at": d.started_at, "duration_seconds": d.duration_seconds,
             "findings": d.findings} for d in r.scalars().all()]

@incident_router.get("/{incident_id}/remediation")
async def get_incident_remediation(incident_id: int, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(RemediationJob).where(RemediationJob.incident_id == incident_id))
    return [_job_dict(j) for j in r.scalars().all()]


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTER: REMEDIATION
# ═══════════════════════════════════════════════════════════════════════════════

remediation_router = APIRouter()

class ApprovalRequest(BaseModel):
    approved_by: str

class RejectionRequest(BaseModel):
    rejected_by: str
    reason: str

class ManualJobCreate(BaseModel):
    incident_id:      int
    action:           str
    remediation_type: RemediationType = RemediationType.MANUAL
    target_host:      Optional[str]   = None
    parameters:       Optional[dict]  = None
    requires_approval:bool            = False


@remediation_router.get("")
async def list_jobs(
    status: Optional[str] = None, incident_id: Optional[int] = None,
    skip: int = 0, limit: int = 50,
    db: AsyncSession = Depends(get_db)):
    q = select(RemediationJob)
    if status:      q = q.where(RemediationJob.status      == status)
    if incident_id: q = q.where(RemediationJob.incident_id == incident_id)
    q = q.order_by(RemediationJob.created_at.desc()).offset(skip).limit(limit)
    r = await db.execute(q)
    return [_job_dict(j) for j in r.scalars().all()]

@remediation_router.post("")
async def create_manual_job(data: ManualJobCreate, db: AsyncSession = Depends(get_db)):
    job = RemediationJob(
        incident_id       = data.incident_id,
        remediation_type  = data.remediation_type,
        action            = data.action,
        target_host       = data.target_host,
        parameters        = data.parameters,
        requires_approval = data.requires_approval,
        status = RemediationStatus.AWAITING_APPROVAL if data.requires_approval else RemediationStatus.PENDING,
        max_attempts = settings.remediation_max_retries,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return _job_dict(job)

@remediation_router.get("/{job_id}")
async def get_job(job_id: int, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(RemediationJob).where(RemediationJob.id == job_id))
    job = r.scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Job not found")
    return _job_dict(job)

@remediation_router.post("/{job_id}/approve")
async def approve_job(job_id: int, req: ApprovalRequest, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(RemediationJob).where(RemediationJob.id == job_id))
    job = r.scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status != RemediationStatus.AWAITING_APPROVAL:
        raise HTTPException(400, f"Job is not awaiting approval (status={job.status})")
    svc = RemediationService(db)
    job = await svc.approve(job, req.approved_by)
    await db.commit()
    return _job_dict(job)

@remediation_router.post("/{job_id}/reject")
async def reject_job(job_id: int, req: RejectionRequest, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(RemediationJob).where(RemediationJob.id == job_id))
    job = r.scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Job not found")
    svc = RemediationService(db)
    job = await svc.reject(job, req.reason, req.rejected_by)
    await db.commit()
    return _job_dict(job)

@remediation_router.post("/{job_id}/execute")
async def execute_job(job_id: int, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(RemediationJob).where(RemediationJob.id == job_id))
    job = r.scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Job not found")
    svc = RemediationService(db)
    job = await svc.execute(job)
    await db.commit()
    return _job_dict(job)


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTER: CMDB
# ═══════════════════════════════════════════════════════════════════════════════

cmdb_router = APIRouter()

class CICreate(BaseModel):
    ci_id:           str
    hostname:        str
    ip_address:      Optional[str] = None
    ci_type:         Optional[str] = "server"
    os:              Optional[str] = None
    environment:     Optional[str] = "prod"
    location:        Optional[str] = None
    owner:           Optional[str] = None
    team:            Optional[str] = None
    business_service:Optional[str] = None
    criticality:     Optional[str] = "medium"
    dependent_on:    Optional[list]= None
    supports:        Optional[list]= None
    tags:            Optional[list]= None
    ssh_user:        Optional[str] = None
    ssh_key_path:    Optional[str] = None

class CIUpdate(BaseModel):
    hostname:        Optional[str] = None
    ip_address:      Optional[str] = None
    ci_type:         Optional[str] = None
    environment:     Optional[str] = None
    owner:           Optional[str] = None
    team:            Optional[str] = None
    business_service:Optional[str] = None
    criticality:     Optional[str] = None
    ssh_user:        Optional[str] = None
    ssh_key_path:    Optional[str] = None
    supports:        Optional[list]= None
    dependent_on:    Optional[list]= None
    tags:            Optional[list]= None


@cmdb_router.get("")
async def list_cis(environment: Optional[str] = None, ci_type: Optional[str] = None,
                   skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)):
    q = select(ConfigItem)
    if environment: q = q.where(ConfigItem.environment == environment)
    if ci_type:     q = q.where(ConfigItem.ci_type     == ci_type)
    q = q.offset(skip).limit(limit)
    r = await db.execute(q)
    return [_ci_dict(c) for c in r.scalars().all()]

@cmdb_router.post("")
async def create_ci(data: CICreate, db: AsyncSession = Depends(get_db)):
    ci = ConfigItem(**data.model_dump())
    db.add(ci)
    await db.commit()
    await db.refresh(ci)
    return _ci_dict(ci)

@cmdb_router.get("/{ci_id}")
async def get_ci(ci_id: str, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(ConfigItem).where(ConfigItem.ci_id == ci_id))
    ci = r.scalar_one_or_none()
    if not ci:
        raise HTTPException(404, "CI not found")
    return _ci_dict(ci)

@cmdb_router.patch("/{ci_id}")
async def update_ci(ci_id: str, data: CIUpdate, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(ConfigItem).where(ConfigItem.ci_id == ci_id))
    ci = r.scalar_one_or_none()
    if not ci:
        raise HTTPException(404, "CI not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(ci, k, v)
    await db.commit()
    return _ci_dict(ci)

@cmdb_router.delete("/{ci_id}")
async def delete_ci(ci_id: str, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(ConfigItem).where(ConfigItem.ci_id == ci_id))
    ci = r.scalar_one_or_none()
    if not ci:
        raise HTTPException(404, "CI not found")
    await db.delete(ci)
    await db.commit()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTER: DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════

dashboard_router = APIRouter()

@dashboard_router.get("")
async def get_dashboard(db: AsyncSession = Depends(get_db)):
    since_day = datetime.utcnow() - timedelta(days=1)

    total_events  = (await db.execute(select(func.count(RawEvent.id)))).scalar() or 0
    events_today  = (await db.execute(select(func.count(RawEvent.id)).where(RawEvent.received_at >= since_day))).scalar() or 0
    total_inc     = (await db.execute(select(func.count(Incident.id)))).scalar() or 0
    open_inc      = (await db.execute(select(func.count(Incident.id)).where(Incident.status.notin_([IncidentStatus.RESOLVED, IncidentStatus.CLOSED])))).scalar() or 0
    resolved_today= (await db.execute(select(func.count(Incident.id)).where(Incident.resolved_at >= since_day))).scalar() or 0
    sla_breached  = (await db.execute(select(func.count(Incident.id)).where(Incident.sla_breached == True, Incident.status.notin_([IncidentStatus.RESOLVED, IncidentStatus.CLOSED])))).scalar() or 0
    pending_approv= (await db.execute(select(func.count(RemediationJob.id)).where(RemediationJob.status == RemediationStatus.AWAITING_APPROVAL))).scalar() or 0
    auto_success  = (await db.execute(select(func.count(RemediationJob.id)).where(RemediationJob.status == RemediationStatus.SUCCESS))).scalar() or 0
    auto_total    = (await db.execute(select(func.count(RemediationJob.id)).where(RemediationJob.status.notin_([RemediationStatus.PENDING, RemediationStatus.AWAITING_APPROVAL])))).scalar() or 1

    by_priority   = dict((await db.execute(select(Incident.priority, func.count(Incident.id)).where(Incident.status.notin_([IncidentStatus.RESOLVED, IncidentStatus.CLOSED])).group_by(Incident.priority))).all())

    recent_inc_r  = await db.execute(select(Incident).order_by(Incident.created_at.desc()).limit(5))
    recent_inc    = [_incident_dict(i) for i in recent_inc_r.scalars().all()]

    return {
        "events":     {"total": total_events, "today": events_today},
        "incidents":  {"total": total_inc, "open": open_inc,
                       "resolved_today": resolved_today, "sla_breached": sla_breached,
                       "by_priority": {str(k): v for k, v in by_priority.items()}},
        "remediation":{"pending_approval": pending_approv,
                       "auto_success_rate": round(auto_success / auto_total * 100, 1)},
        "recent_incidents": recent_inc,
        "targets": {
            "platform_uptime":        "99.9%",
            "api_response_p95":       "<500ms",
            "event_to_ticket":        "<10s",
            "auto_remediation_success": f"{round(auto_success/auto_total*100,1)}%",
            "sla_compliance":         f"{round((1 - sla_breached/max(total_inc,1))*100,1)}%",
        }
    }


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTER: AUTH
# ═══════════════════════════════════════════════════════════════════════════════

auth_router = APIRouter()

class LoginRequest(BaseModel):
    username: str
    password: str

class UserCreate(BaseModel):
    username: str
    password: str
    email:    Optional[str] = None
    full_name:Optional[str] = None
    role:     str = "operator"


@auth_router.post("/login")
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(User).where(User.username == data.username))
    user = r.scalar_one_or_none()
    if not user or not _verify_pw(data.password, user.hashed_password):
        raise HTTPException(401, "Invalid credentials")
    token = jwt.encode(
        {"sub": user.username, "role": user.role,
         "exp": datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)},
        settings.secret_key, algorithm=settings.algorithm
    )
    return {"access_token": token, "token_type": "bearer",
            "username": user.username, "role": user.role}

@auth_router.post("/register")
async def register(data: UserCreate, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(User).where(User.username == data.username))
    if r.scalar_one_or_none():
        raise HTTPException(400, "Username already exists")
    user = User(
        username        = data.username,
        email           = data.email,
        full_name       = data.full_name,
        hashed_password = _hash_pw(data.password),
        role            = data.role,
    )
    db.add(user)
    await db.commit()
    return {"username": user.username, "role": user.role, "created": True}


# ═══════════════════════════════════════════════════════════════════════════════
# SERIALIZER HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _ev(val) -> str:
    """Serialize enum to its plain value string, e.g. 'critical' not 'Severity.CRITICAL'."""
    if val is None:
        return None
    s = str(val)
    return s.split(".")[-1].lower() if "." in s else s

def _raw_event_dict(e: RawEvent) -> dict:
    return {
        "id": e.id, "source": _ev(e.source), "source_host": e.source_host,
        "source_id": e.source_id, "tool_name": e.tool_name,
        "severity": _ev(e.severity), "title": e.title, "message": e.message,
        "affected_host": e.affected_host, "affected_service": e.affected_service,
        "status": _ev(e.status), "received_at": e.received_at,
    }

def _incident_dict(i: Incident) -> dict:
    return {
        "id": i.id, "title": i.title, "description": i.description,
        "status": _ev(i.status), "priority": _ev(i.priority),
        "source": _ev(i.source), "decision_path": _ev(i.decision_path),
        "auto_remediate": i.auto_remediate, "requires_approval": i.requires_approval,
        "assigned_to": i.assigned_to, "assigned_team": i.assigned_team,
        "sla_deadline": i.sla_deadline, "sla_breached": i.sla_breached,
        "escalated": i.escalated, "resolution_notes": i.resolution_notes,
        "created_at": i.created_at, "updated_at": i.updated_at, "resolved_at": i.resolved_at,
    }

def _job_dict(j: RemediationJob) -> dict:
    return {
        "id": j.id, "incident_id": j.incident_id,
        "remediation_type": _ev(j.remediation_type), "action": j.action,
        "target_host": j.target_host, "parameters": j.parameters,
        "status": _ev(j.status), "attempt_number": j.attempt_number,
        "requires_approval": j.requires_approval, "approved_by": j.approved_by,
        "output": j.output, "error": j.error, "exit_code": j.exit_code,
        "rolled_back": j.rolled_back, "poll_count": j.poll_count,
        "created_at": j.created_at, "started_at": j.started_at, "completed_at": j.completed_at,
    }

def _ci_dict(c: ConfigItem) -> dict:
    return {
        "id": c.id, "ci_id": c.ci_id, "hostname": c.hostname,
        "ip_address": c.ip_address, "ci_type": c.ci_type,
        "os": c.os, "environment": c.environment, "location": c.location,
        "owner": c.owner, "team": c.team, "business_service": c.business_service,
        "criticality": c.criticality, "dependent_on": c.dependent_on,
        "supports": c.supports, "tags": c.tags,
        "ssh_user": c.ssh_user,
        "created_at": c.created_at, "updated_at": c.updated_at,
    }
