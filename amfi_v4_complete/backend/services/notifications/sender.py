"""
AMFI v4 — Notification sender
Sends notifications to all configured channels concurrently:
  Email (SMTP), Slack, Microsoft Teams, PagerDuty, OpsGenie, VictorOps, xMatters
All calls are best-effort — failures are logged, never raised.
"""
import logging
import smtplib
import asyncio
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
import httpx

from backend.config import get_settings

logger   = logging.getLogger("amfi.notifications")
settings = get_settings()

# ── Priority helpers ───────────────────────────────────────────────────────────

def _pd_severity(priority: Optional[str]) -> str:
    """Map AMFI priority to PagerDuty severity."""
    return {"p1": "critical", "p2": "critical", "p3": "warning", "p4": "info"}.get(priority or "p3", "warning")

def _og_priority(priority: Optional[str]) -> str:
    """Map AMFI priority to OpsGenie priority."""
    return {"p1": "P1", "p2": "P2", "p3": "P3", "p4": "P4"}.get(priority or "p3", "P3")


# ── Public API ─────────────────────────────────────────────────────────────────

async def notify_resolved(incident) -> None:
    """Notify all channels when the agent resolves an incident."""
    subject = f"[RESOLVED] {incident.number}: {incident.title[:80]}"
    body = (
        f"Incident {incident.number} has been automatically resolved.\n\n"
        f"Title: {incident.title}\n"
        f"Host: {incident.affected_host or 'N/A'}\n"
        f"Fault: {incident.fault_category or 'N/A'}\n"
        f"Resolution: {incident.resolution or 'N/A'}\n"
        f"Resolved by: {incident.resolved_by or 'agent'}\n"
    )
    await _send_all(subject, body, incident=incident, event_type="resolve")


async def notify_escalation(incident, reason: str = "") -> None:
    """Notify all channels when an incident is escalated to L3."""
    subject = f"[L3 ESCALATION] {incident.number}: {incident.title[:80]}"
    body = (
        f"Incident {incident.number} has been escalated to L3 — automated remediation failed.\n\n"
        f"Title: {incident.title}\n"
        f"Host: {incident.affected_host or 'N/A'}\n"
        f"Fault: {incident.fault_category or 'N/A'}\n"
        f"Priority: {incident.priority or 'N/A'}\n"
        f"Reason: {reason}\n\n"
        f"Please investigate immediately.\n"
    )
    await _send_all(subject, body, incident=incident, event_type="trigger", reason=reason)


async def notify_approval_required(incident, approval) -> None:
    """Notify operators that a high-risk action requires approval."""
    subject = f"[APPROVAL REQUIRED] {incident.number}: {approval.action}"
    body = (
        f"Incident {incident.number} requires human approval for a high-risk action.\n\n"
        f"Action: {approval.action}\n"
        f"Host: {approval.host or incident.affected_host or 'N/A'}\n"
        f"Risk level: {approval.risk_level}\n"
        f"Reason: {approval.reason or 'N/A'}\n"
        f"Rollback plan: {approval.rollback or 'N/A'}\n\n"
        f"Token: {approval.token}\n"
        f"Expires: {approval.expires_at}\n"
    )
    recipients = [e for e in [settings.l1_email, settings.l2_email] if e]
    await _send_all(subject, body, incident=incident, event_type="trigger",
                    email_recipients=recipients)


# ── Internal coordinator ───────────────────────────────────────────────────────

async def _send_all(
    subject: str,
    body: str,
    incident=None,
    event_type: str = "trigger",
    reason: str = "",
    email_recipients: Optional[list] = None,
) -> None:
    """Fire all configured notification channels concurrently."""
    tasks = []

    # Email
    if email_recipients is None:
        email_recipients = [e for e in [settings.l1_email, settings.l2_email, settings.l3_email] if e]
    valid_recipients = [r for r in email_recipients if r and "@" in r]
    if valid_recipients and settings.smtp_host and settings.smtp_user:
        tasks.append(_send_email(subject, body, valid_recipients))

    # Slack
    if settings.slack_webhook:
        tasks.append(_send_slack(subject, body))

    # Microsoft Teams
    if settings.teams_webhook:
        tasks.append(_send_teams(subject, body, incident))

    # PagerDuty
    if settings.pagerduty_integration_key and incident:
        tasks.append(_send_pagerduty(incident, subject, body, event_type))

    # OpsGenie
    if settings.opsgenie_api_key and incident:
        tasks.append(_send_opsgenie(incident, subject, body, event_type))

    # VictorOps / Splunk On-Call
    if settings.victorops_api_key and incident:
        tasks.append(_send_victorops(incident, subject, body, event_type))

    # xMatters
    if settings.xmatters_webhook_url and incident:
        tasks.append(_send_xmatters(incident, subject, body, event_type))

    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                logger.debug("Notification channel error: %s", r)


