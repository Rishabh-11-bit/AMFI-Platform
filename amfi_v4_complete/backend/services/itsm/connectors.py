"""
AMFI v4 — ITSM Connectors
Creates and updates tickets in all configured ITSM platforms when an incident
is escalated to L3. All calls are best-effort — failures are logged, never raised.

Supported:
  - ServiceNow (Table API)
  - Jira Service Management (REST API v3)
  - Freshservice (REST API v2)
  - Zendesk (REST API v2)
  - ManageEngine ServiceDesk Plus (REST API v3)
  - BMC Remedy / Helix ITSM (REST API)
"""
import base64
import logging
from typing import Optional
import httpx

from backend.config import get_settings

logger   = logging.getLogger("amfi.itsm")
settings = get_settings()


# ── Priority maps ──────────────────────────────────────────────────────────────

_SNOW_URGENCY = {"p1": "1", "p2": "2", "p3": "3", "p4": "4"}
_JIRA_PRIORITY = {"p1": "Highest", "p2": "High", "p3": "Medium", "p4": "Low"}
_FRESH_PRIORITY = {"p1": 4, "p2": 3, "p3": 2, "p4": 1}   # 4=Urgent,3=High,2=Medium,1=Low
_ZENDESK_PRIORITY = {"p1": "urgent", "p2": "high", "p3": "normal", "p4": "low"}
_REMEDY_URGENCY = {"p1": "1-Critical", "p2": "2-High", "p3": "3-Medium", "p4": "4-Low"}


def _basic_auth(user: str, password: str) -> str:
    return base64.b64encode(f"{user}:{password}".encode()).decode()


# ── ServiceNow ────────────────────────────────────────────────────────────────

