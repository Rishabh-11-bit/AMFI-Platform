"""
Event Ingestion Service — Module 1

Responsibilities:
  1. Validate incoming payloads (schema + basic sanity checks)
  2. Normalize to a common internal schema regardless of source
  3. Detect duplicates (same source_id within time window)
  4. Persist to DB
  5. Emit to downstream (Module 2 will read FORWARDED events)

Each source protocol has its own parse_* method.
All of them return a dict that maps to RawEvent columns.
"""
from datetime import datetime, timedelta
from typing import Optional
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.models.all_models import (
    RawEvent, IngestionSource, Severity, RawEventStatus
)

logger = logging.getLogger("amfi.ingestion")


# ── Severity mapping helpers ──────────────────────────────────────────────────

PROM_SEVERITY_MAP = {
    "critical": Severity.CRITICAL,
    "error":    Severity.MAJOR,
    "warning":  Severity.WARNING,
    "info":     Severity.INFO,
}

SYSLOG_SEVERITY_MAP = {
    0: Severity.CRITICAL,   # Emergency
    1: Severity.CRITICAL,   # Alert
    2: Severity.CRITICAL,   # Critical
    3: Severity.MAJOR,      # Error
    4: Severity.WARNING,    # Warning
    5: Severity.INFO,       # Notice
    6: Severity.INFO,       # Informational
    7: Severity.INFO,       # Debug
}


# ── Duplicate detection window ────────────────────────────────────────────────

DEDUP_WINDOW_SECONDS = 120  # suppress same source_id within 2 minutes


# ── Main service class ────────────────────────────────────────────────────────