# ── Email ──────────────────────────────────────────────────────────────────────

async def _send_email(subject: str, body: str, recipients: list[str]) -> None:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _smtp_send, subject, body, recipients)


def _smtp_send(subject: str, body: str, recipients: list[str]) -> None:
    try:
        msg = MIMEMultipart()
        msg["From"]    = settings.smtp_from or settings.smtp_user
        msg["To"]      = ", ".join(recipients)
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
            server.starttls()
            if settings.smtp_user and settings.smtp_password:
                server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.smtp_from or settings.smtp_user, recipients, msg.as_string())
        logger.info("Email sent to %s: %s", recipients, subject[:60])
    except Exception as e:
        logger.debug("SMTP send failed: %s", e)


# ── Slack ──────────────────────────────────────────────────────────────────────

async def _send_slack(subject: str, body: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                settings.slack_webhook,
                json={"text": f"*{subject}*\n{body[:1000]}"},
            )
        logger.info("Slack notification sent: %s", subject[:60])
    except Exception as e:
        logger.debug("Slack send failed: %s", e)


# ── Microsoft Teams ────────────────────────────────────────────────────────────

async def _send_teams(subject: str, body: str, incident=None) -> None:
    """Post an Adaptive Card to a Teams incoming webhook."""
    if not settings.teams_webhook:
        return
    try:
        color = "attention"  # orange/red for escalations
        if incident and getattr(incident, "status", "") == "resolved":
            color = "good"

        card = {
            "type": "message",
            "attachments": [{
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {
                            "type": "TextBlock",
                            "text": subject,
                            "weight": "Bolder",
                            "size": "Medium",
                            "color": color,
                            "wrap": True,
                        },
                        {
                            "type": "TextBlock",
                            "text": body[:800],
                            "wrap": True,
                            "spacing": "Small",
                        },
                    ],
                    "actions": [
                        {
                            "type": "Action.OpenUrl",
                            "title": "View in AMFI",
                            "url": f"{settings.public_url}/incidents/{getattr(incident, 'id', '')}",
                        }
                    ] if incident else [],
                },
            }],
        }
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(settings.teams_webhook, json=card)
        logger.info("Teams notification sent: %s", subject[:60])
    except Exception as e:
        logger.debug("Teams send failed: %s", e)


# ── PagerDuty ─────────────────────────────────────────────────────────────────

async def _send_pagerduty(incident, subject: str, body: str, event_type: str) -> None:
    """Send event to PagerDuty Events API v2."""
    if not settings.pagerduty_integration_key:
        return
    try:
        dedup_key = getattr(incident, "number", "unknown")
        payload   = {
            "routing_key":  settings.pagerduty_integration_key,
            "dedup_key":    dedup_key,
            "event_action": "resolve" if event_type == "resolve" else "trigger",
        }
        if event_type != "resolve":
            payload["payload"] = {
                "summary":   subject,
                "severity":  _pd_severity(getattr(incident, "priority", None)),
                "source":    getattr(incident, "affected_host", "unknown") or "amfi",
                "component": getattr(incident, "affected_service", "") or "",
                "group":     getattr(incident, "fault_category", "") or "",
                "custom_details": {
                    "incident_number": dedup_key,
                    "fault_category":  getattr(incident, "fault_category", ""),
                    "priority":        getattr(incident, "priority", ""),
                    "host":            getattr(incident, "affected_host", ""),
                    "details":         body[:500],
                },
            }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://events.pagerduty.com/v2/enqueue",
                json=payload,
            )
            logger.info("PagerDuty event sent (%s): %s -> %s",
                        event_type, dedup_key, resp.status_code)
    except Exception as e:
        logger.debug("PagerDuty send failed: %s", e)