class ServiceNowConnector:
    """ServiceNow Table API — creates and resolves incident records."""

    async def create_ticket(self, incident) -> Optional[str]:
        if not (settings.servicenow_url and settings.servicenow_user and settings.servicenow_password):
            return None
        try:
            priority = getattr(incident, "priority", "p3") or "p3"
            body: dict = {
                "short_description": getattr(incident, "title", "")[:160],
                "description": (
                    f"AMFI Incident: {getattr(incident, 'number', '')}\n"
                    f"Host: {getattr(incident, 'affected_host', '') or 'N/A'}\n"
                    f"Fault: {getattr(incident, 'fault_category', '') or 'N/A'}\n"
                    f"Priority: {priority}\n\n"
                    f"{getattr(incident, 'description', '') or ''}"
                )[:4000],
                "urgency":    _SNOW_URGENCY.get(priority, "3"),
                "impact":     _SNOW_URGENCY.get(priority, "3"),
                "category":   "Software",
                "u_amfi_number": getattr(incident, "number", ""),
            }
            if settings.servicenow_assignment_group:
                body["assignment_group"] = settings.servicenow_assignment_group
            if settings.servicenow_caller_id:
                body["caller_id"] = settings.servicenow_caller_id

            url = f"{settings.servicenow_url.rstrip('/')}/api/now/table/{settings.servicenow_incident_table}"
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    url,
                    json=body,
                    headers={
                        "Authorization": f"Basic {_basic_auth(settings.servicenow_user, settings.servicenow_password)}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                )
                if resp.status_code in (200, 201):
                    sys_id = resp.json().get("result", {}).get("sys_id")
                    number = resp.json().get("result", {}).get("number", sys_id)
                    logger.info("ServiceNow ticket created: %s for %s", number, getattr(incident, "number", ""))
                    return sys_id
                logger.error("ServiceNow create failed %d: %s", resp.status_code, resp.text[:200])
        except Exception as e:
            logger.debug("ServiceNow create error: %s", e)
        return None

    async def update_ticket(self, sys_id: str, status: str, resolution: str) -> bool:
        if not (settings.servicenow_url and settings.servicenow_user and sys_id):
            return False
        try:
            url = f"{settings.servicenow_url.rstrip('/')}/api/now/table/{settings.servicenow_incident_table}/{sys_id}"
            body = {
                "state":       "6",   # Resolved
                "close_notes": resolution[:4000],
                "close_code":  "Solved (Permanently)",
            }
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.patch(
                    url,
                    json=body,
                    headers={
                        "Authorization": f"Basic {_basic_auth(settings.servicenow_user, settings.servicenow_password)}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                )
                return resp.status_code in (200, 201)
        except Exception as e:
            logger.debug("ServiceNow update error: %s", e)
        return False


# ── Jira Service Management ───────────────────────────────────────────────────

class JiraConnector:
    """Jira Service Management REST API v3."""

    async def create_ticket(self, incident) -> Optional[str]:
        if not (settings.jira_url and settings.jira_user and settings.jira_api_token):
            return None
        try:
            priority = getattr(incident, "priority", "p3") or "p3"
            description_text = (
                f"AMFI Incident: {getattr(incident, 'number', '')}\n"
                f"Host: {getattr(incident, 'affected_host', '') or 'N/A'}\n"
                f"Fault: {getattr(incident, 'fault_category', '') or 'N/A'}\n\n"
                f"{getattr(incident, 'description', '') or 'No description provided.'}"
            )
            body = {
                "fields": {
                    "project":    {"key": settings.jira_project_key},
                    "issuetype":  {"name": settings.jira_issue_type},
                    "summary":    getattr(incident, "title", "")[:255],
                    "description": {
                        "type": "doc", "version": 1,
                        "content": [{
                            "type": "paragraph",
                            "content": [{"type": "text", "text": description_text[:3000]}],
                        }],
                    },
                    "priority": {"name": _JIRA_PRIORITY.get(priority, "Medium")},
                    "labels":   ["amfi", "noc"],
                }
            }
            url = f"{settings.jira_url.rstrip('/')}/rest/api/3/issue"
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    url,
                    json=body,
                    auth=(settings.jira_user, settings.jira_api_token),
                    headers={"Accept": "application/json", "Content-Type": "application/json"},
                )
                if resp.status_code in (200, 201):
                    key = resp.json().get("key")
                    logger.info("Jira issue created: %s for %s", key, getattr(incident, "number", ""))
                    return key
                logger.error("Jira create failed %d: %s", resp.status_code, resp.text[:200])
        except Exception as e:
            logger.debug("Jira create error: %s", e)
        return None

    async def update_ticket(self, issue_key: str, status: str, resolution: str) -> bool:
        if not (settings.jira_url and settings.jira_user and issue_key):
            return False
        try:
            # Get available transitions
            url = f"{settings.jira_url.rstrip('/')}/rest/api/3/issue/{issue_key}/transitions"
            auth = (settings.jira_user, settings.jira_api_token)
            async with httpx.AsyncClient(timeout=15) as client:
                tr = await client.get(url, auth=auth)
                transitions = tr.json().get("transitions", [])
                # Find Done/Resolved/Closed transition
                done_id = None
                for t in transitions:
                    if t.get("name", "").lower() in ("done", "resolved", "closed", "complete"):
                        done_id = t["id"]
                        break
                if not done_id and transitions:
                    done_id = transitions[-1]["id"]

                if done_id:
                    await client.post(
                        url, auth=auth,
                        json={"transition": {"id": done_id}},
                        headers={"Content-Type": "application/json"},
                    )
                    # Add resolution comment
                    comment_url = f"{settings.jira_url.rstrip('/')}/rest/api/3/issue/{issue_key}/comment"
                    await client.post(
                        comment_url, auth=auth,
                        json={"body": {"type": "doc", "version": 1,
                                       "content": [{"type": "paragraph",
                                                    "content": [{"type": "text", "text": resolution[:3000]}]}]}},
                        headers={"Content-Type": "application/json"},
                    )
                    return True
        except Exception as e:
            logger.debug("Jira update error: %s", e)
        return False


# ── Freshservice ──────────────────────────────────────────────────────────────

class FreshserviceConnector:
    """Freshservice REST API v2."""

    async def create_ticket(self, incident) -> Optional[str]:
        if not (settings.freshservice_domain and settings.freshservice_api_key):
            return None
        try:
            priority = getattr(incident, "priority", "p3") or "p3"
            body = {
                "subject":     getattr(incident, "title", "")[:255],
                "description": (
                    f"<p><b>AMFI Incident:</b> {getattr(incident, 'number', '')}</p>"
                    f"<p><b>Host:</b> {getattr(incident, 'affected_host', '') or 'N/A'}</p>"
                    f"<p><b>Fault:</b> {getattr(incident, 'fault_category', '') or 'N/A'}</p>"
                    f"<p>{getattr(incident, 'description', '') or ''}</p>"
                ),
                "email":    "amfi@noc.local",
                "priority": _FRESH_PRIORITY.get(priority, 2),
                "status":   2,   # Open
                "source":   2,   # Portal
                "tags":     ["amfi", "noc"],
            }
            url = f"https://{settings.freshservice_domain}/api/v2/tickets"
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    url,
                    json=body,
                    auth=(settings.freshservice_api_key, "X"),
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code in (200, 201):
                    ticket_id = resp.json().get("ticket", {}).get("id")
                    logger.info("Freshservice ticket created: %s for %s", ticket_id, getattr(incident, "number", ""))
                    return str(ticket_id)
                logger.error("Freshservice create failed %d: %s", resp.status_code, resp.text[:200])
        except Exception as e:
            logger.debug("Freshservice create error: %s", e)
        return None

    async def update_ticket(self, ticket_id: str, status: str, resolution: str) -> bool:
        if not (settings.freshservice_domain and settings.freshservice_api_key and ticket_id):
            return False
        try:
            url = f"https://{settings.freshservice_domain}/api/v2/tickets/{ticket_id}"
            body = {
                "status": 5,   # Resolved
                "resolution": {"content": resolution[:3000]},
            }
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.put(
                    url, json=body,
                    auth=(settings.freshservice_api_key, "X"),
                    headers={"Content-Type": "application/json"},
                )
                return resp.status_code in (200, 201)
        except Exception as e:
            logger.debug("Freshservice update error: %s", e)
        return False


# ── Zendesk ───────────────────────────────────────────────────────────────────

class ZendeskConnector:
    """Zendesk REST API v2."""

    async def create_ticket(self, incident) -> Optional[str]:
        if not (settings.zendesk_subdomain and settings.zendesk_email and settings.zendesk_api_token):
            return None
        try:
            priority = getattr(incident, "priority", "p3") or "p3"
            body = {
                "ticket": {
                    "subject":  getattr(incident, "title", "")[:255],
                    "comment":  {
                        "body": (
                            f"AMFI Incident: {getattr(incident, 'number', '')}\n"
                            f"Host: {getattr(incident, 'affected_host', '') or 'N/A'}\n"
                            f"Fault: {getattr(incident, 'fault_category', '') or 'N/A'}\n\n"
                            f"{getattr(incident, 'description', '') or ''}"
                        )[:3000],
                    },
                    "priority": _ZENDESK_PRIORITY.get(priority, "normal"),
                    "tags":     ["amfi", "noc"],
                    "type":     "incident",
                }
            }
            url = f"https://{settings.zendesk_subdomain}.zendesk.com/api/v2/tickets"
            auth_str = f"{settings.zendesk_email}/token:{settings.zendesk_api_token}"
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    url, json=body,
                    headers={
                        "Authorization": f"Basic {base64.b64encode(auth_str.encode()).decode()}",
                        "Content-Type": "application/json",
                    },
                )
                if resp.status_code in (200, 201):
                    ticket_id = resp.json().get("ticket", {}).get("id")
                    logger.info("Zendesk ticket created: %s for %s", ticket_id, getattr(incident, "number", ""))
                    return str(ticket_id)
                logger.error("Zendesk create failed %d: %s", resp.status_code, resp.text[:200])
        except Exception as e:
            logger.debug("Zendesk create error: %s", e)
        return None

    async def update_ticket(self, ticket_id: str, status: str, resolution: str) -> bool:
        if not (settings.zendesk_subdomain and settings.zendesk_email and ticket_id):
            return False
        try:
            url = f"https://{settings.zendesk_subdomain}.zendesk.com/api/v2/tickets/{ticket_id}"
            auth_str = f"{settings.zendesk_email}/token:{settings.zendesk_api_token}"
            body = {
                "ticket": {
                    "status":  "solved",
                    "comment": {"body": resolution[:3000], "public": False},
                }
            }
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.put(
                    url, json=body,
                    headers={
                        "Authorization": f"Basic {base64.b64encode(auth_str.encode()).decode()}",
                        "Content-Type": "application/json",
                    },
                )
                return resp.status_code in (200, 201)
        except Exception as e:
            logger.debug("Zendesk update error: %s", e)
        return False


# ── ManageEngine ServiceDesk Plus ─────────────────────────────────────────────

class ManageEngineConnector:
    """ManageEngine ServiceDesk Plus REST API v3."""

    async def create_ticket(self, incident) -> Optional[str]:
        if not (settings.manageengine_url and settings.manageengine_api_key):
            return None
        try:
            priority = getattr(incident, "priority", "p3") or "p3"
            priority_name = {"p1": "High", "p2": "High", "p3": "Medium", "p4": "Low"}.get(priority, "Medium")
            body = {
                "request": {
                    "subject": getattr(incident, "title", "")[:255],
                    "description": (
                        f"AMFI Incident: {getattr(incident, 'number', '')}\n"
                        f"Host: {getattr(incident, 'affected_host', '') or 'N/A'}\n"
                        f"Fault: {getattr(incident, 'fault_category', '') or 'N/A'}\n\n"
                        f"{getattr(incident, 'description', '') or ''}"
                    )[:3000],
                    "urgency":  {"name": priority_name},
                    "impact":   {"name": "Affects Business"},
                    "category": {"name": "Network"},
                }
            }
            url = f"{settings.manageengine_url.rstrip('/')}/api/v3/requests"
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    url, json=body,
                    headers={
                        "authtoken":    settings.manageengine_api_key,
                        "Content-Type": "application/json",
                        "Accept":       "application/json",
                    },
                )
                if resp.status_code in (200, 201):
                    req_id = resp.json().get("request", {}).get("id")
                    logger.info("ManageEngine ticket created: %s for %s", req_id, getattr(incident, "number", ""))
                    return str(req_id)
                logger.error("ManageEngine create failed %d: %s", resp.status_code, resp.text[:200])
        except Exception as e:
            logger.debug("ManageEngine create error: %s", e)
        return None

    async def update_ticket(self, ticket_id: str, status: str, resolution: str) -> bool:
        if not (settings.manageengine_url and settings.manageengine_api_key and ticket_id):
            return False
        try:
            url = f"{settings.manageengine_url.rstrip('/')}/api/v3/requests/{ticket_id}"
            body = {
                "request": {
                    "status":       {"name": "Resolved"},
                    "closure_info": {"closure_comments": resolution[:3000]},
                }
            }
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.put(
                    url, json=body,
                    headers={
                        "authtoken":    settings.manageengine_api_key,
                        "Content-Type": "application/json",
                    },
                )
                return resp.status_code in (200, 201)
        except Exception as e:
            logger.debug("ManageEngine update error: %s", e)
        return False


