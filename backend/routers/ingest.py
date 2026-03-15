"""
Ingestion Router — Module 1

HTTP endpoints for event ingestion:

  POST /api/ingest/alertmanager   ← Prometheus Alertmanager webhook
  POST /api/ingest/webhook        ← Generic JSON webhook (any tool)
  POST /api/ingest/manual         ← Manual test event via API/UI
  GET  /api/ingest/events         ← List stored raw events
  GET  /api/ingest/events/{id}    ← Get single event
  GET  /api/ingest/stats          ← Counts by source/severity/status
  GET  /api/ingest/health         ← Listener health check

Configure Alertmanager to POST to:
  http://<your-server>:8000/api/ingest/alertmanager

alertmanager.yml example:
  receivers:
    - name: amfi
      webhook_configs:
        - url: 'http://<amfi-ip>:8000/api/ingest/alertmanager'
          send_resolved: true
  route:
    receiver: amfi
"""
from datetime import datetime
from typing import Optional, List, Any
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel

from backend.database import get_db
from backend.models import RawEvent, IngestionSource, Severity, RawEventStatus
from backend.services.ingestion_service import IngestionService

router = APIRouter()


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class AlertmanagerLabel(BaseModel):
    """Flexible — Alertmanager labels are arbitrary key/value."""
    model_config = {"extra": "allow"}


class AlertmanagerAlert(BaseModel):
    status: str = "firing"
    labels: dict = {}
    annotations: dict = {}
    startsAt: Optional[str] = None
    endsAt: Optional[str] = None
    fingerprint: Optional[str] = None
    generatorURL: Optional[str] = None


class AlertmanagerPayload(BaseModel):
    """Full Alertmanager webhook payload."""
    version: Optional[str] = None
    groupKey: Optional[str] = None
    status: Optional[str] = None
    receiver: Optional[str] = None
    groupLabels: dict = {}
    commonLabels: dict = {}
    commonAnnotations: dict = {}
    externalURL: Optional[str] = None
    alerts: List[AlertmanagerAlert] = []


class WebhookPayload(BaseModel):
    """Generic webhook — accept any JSON."""
    model_config = {"extra": "allow"}


class ManualEventCreate(BaseModel):
    title: str
    message: Optional[str] = None
    severity: Severity = Severity.WARNING
    affected_host: Optional[str] = None
    affected_service: Optional[str] = None
    tool_name: Optional[str] = "manual"


class RawEventResponse(BaseModel):
    id: int
    source: str
    source_host: Optional[str]
    source_id: Optional[str]
    tool_name: Optional[str]
    severity: str
    title: str
    message: Optional[str]
    affected_host: Optional[str]
    affected_service: Optional[str]
    status: str
    received_at: datetime
    validated_at: Optional[datetime]

    model_config = {"from_attributes": True}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/alertmanager", summary="Prometheus Alertmanager webhook")
async def ingest_alertmanager(
    payload: AlertmanagerPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Receives alerts from Prometheus Alertmanager.
    One call may contain multiple alerts (one per firing rule).
    Returns list of created event IDs.
    """
    source_host = request.client.host if request.client else None
    svc = IngestionService(db)
    events = await svc.ingest_alertmanager(payload.model_dump(), source_host)
    return {
        "received": len(events),
        "events": [
            {"id": e.id, "status": e.status, "title": e.title, "severity": e.severity}
            for e in events
        ],
    }


@router.post("/webhook", summary="Generic JSON webhook")
async def ingest_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Generic endpoint — accepts any JSON body.
    Useful for tools that let you customize the webhook payload.
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    source_host = request.client.host if request.client else None
    svc = IngestionService(db)
    event = await svc.ingest_webhook(payload, source_host)
    return {"id": event.id, "status": event.status, "title": event.title}


@router.post("/manual", summary="Manually create a test event")
async def ingest_manual(
    data: ManualEventCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Create an event manually — useful for testing the pipeline
    without needing a real NMS alert.
    """
    source_host = request.client.host if request.client else "manual"
    svc = IngestionService(db)
    event = await svc.ingest_webhook(
        {
            "title":    data.title,
            "message":  data.message,
            "severity": data.severity.value,
            "host":     data.affected_host,
            "service":  data.affected_service,
            "tool":     data.tool_name,
        },
        source_host,
    )
    return {"id": event.id, "status": event.status, "title": event.title}


@router.get("/events", response_model=List[RawEventResponse])
async def list_events(
    source:   Optional[str] = None,
    severity: Optional[str] = None,
    status:   Optional[str] = None,
    host:     Optional[str] = None,
    skip:     int = Query(0, ge=0),
    limit:    int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List all ingested raw events with optional filters."""
    q = select(RawEvent)
    if source:
        q = q.where(RawEvent.source == source)
    if severity:
        q = q.where(RawEvent.severity == severity)
    if status:
        q = q.where(RawEvent.status == status)
    if host:
        q = q.where(RawEvent.affected_host.contains(host))
    q = q.order_by(RawEvent.received_at.desc()).offset(skip).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/events/{event_id}", response_model=RawEventResponse)
async def get_event(event_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(RawEvent).where(RawEvent.id == event_id))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.get("/events/{event_id}/raw")
async def get_event_raw(event_id: int, db: AsyncSession = Depends(get_db)):
    """Get the full raw_payload of a specific event."""
    result = await db.execute(select(RawEvent).where(RawEvent.id == event_id))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return {"id": event.id, "raw_payload": event.raw_payload}


@router.get("/stats")
async def ingestion_stats(db: AsyncSession = Depends(get_db)):
    """Counts broken down by source, severity, and status."""
    total = (await db.execute(select(func.count(RawEvent.id)))).scalar() or 0

    by_source = dict(
        (await db.execute(
            select(RawEvent.source, func.count(RawEvent.id)).group_by(RawEvent.source)
        )).all()
    )
    by_severity = dict(
        (await db.execute(
            select(RawEvent.severity, func.count(RawEvent.id)).group_by(RawEvent.severity)
        )).all()
    )
    by_status = dict(
        (await db.execute(
            select(RawEvent.status, func.count(RawEvent.id)).group_by(RawEvent.status)
        )).all()
    )

    return {
        "total":       total,
        "by_source":   {str(k): v for k, v in by_source.items()},
        "by_severity": {str(k): v for k, v in by_severity.items()},
        "by_status":   {str(k): v for k, v in by_status.items()},
    }


@router.get("/health")
async def listener_health():
    """Returns the status of each listener."""
    # Imported here to avoid circular imports
    from backend.main import listener_status
    return {
        "api":         "running",
        "snmp":        listener_status.get("snmp", "unknown"),
        "syslog":      listener_status.get("syslog", "unknown"),
        "mqtt":        listener_status.get("mqtt", "unknown"),
        "alertmanager":"ready",  # always ready (it's just HTTP)
    }