class IngestionService:

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── PUBLIC: process a raw payload from any source ─────────────────────────

    async def ingest_alertmanager(self, payload: dict, source_host: str = None) -> list[RawEvent]:
        """
        Parse a Prometheus Alertmanager webhook payload.

        Alertmanager sends one POST per group, which can contain
        multiple alerts. We create one RawEvent per alert.
        """
        alerts = payload.get("alerts", [])
        if not alerts:
            logger.warning("Alertmanager payload has no alerts: %s", payload)
            return []

        results = []
        for alert in alerts:
            normalized = self._parse_alertmanager_alert(alert, payload, source_host)
            event = await self._save(normalized)
            results.append(event)

        return results

    async def ingest_webhook(self, payload: dict, source_host: str = None) -> RawEvent:
        """Generic webhook — expects our own schema or best-effort parse."""
        normalized = self._parse_generic_webhook(payload, source_host)
        return await self._save(normalized)

    async def ingest_snmp(self, trap_data: dict, source_host: str = None) -> RawEvent:
        """SNMP trap parsed by the listener and passed as a dict."""
        normalized = self._parse_snmp_trap(trap_data, source_host)
        return await self._save(normalized)

    async def ingest_syslog(self, syslog_data: dict, source_host: str = None) -> RawEvent:
        """Syslog message parsed by the listener."""
        normalized = self._parse_syslog(syslog_data, source_host)
        return await self._save(normalized)

    async def ingest_mqtt(self, topic: str, payload: dict, source_host: str = None) -> RawEvent:
        """MQTT message from broker."""
        normalized = self._parse_mqtt(topic, payload, source_host)
        return await self._save(normalized)

    # ── PARSERS — one per source protocol ─────────────────────────────────────

    def _parse_alertmanager_alert(self, alert: dict, group: dict, source_host: str) -> dict:
        """
        Alertmanager alert shape:
        {
          "status": "firing" | "resolved",
          "labels": { "alertname": "...", "severity": "...", "instance": "...", "job": "..." },
          "annotations": { "summary": "...", "description": "..." },
          "startsAt": "2024-01-01T00:00:00Z",
          "fingerprint": "abc123"
        }
        """
        labels      = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        status      = alert.get("status", "firing")

        alert_name  = labels.get("alertname", "UnknownAlert")
        instance    = labels.get("instance", labels.get("host", None))
        job         = labels.get("job", None)
        sev_raw     = labels.get("severity", "warning").lower()
        severity    = PROM_SEVERITY_MAP.get(sev_raw, Severity.WARNING)

        # If resolved, downgrade to INFO
        if status == "resolved":
            severity = Severity.INFO

        summary     = annotations.get("summary", alert_name)
        description = annotations.get("description", "")
        fingerprint = alert.get("fingerprint")

        return {
            "source":           IngestionSource.ALERTMANAGER,
            "source_host":      source_host,
            "source_id":        fingerprint,
            "tool_name":        "prometheus",
            "severity":         severity,
            "title":            f"[{status.upper()}] {summary}",
            "message":          description,
            "affected_host":    instance,
            "affected_service": job,
            "raw_payload":      {"alert": alert, "group_labels": group.get("groupLabels", {})},
        }

    def _parse_generic_webhook(self, payload: dict, source_host: str) -> dict:
        """
        Best-effort parse for any JSON webhook.
        Looks for common field names used by different tools.
        """
        # Try to find severity
        sev_raw = (
            payload.get("severity") or
            payload.get("priority") or
            payload.get("level") or
            "unknown"
        ).lower()
        severity = PROM_SEVERITY_MAP.get(sev_raw, Severity.UNKNOWN)

        title = (
            payload.get("title") or
            payload.get("summary") or
            payload.get("alertname") or
            payload.get("name") or
            "Webhook Event"
        )

        return {
            "source":           IngestionSource.WEBHOOK,
            "source_host":      source_host,
            "source_id":        str(payload.get("id") or payload.get("fingerprint") or ""),
            "tool_name":        payload.get("tool") or payload.get("source") or "unknown",
            "severity":         severity,
            "title":            title,
            "message":          payload.get("description") or payload.get("message") or "",
            "affected_host":    payload.get("host") or payload.get("instance") or payload.get("node"),
            "affected_service": payload.get("service") or payload.get("job"),
            "raw_payload":      payload,
        }

    def _parse_snmp_trap(self, trap: dict, source_host: str) -> dict:
        """
        SNMP trap dict from pysnmp listener:
        {
          "oid": "1.3.6.1.4.1.2021.11.9.0",
          "community": "public",
          "varbinds": { "oid": "value", ... },
          "source_ip": "10.0.0.5"
        }
        """
        oid      = trap.get("oid", "")
        varbinds = trap.get("varbinds", {})

        # Common OID → severity heuristic
        # You can expand this map with your device vendor OIDs
        sev = Severity.WARNING
        if "critical" in str(varbinds).lower():
            sev = Severity.CRITICAL
        elif "down" in str(varbinds).lower():
            sev = Severity.MAJOR

        # Try to extract a human-readable message from varbinds
        msg = " | ".join(f"{k}={v}" for k, v in varbinds.items())

        return {
            "source":           IngestionSource.SNMP_TRAP,
            "source_host":      trap.get("source_ip") or source_host,
            "source_id":        oid,
            "tool_name":        "snmp",
            "severity":         sev,
            "title":            f"SNMP Trap: {oid}",
            "message":          msg,
            "affected_host":    trap.get("source_ip") or source_host,
            "affected_service": None,
            "raw_payload":      trap,
            "snmp_oid":         oid,
            "snmp_community":   trap.get("community"),
        }

    def _parse_syslog(self, msg: dict, source_host: str) -> dict:
        """
        Syslog dict from listener:
        {
          "facility": 1, "severity": 3, "hostname": "srv01",
          "program": "kernel", "message": "...", "timestamp": "..."
        }
        """
        sev_int  = msg.get("severity", 6)
        severity = SYSLOG_SEVERITY_MAP.get(sev_int, Severity.INFO)
        program  = msg.get("program", "syslog")
        hostname = msg.get("hostname") or source_host

        return {
            "source":           IngestionSource.SYSLOG,
            "source_host":      source_host,
            "source_id":        None,
            "tool_name":        "syslog",
            "severity":         severity,
            "title":            f"Syslog [{program}]: {msg.get('message', '')[:120]}",
            "message":          msg.get("message", ""),
            "affected_host":    hostname,
            "affected_service": program,
            "raw_payload":      msg,
            "syslog_facility":  msg.get("facility"),
            "syslog_priority":  sev_int,
            "syslog_program":   program,
        }

    def _parse_mqtt(self, topic: str, payload: dict, source_host: str) -> dict:
        sev_raw  = payload.get("severity", "warning").lower()
        severity = PROM_SEVERITY_MAP.get(sev_raw, Severity.WARNING)

        return {
            "source":           IngestionSource.MQTT,
            "source_host":      source_host,
            "source_id":        payload.get("id"),
            "tool_name":        payload.get("tool", "mqtt"),
            "severity":         severity,
            "title":            payload.get("title", f"MQTT: {topic}"),
            "message":          payload.get("message", ""),
            "affected_host":    payload.get("host"),
            "affected_service": payload.get("service"),
            "raw_payload":      payload,
            "mqtt_topic":       topic,
        }

    # ── INTERNAL: dedup + save ─────────────────────────────────────────────────

    async def _is_duplicate(self, source_id: str, source: IngestionSource) -> bool:
        """Check if same source_id arrived within the dedup window."""
        if not source_id:
            return False
        cutoff = datetime.utcnow() - timedelta(seconds=DEDUP_WINDOW_SECONDS)
        result = await self.db.execute(
            select(RawEvent).where(
                RawEvent.source_id == source_id,
                RawEvent.source    == source,
                RawEvent.received_at >= cutoff,
            ).limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def _validate(self, data: dict) -> Optional[str]:
        """Return error string if invalid, None if OK."""
        if not data.get("title"):
            return "Missing title/summary field"
        if not data.get("source"):
            return "Missing source"
        return None

    async def _save(self, data: dict) -> RawEvent:
        """Validate → dedup → persist."""
        now = datetime.utcnow()

        # Validate
        err = await self._validate(data)
        if err:
            logger.warning("Validation failed: %s | data=%s", err, data)
            event = RawEvent(
                source       = data.get("source", IngestionSource.WEBHOOK),
                title        = data.get("title", "Invalid Event"),
                raw_payload  = data.get("raw_payload"),
                status       = RawEventStatus.INVALID,
                validation_error = err,
            )
            self.db.add(event)
            await self.db.flush()
            return event

        # Dedup
        source_id = data.get("source_id")
        source    = data.get("source")
        if await self._is_duplicate(source_id, source):
            logger.info("Duplicate suppressed: source_id=%s source=%s", source_id, source)
            event = RawEvent(
                source       = source,
                source_id    = source_id,
                title        = data.get("title"),
                raw_payload  = data.get("raw_payload"),
                status       = RawEventStatus.DUPLICATE,
            )
            self.db.add(event)
            await self.db.flush()
            return event

        # Persist as VALIDATED → ready for Module 2
        event = RawEvent(
            source           = source,
            source_host      = data.get("source_host"),
            source_id        = source_id,
            tool_name        = data.get("tool_name"),
            severity         = data.get("severity", Severity.UNKNOWN),
            title            = data.get("title"),
            message          = data.get("message"),
            affected_host    = data.get("affected_host"),
            affected_service = data.get("affected_service"),
            raw_payload      = data.get("raw_payload"),
            snmp_oid         = data.get("snmp_oid"),
            snmp_community   = data.get("snmp_community"),
            syslog_facility  = data.get("syslog_facility"),
            syslog_priority  = data.get("syslog_priority"),
            syslog_program   = data.get("syslog_program"),
            mqtt_topic       = data.get("mqtt_topic"),
            status           = RawEventStatus.VALIDATED,
            validated_at     = now,
        )
        self.db.add(event)
        await self.db.flush()
        logger.info("Ingested event id=%s source=%s severity=%s host=%s",
                    event.id, event.source, event.severity, event.affected_host)
        return event