# ── BMC Remedy / Helix ITSM ───────────────────────────────────────────────────

class RemedyConnector:
    """BMC Remedy / Helix ITSM REST API."""

    _jwt_token: str = ""

    async def _get_token(self) -> Optional[str]:
        if not (settings.remedy_url and settings.remedy_user and settings.remedy_password):
            return None
        try:
            async with httpx.AsyncClient(timeout=15, verify=False) as client:
                resp = await client.post(
                    f"{settings.remedy_url.rstrip('/')}/api/jwt/login",
                    json={"username": settings.remedy_user, "password": settings.remedy_password},
                )
                if resp.status_code == 200:
                    self._jwt_token = resp.text.strip().strip('"')
                    return self._jwt_token
        except Exception as e:
            logger.debug("Remedy auth error: %s", e)
        return None

    async def create_ticket(self, incident) -> Optional[str]:
        if not settings.remedy_url:
            return None
        token = await self._get_token()
        if not token:
            return None
        try:
            priority = getattr(incident, "priority", "p3") or "p3"
            body = {
                "values": {
                    "Summary":         getattr(incident, "title", "")[:254],
                    "Notes":           (
                        f"AMFI Incident: {getattr(incident, 'number', '')}\n"
                        f"Host: {getattr(incident, 'affected_host', '') or 'N/A'}\n"
                        f"Fault: {getattr(incident, 'fault_category', '') or 'N/A'}\n\n"
                        f"{getattr(incident, 'description', '') or ''}"
                    )[:3000],
                    "Urgency":         _REMEDY_URGENCY.get(priority, "3-Medium"),
                    "Impact":          "2-Significant/Large",
                    "Reported Source": "Systems Management",
                    "Service Type":    "Infrastructure Event",
                    "Status":          "Assigned",
                }
            }
            url = f"{settings.remedy_url.rstrip('/')}/api/arsys/v1/entry/HPD:IncidentInterface_Create"
            async with httpx.AsyncClient(timeout=15, verify=False) as client:
                resp = await client.post(
                    url, json=body,
                    headers={
                        "Authorization": f"AR-JWT {token}",
                        "Content-Type":  "application/json",
                    },
                )
                if resp.status_code == 201:
                    location = resp.headers.get("Location", "")
                    entry_id = location.split("/")[-1] if location else None
                    logger.info("Remedy incident created: %s for %s", entry_id, getattr(incident, "number", ""))
                    return entry_id
                logger.error("Remedy create failed %d: %s", resp.status_code, resp.text[:200])
        except Exception as e:
            logger.debug("Remedy create error: %s", e)
        return None

    async def update_ticket(self, entry_id: str, status: str, resolution: str) -> bool:
        if not settings.remedy_url or not entry_id:
            return False
        token = self._jwt_token or await self._get_token()
        if not token:
            return False
        try:
            url = f"{settings.remedy_url.rstrip('/')}/api/arsys/v1/entry/HPD:IncidentInterface/{entry_id}"
            body = {
                "values": {
                    "Status":     "Resolved",
                    "Resolution": resolution[:3000],
                }
            }
            async with httpx.AsyncClient(timeout=15, verify=False) as client:
                resp = await client.put(
                    url, json=body,
                    headers={"Authorization": f"AR-JWT {token}", "Content-Type": "application/json"},
                )
                return resp.status_code in (200, 204)
        except Exception as e:
            logger.debug("Remedy update error: %s", e)
        return False


