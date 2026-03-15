"""
Module 7 — Notification Service

Sends alerts via:
  - Slack webhook
  - Microsoft Teams webhook
  - PagerDuty Events API v2
  - Email (SMTP)

Also handles escalation:
  - Monitors SLA deadlines
  - Escalates to L2/L3 team when breaching
"""
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.models.all_models import (
    Incident, NotificationLog, NotificationChannel, NotificationStatus,
    IncidentPriority, IncidentStatus
)
from backend.config import get_settings

logger = logging.getLogger("amfi.notifications")
settings = get_settings()

PRIORITY_EMOJI = {
    IncidentPriority.CRITICAL: "🔴",
    IncidentPriority.HIGH:     "🟠",
    IncidentPriority.MEDIUM:   "🟡",
    IncidentPriority.LOW:      "🟢",
}


class NotificationService:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def notify(self, incident: Incident, event: str = "created"):
        """Send notifications for an incident event."""
        tasks = []
        if settings.slack_webhook_url:
            tasks.append(self._notify_slack(incident, event))
        if settings.teams_webhook_url:
            tasks.append(self._notify_teams(incident, event))
        if settings.pagerduty_routing_key and incident.priority == IncidentPriority.CRITICAL:
            tasks.append(self._notify_pagerduty(incident, event))
        if settings.smtp_host and settings.notify_email_to:
            tasks.append(self._notify_email(incident, event))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        else:
            logger.info(
                "Notification skipped for incident %s — no channels configured in .env",
                incident.id
            )

    async def check_sla_and_escalate(self, incident: Incident):
        """Called by scheduler — check SLA breach and escalate if needed."""
        if incident.status in (IncidentStatus.RESOLVED, IncidentStatus.CLOSED):
            return
        if not incident.sla_deadline:
            return

        now = datetime.utcnow()
        if now >= incident.sla_deadline and not incident.sla_breached:
            incident.sla_breached = True
            incident.escalated    = True
            incident.escalated_at = now
            await self.db.flush()
            await self.notify(incident, event="sla_breach")
            logger.warning("SLA BREACHED: incident=%s priority=%s", incident.id, incident.priority)

        # Warn at 80% of SLA elapsed
        elif not incident.sla_breached:
            elapsed   = (now - incident.created_at).total_seconds() / 60
            total_sla = (incident.sla_deadline - incident.created_at).total_seconds() / 60
            if total_sla > 0 and (elapsed / total_sla) >= 0.8:
                await self.notify(incident, event="sla_warning")

    # ── Slack ─────────────────────────────────────────────────────────────────

    async def _notify_slack(self, incident: Incident, event: str):
        emoji = PRIORITY_EMOJI.get(incident.priority, "⚪")
        color = {"critical": "#FF2D55", "high": "#FF6B35",
                 "medium": "#FFD600", "low": "#00E5A0"}.get(
            str(incident.priority), "#888"
        )
        event_label = {"created": "🚨 New Incident", "sla_breach": "🔥 SLA BREACHED",
                       "sla_warning": "⚠️ SLA Warning", "resolved": "✅ Resolved"}.get(event, event)

        payload = {
            "attachments": [{
                "color":  color,
                "title":  f"{event_label} #{incident.id}: {incident.title}",
                "fields": [
                    {"title": "Priority", "value": f"{emoji} {incident.priority}", "short": True},
                    {"title": "Status",   "value": incident.status,               "short": True},
                    {"title": "Team",     "value": incident.assigned_team or "Unassigned", "short": True},
                    {"title": "SLA Due",  "value": str(incident.sla_deadline)[:16] if incident.sla_deadline else "N/A", "short": True},
                ],
                "footer": "AMFI Platform",
                "ts":     int(datetime.utcnow().timestamp()),
            }]
        }
        await self._post(settings.slack_webhook_url, payload,
                         incident, NotificationChannel.SLACK)

    # ── MS Teams ──────────────────────────────────────────────────────────────

    async def _notify_teams(self, incident: Incident, event: str):
        payload = {
            "@type":      "MessageCard",
            "@context":   "http://schema.org/extensions",
            "themeColor": "FF2D55" if incident.priority == IncidentPriority.CRITICAL else "FF6B35",
            "summary":    f"AMFI Incident #{incident.id}",
            "sections": [{
                "activityTitle": f"Incident #{incident.id}: {incident.title}",
                "facts": [
                    {"name": "Priority", "value": str(incident.priority)},
                    {"name": "Status",   "value": str(incident.status)},
                    {"name": "Team",     "value": incident.assigned_team or "Unassigned"},
                    {"name": "Event",    "value": event},
                ],
            }]
        }
        await self._post(settings.teams_webhook_url, payload,
                         incident, NotificationChannel.TEAMS)

    # ── PagerDuty ─────────────────────────────────────────────────────────────

    async def _notify_pagerduty(self, incident: Incident, event: str):
        pd_event  = "resolve" if event == "resolved" else "trigger"
        severity  = {"critical": "critical", "high": "error",
                     "medium": "warning", "low": "info"}.get(str(incident.priority), "warning")
        payload = {
            "routing_key":  settings.pagerduty_routing_key,
            "event_action": pd_event,
            "dedup_key":    f"amfi-incident-{incident.id}",
            "payload": {
                "summary":  incident.title,
                "severity": severity,
                "source":   incident.source or "amfi",
                "custom_details": {
                    "incident_id": incident.id,
                    "priority":    str(incident.priority),
                    "team":        incident.assigned_team,
                }
            }
        }
        await self._post("https://events.pagerduty.com/v2/enqueue", payload,
                         incident, NotificationChannel.PAGERDUTY)

    # ── Email ─────────────────────────────────────────────────────────────────

    async def _notify_email(self, incident: Incident, event: str):
        import smtplib
        from email.mime.text import MIMEText
        loop = asyncio.get_event_loop()

        subject = f"[AMFI] Incident #{incident.id} {event.upper()}: {incident.title}"
        body = f"""
AMFI Incident Notification
===========================
ID:       #{incident.id}
Title:    {incident.title}
Priority: {incident.priority}
Status:   {incident.status}
Team:     {incident.assigned_team or 'Unassigned'}
Event:    {event}
SLA:      {str(incident.sla_deadline)[:16] if incident.sla_deadline else 'N/A'}
Created:  {str(incident.created_at)[:16]}
"""
        log = NotificationLog(
            incident_id = incident.id,
            channel     = NotificationChannel.EMAIL,
            recipient   = settings.notify_email_to,
            subject     = subject,
            body        = body,
            status      = NotificationStatus.PENDING,
        )
        self.db.add(log)

        def _send():
            try:
                msg = MIMEText(body)
                msg["Subject"] = subject
                msg["From"]    = settings.smtp_user
                msg["To"]      = settings.notify_email_to
                with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as s:
                    s.starttls()
                    s.login(settings.smtp_user, settings.smtp_password)
                    s.send_message(msg)
                return True
            except Exception as e:
                logger.error("Email send failed: %s", e)
                return False

        ok = await loop.run_in_executor(None, _send)
        log.status  = NotificationStatus.SENT if ok else NotificationStatus.FAILED
        log.sent_at = datetime.utcnow()
        await self.db.flush()

    # ── HTTP POST helper ──────────────────────────────────────────────────────

    async def _post(self, url: str, payload: dict, incident: Incident, channel: NotificationChannel):
        log = NotificationLog(
            incident_id = incident.id,
            channel     = channel,
            body        = str(payload)[:2000],
            status      = NotificationStatus.PENDING,
        )
        self.db.add(log)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                log.status  = NotificationStatus.SENT
                log.sent_at = datetime.utcnow()
                logger.info("Notification sent via %s for incident %s", channel, incident.id)
        except Exception as e:
            log.status = NotificationStatus.FAILED
            log.error  = str(e)
            logger.error("Notification failed via %s: %s", channel, e)
        await self.db.flush()