# ── OpsGenie ──────────────────────────────────────────────────────────────────

async def _send_opsgenie(incident, subject: str, body: str, event_type: str) -> None:
    """Create or close an OpsGenie alert."""
    if not settings.opsgenie_api_key:
        return
    try:
        headers = {
            "Authorization": f"GenieKey {settings.opsgenie_api_key}",
            "Content-Type":  "application/json",
        }
        alias = getattr(incident, "number", "unknown")

        async with httpx.AsyncClient(timeout=10) as client:
            if event_type == "resolve":
                # Close the alert by alias
                await client.post(
                    f"{settings.opsgenie_api_url}/v2/alerts/{alias}/close",
                    headers=headers,
                    json={"user": "AMFI Agent", "note": body[:500]},
                    params={"identifierType": "alias"},
                )
                logger.info("OpsGenie alert closed: %s", alias)
            else:
                payload = {
                    "message":     subject[:130],
                    "alias":       alias,
                    "description": body[:1000],
                    "priority":    _og_priority(getattr(incident, "priority", None)),
                    "source":      "AMFI Agent v4",
                    "tags":        ["amfi", "noc", getattr(incident, "fault_category", "") or "unknown"],
                    "details": {
                        "incident_number": alias,
                        "host":            getattr(incident, "affected_host", "") or "",
                        "fault_category":  getattr(incident, "fault_category", "") or "",
                    },
                }
                resp = await client.post(
                    f"{settings.opsgenie_api_url}/v2/alerts",
                    headers=headers,
                    json=payload,
                )
                logger.info("OpsGenie alert created: %s -> %s", alias, resp.status_code)
    except Exception as e:
        logger.debug("OpsGenie send failed: %s", e)


# ── VictorOps / Splunk On-Call ────────────────────────────────────────────────

async def _send_victorops(incident, subject: str, body: str, event_type: str) -> None:
    """Post to VictorOps REST Endpoint Integration."""
    if not settings.victorops_api_key:
        return
    try:
        message_type = "RECOVERY" if event_type == "resolve" else "CRITICAL"
        if event_type != "resolve":
            prio = getattr(incident, "priority", "p3") or "p3"
            if prio in ("p3", "p4"):
                message_type = "WARNING"

        payload = {
            "message_type":    message_type,
            "entity_id":       getattr(incident, "number", "unknown"),
            "entity_display_name": subject,
            "state_message":   body[:1000],
            "monitoring_tool": "AMFI Agent v4",
            "host_name":       getattr(incident, "affected_host", "") or "",
            "service":         getattr(incident, "affected_service", "") or "",
            "fault_category":  getattr(incident, "fault_category", "") or "",
        }
        url = (
            f"https://alert.victorops.com/integrations/generic/20131114/alert"
            f"/{settings.victorops_api_key}/{settings.victorops_routing_key}"
        )
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
        logger.info("VictorOps event sent (%s): %s -> %s",
                    message_type, payload["entity_id"], resp.status_code)
    except Exception as e:
        logger.debug("VictorOps send failed: %s", e)


# ── xMatters ──────────────────────────────────────────────────────────────────

async def _send_xmatters(incident, subject: str, body: str, event_type: str) -> None:
    """POST to an xMatters inbound integration webhook."""
    if not settings.xmatters_webhook_url:
        return
    try:
        payload = {
            "incident_number": getattr(incident, "number", "unknown"),
            "summary":         subject,
            "body":            body[:1000],
            "priority":        getattr(incident, "priority", "p3") or "p3",
            "host":            getattr(incident, "affected_host", "") or "",
            "fault_category":  getattr(incident, "fault_category", "") or "",
            "event_type":      event_type,
            "status":          getattr(incident, "status", "") or "",
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(settings.xmatters_webhook_url, json=payload)
        logger.info("xMatters notification sent: %s -> %s",
                    payload["incident_number"], resp.status_code)
    except Exception as e:
        logger.debug("xMatters send failed: %s", e)