# ── Top-level helpers ─────────────────────────────────────────────────────────

_CONNECTORS = {
    "servicenow": ServiceNowConnector,
    "jira":       JiraConnector,
    "freshservice": FreshserviceConnector,
    "zendesk":    ZendeskConnector,
    "manageengine": ManageEngineConnector,
    "remedy":     RemedyConnector,
}


async def create_itsm_ticket(incident) -> dict:
    """
    Try all configured ITSM connectors concurrently.
    Returns {tool_name: ticket_id} for every ticket successfully created.
    """
    import asyncio

    async def _try_create(name: str, cls) -> tuple[str, Optional[str]]:
        try:
            connector = cls()
            ticket_id = await connector.create_ticket(incident)
            return name, ticket_id
        except Exception as e:
            logger.debug("ITSM %s create error: %s", name, e)
            return name, None

    results = await asyncio.gather(*[
        _try_create(name, cls) for name, cls in _CONNECTORS.items()
    ], return_exceptions=False)

    return {name: tid for name, tid in results if tid}


async def resolve_itsm_tickets(incident, ticket_refs: dict, resolution: str) -> None:
    """
    Update all previously created ITSM tickets to resolved.
    ticket_refs: {tool_name: ticket_id}
    """
    import asyncio

    async def _try_resolve(name: str, ticket_id: str) -> None:
        try:
            cls = _CONNECTORS.get(name)
            if cls:
                connector = cls()
                await connector.update_ticket(ticket_id, "resolved", resolution)
                logger.info("ITSM %s ticket %s resolved", name, ticket_id)
        except Exception as e:
            logger.debug("ITSM %s resolve error: %s", name, e)

    await asyncio.gather(*[
        _try_resolve(name, tid) for name, tid in ticket_refs.items()
    ], return_exceptions=False)
