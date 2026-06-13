"""
NMS Connectors - polls monitoring tools for active alerts.
Creates incidents automatically and triggers the agent.

Supported:
  - Prometheus / Alertmanager
  - Zabbix
  - SolarWinds Orion (SWIS API)
  - PRTG
  - Generic webhook (already in router)
"""
import logging
import hashlib
from datetime import datetime
from typing import Optional
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_

from backend.models.models import Incident, IncidentStatus, NMSSource
from backend.config import get_settings

settings = get_settings()

logger   = logging.getLogger("amfi.nms")
settings = get_settings()


# ── Shared helpers ─────────────────────────────────────────────────────────────

async def _incident_count(db: AsyncSession) -> int:
    return (await db.execute(select(func.count(Incident.id)))).scalar() or 0


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
    db: AsyncSession,
    title: str,
    description: str,
    host: str,
    service: str,
    source: str,
    source_id: str,
    raw_alert: dict,
) -> Optional[Incident]:
    """Create an incident if not already tracked."""
    if await _is_duplicate(source, source_id, db):
        return None

    count  = await _incident_count(db)
    number = f"INC-{count + 1:04d}"

    inc = Incident(
        number           = number,
        source           = source,
        source_alert_id  = source_id,
        title            = title[:500],
        description      = description,
        affected_host    = host,
        affected_service = service,
        raw_alert        = raw_alert,
        status           = IncidentStatus.NEW,
    )
    db.add(inc)
    await db.flush()
    logger.info("Created %s from %s: %s", number, source, title[:60])
    return inc


# ── Prometheus / Alertmanager ──────────────────────────────────────────────────

class PrometheusConnector:
    """Polls Prometheus Alertmanager for active alerts."""

    def __init__(self, source: NMSSource):
        self.source   = source
        self.base_url = (source.base_url or "").rstrip("/")
        self.token    = source.api_token or ""

    async def poll(self, db: AsyncSession) -> int:
        if not self.base_url:
            return 0
        created = 0
        try:
            headers = {}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"

            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self.base_url}/api/v2/alerts",
                    headers=headers,
                    params={"active": "true", "silenced": "false"},
                )
                if resp.status_code != 200:
                    logger.error("Prometheus %d: %s", resp.status_code, self.base_url)
                    return 0
                alerts = resp.json()

            for alert in alerts:
                labels      = alert.get("labels", {})
                annotations = alert.get("annotations", {})
                alert_name  = labels.get("alertname", "Unknown")
                instance    = (labels.get("instance", "") or "").split(":")[0]
                severity    = labels.get("severity", "warning")
                source_id   = f"prom-{alert_name}-{instance}-{severity}"

                inc = await _create_incident(
                    db,
                    title       = annotations.get("summary") or alert_name,
                    description = annotations.get("description", ""),
                    host        = instance or labels.get("node", "") or labels.get("host", ""),
                    service     = labels.get("job", ""),
                    source      = "prometheus",
                    source_id   = source_id,
                    raw_alert   = alert,
                )
                if inc:
                    created += 1

            # Update last polled
            self.source.last_polled_at = datetime.utcnow()
            self.source.status = "active"
            self.source.last_error = None

        except Exception as e:
            logger.error("Prometheus poll failed %s: %s", self.base_url, e)
            self.source.last_error = str(e)
            self.source.status = "error"

        return created

    async def silence(self, alert_name: str, instance: str, duration_minutes: int = 30) -> bool:
        """Silence an alert in Alertmanager while the agent is remediating."""
        if not self.base_url:
            return False
        try:
            end_time = datetime.utcnow().replace(microsecond=0)
            from datetime import timedelta
            end_time = end_time + timedelta(minutes=duration_minutes)

            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.base_url}/api/v2/silences",
                    json={
                        "matchers": [
                            {"name": "alertname", "value": alert_name, "isRegex": False},
                            {"name": "instance",  "value": instance,   "isRegex": False},
                        ],
                        "startsAt":  datetime.utcnow().isoformat() + "Z",
                        "endsAt":    end_time.isoformat() + "Z",
                        "createdBy": "AMFI Agent v4",
                        "comment":   "Silenced during automated remediation",
                    },
                )
                return resp.status_code == 200
        except Exception as e:
            logger.error("Silence failed: %s", e)
            return False


# ── Zabbix ─────────────────────────────────────────────────────────────────────

class ZabbixConnector:
    """Polls Zabbix for active problems via JSON-RPC API."""

    def __init__(self, source: NMSSource):
        self.source   = source
        self.base_url = (source.base_url or "").rstrip("/")
        self.username = source.username or ""
        self.password = source.password or ""
        self._token: Optional[str] = None

    async def _auth(self) -> Optional[str]:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{self.base_url}/api_jsonrpc.php",
                    json={
                        "jsonrpc": "2.0",
                        "method":  "user.login",
                        "params":  {"username": self.username, "password": self.password},
                        "id":      1,
                    },
                )
                data = resp.json()
                if "error" in data:
                    logger.error("Zabbix auth error: %s", data["error"])
                    return None
                return data.get("result")
        except Exception as e:
            logger.error("Zabbix auth failed: %s", e)
            return None

    async def poll(self, db: AsyncSession) -> int:
        if not self.base_url:
            return 0

        if not self._token:
            self._token = await self._auth()
        if not self._token:
            return 0

        created = 0
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{self.base_url}/api_jsonrpc.php",
                    json={
                        "jsonrpc": "2.0",
                        "method":  "problem.get",
                        "params": {
                            "output":       "extend",
                            "selectHosts":  ["host", "name"],
                            "recent":       True,
                            "sortfield":    ["eventid"],
                            "sortorder":    "DESC",
                            "limit":        50,
                        },
                        "auth": self._token,
                        "id":   2,
                    },
                )
                problems = resp.json().get("result", [])

            severity_map = {"0":"info","1":"warn","2":"avg","3":"high","4":"disaster","5":"disaster"}

            for p in problems:
                hosts     = p.get("hosts", [{}])
                host_name = hosts[0].get("name", "") if hosts else ""
                event_id  = p.get("eventid", "")
                source_id = f"zabbix-{event_id}"

                sev  = severity_map.get(str(p.get("severity", "0")), "unknown")
                name = p.get("name", "Zabbix Alert")

                inc = await _create_incident(
                    db,
                    title       = name,
                    description = f"Severity: {sev} | EventID: {event_id}",
                    host        = host_name,
                    service     = "",
                    source      = "zabbix",
                    source_id   = source_id,
                    raw_alert   = p,
                )
                if inc:
                    created += 1

            self.source.last_polled_at = datetime.utcnow()
            self.source.status = "active"
            self.source.last_error = None

        except Exception as e:
            logger.error("Zabbix poll failed: %s", e)
            self.source.status = "error"
            self.source.last_error = str(e)
            self._token = None  # force re-auth next poll

        return created

    async def acknowledge(self, event_id: str, message: str) -> bool:
        if not self._token:
            return False
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.base_url}/api_jsonrpc.php",
                    json={
                        "jsonrpc": "2.0",
                        "method":  "event.acknowledge",
                        "params": {
                            "eventids": [event_id],
                            "action":   6,
                            "message":  message,
                        },
                        "auth": self._token,
                        "id":   3,
                    },
                )
                return "result" in resp.json()
        except Exception:
            return False


# ── SolarWinds ─────────────────────────────────────────────────────────────────

class SolarWindsConnector:
    """Polls SolarWinds Orion via SWIS REST API."""

    def __init__(self, source: NMSSource):
        self.source   = source
        self.base_url = (source.base_url or "").rstrip("/")
        self.username = source.username or ""
        self.password = source.password or ""

    async def poll(self, db: AsyncSession) -> int:
        if not self.base_url:
            return 0
        created = 0
        try:
            query = (
                "SELECT AlertID, AlertDefID, ActiveObject, ObjectType, "
                "Message, Severity, TriggeredDateTime "
                "FROM Orion.AlertActive "
                "WHERE Acknowledged=0 "
                "ORDER BY TriggeredDateTime DESC"
            )
            async with httpx.AsyncClient(
                timeout=15,
                verify=False,
                auth=(self.username, self.password),
            ) as client:
                resp = await client.post(
                    f"{self.base_url}/SolarWinds/InformationService/v3/Json/Query",
                    json={"query": query},
                )
                if resp.status_code != 200:
                    logger.error("SolarWinds %d", resp.status_code)
                    return 0
                alerts = resp.json().get("results", [])

            for alert in alerts:
                alert_id  = str(alert.get("AlertID", ""))
                source_id = f"sw-{alert_id}"
                obj        = alert.get("ActiveObject", "")
                msg        = alert.get("Message", "SolarWinds Alert")

                inc = await _create_incident(
                    db,
                    title       = msg[:500],
                    description = f"Object: {obj} | Type: {alert.get('ObjectType','')}",
                    host        = obj,
                    service     = alert.get("ObjectType", ""),
                    source      = "solarwinds",
                    source_id   = source_id,
                    raw_alert   = alert,
                )
                if inc:
                    created += 1

            self.source.last_polled_at = datetime.utcnow()
            self.source.status = "active"
            self.source.last_error = None

        except Exception as e:
            logger.error("SolarWinds poll failed: %s", e)
            self.source.status = "error"
            self.source.last_error = str(e)

        return created

    async def acknowledge(self, alert_id: str) -> bool:
        try:
            async with httpx.AsyncClient(
                timeout=10, verify=False,
                auth=(self.username, self.password),
            ) as client:
                resp = await client.post(
                    f"{self.base_url}/SolarWinds/InformationService/v3/Json/Invoke"
                    "/Orion.AlertSuppression/SuppressAlerts",
                    json={"alertObjectIds": [alert_id], "suppressUntil": ""},
                )
                return resp.status_code == 200
        except Exception:
            return False


# ── PRTG ───────────────────────────────────────────────────────────────────────

class PRTGConnector:
    """Polls PRTG for sensors in Down/Warning state."""

    def __init__(self, source: NMSSource):
        self.source   = source
        self.base_url = (source.base_url or "").rstrip("/")
        self.token    = source.api_token or ""
        self.username = source.username or ""
        self.password = source.password or ""

    async def poll(self, db: AsyncSession) -> int:
        if not self.base_url:
            return 0
        created = 0
        try:
            params = {
                "content":       "sensors",
                "columns":       "objid,name,status,message,device,lastvalue,priority",
                "filter_status": "5",  # 5=Down, could add 4=Warning
                "output":        "json",
            }
            if self.token:
                params["apitoken"] = self.token
            else:
                params["username"] = self.username
                params["password"] = self.password

            async with httpx.AsyncClient(timeout=15, verify=False) as client:
                resp = await client.get(
                    f"{self.base_url}/api/table.json",
                    params=params,
                )
                sensors = resp.json().get("sensors", [])

            for sensor in sensors:
                obj_id    = str(sensor.get("objid", ""))
                source_id = f"prtg-{obj_id}"
                name      = sensor.get("name", "PRTG Sensor")
                device    = sensor.get("device", "")
                status    = sensor.get("status_raw", "")

                inc = await _create_incident(
                    db,
                    title       = f"{name} — {status}",
                    description = sensor.get("message", ""),
                    host        = device,
                    service     = name,
                    source      = "prtg",
                    source_id   = source_id,
                    raw_alert   = sensor,
                )
                if inc:
                    created += 1

            self.source.last_polled_at = datetime.utcnow()
            self.source.status = "active"
            self.source.last_error = None

        except Exception as e:
            logger.error("PRTG poll failed: %s", e)
            self.source.status = "error"
            self.source.last_error = str(e)

        return created

    async def pause_sensor(self, sensor_id: str, message: str) -> bool:
        try:
            params = {"id": sensor_id, "pausemsg": message, "action": "0", "output": "json"}
            if self.token:
                params["apitoken"] = self.token
            async with httpx.AsyncClient(timeout=10, verify=False) as client:
                resp = await client.get(f"{self.base_url}/api/pause.htm", params=params)
                return resp.status_code == 200
        except Exception:
            return False


# ── Nagios / Icinga2 ──────────────────────────────────────────────────────────

class NagiosConnector:
    """Polls Nagios XI REST API for host/service problems."""

    def __init__(self, source: NMSSource):
        self.source   = source
        self.base_url = (source.base_url or settings.nagios_url or "").rstrip("/")
        self.username = source.username or settings.nagios_user or ""
        self.password = source.password or settings.nagios_password or ""

    async def poll(self, db: AsyncSession) -> int:
        if not self.base_url:
            return 0
        created = 0
        try:
            params = {
                "apikey":                self.source.api_token or "",
                "problem_acknowledged":  0,
                "current_state":         "!0",  # not OK
                "output":                "json",
            }
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self.base_url}/nagiosxi/api/v1/objects/servicestatus",
                    params=params,
                    auth=(self.username, self.password) if self.username else None,
                )
                if resp.status_code != 200:
                    logger.error("Nagios %d: %s", resp.status_code, self.base_url)
                    return 0
                data = resp.json()

            services = data.get("servicestatus", [])
            for svc in services:
                host_name    = svc.get("host_name", "")
                service_name = svc.get("name", "")
                output       = svc.get("status_text", svc.get("plugin_output", ""))
                state        = str(svc.get("current_state", "0"))
                if state == "0":
                    continue
                source_id = f"nagios-{host_name}-{service_name}"
                inc = await _create_incident(
                    db,
                    title       = f"{service_name} {['OK','WARNING','CRITICAL','UNKNOWN'][int(state)] if state in '123' else 'PROBLEM'} on {host_name}",
                    description = output,
                    host        = host_name,
                    service     = service_name,
                    source      = "nagios",
                    source_id   = source_id,
                    raw_alert   = svc,
                )
                if inc:
                    created += 1

            self.source.last_polled_at = datetime.utcnow()
            self.source.status = "active"
            self.source.last_error = None
        except Exception as e:
            logger.error("Nagios poll failed %s: %s", self.base_url, e)
            self.source.status = "error"
            self.source.last_error = str(e)
        return created


class IcingaConnector:
    """Polls Icinga2 REST API for service problems."""

    def __init__(self, source: NMSSource):
        self.source   = source
        self.base_url = (source.base_url or settings.icinga2_url or "").rstrip("/")
        self.username = source.username or settings.icinga2_user or ""
        self.password = source.password or settings.icinga2_password or ""

    async def poll(self, db: AsyncSession) -> int:
        if not self.base_url:
            return 0
        created = 0
        try:
            async with httpx.AsyncClient(timeout=15, verify=False) as client:
                resp = await client.get(
                    f"{self.base_url}/v1/objects/services",
                    auth=(self.username, self.password),
                    headers={
                        "Accept":               "application/json",
                        "X-HTTP-Method-Override": "GET",
                    },
                    json={"filter": "service.state != ServiceOK && service.acknowledgement == 0"},
                )
                if resp.status_code != 200:
                    logger.error("Icinga2 %d: %s", resp.status_code, self.base_url)
                    return 0
                objects = resp.json().get("results", [])

            for obj in objects:
                attrs      = obj.get("attrs", {})
                name       = obj.get("name", "")
                host_name  = attrs.get("host_name", "")
                output     = attrs.get("last_check_result", {}).get("output", "")
                source_id  = f"icinga-{host_name}-{name}"

                inc = await _create_incident(
                    db,
                    title       = f"{name} problem on {host_name}",
                    description = output,
                    host        = host_name,
                    service     = name,
                    source      = "icinga2",
                    source_id   = source_id,
                    raw_alert   = attrs,
                )
                if inc:
                    created += 1

            self.source.last_polled_at = datetime.utcnow()
            self.source.status = "active"
            self.source.last_error = None
        except Exception as e:
            logger.error("Icinga2 poll failed %s: %s", self.base_url, e)
            self.source.status = "error"
            self.source.last_error = str(e)
        return created


# ── Datadog ────────────────────────────────────────────────────────────────────

class DatadogConnector:
    """Polls Datadog Events API for error/warning events."""

    def __init__(self, source: NMSSource):
        self.source  = source
        self.api_key = source.api_token or settings.datadog_api_key or ""
        self.app_key = settings.datadog_app_key or ""
        self.site    = settings.datadog_site or "datadoghq.com"

    async def poll(self, db: AsyncSession) -> int:
        if not self.api_key:
            return 0
        import time as _time
        created = 0
        try:
            params = {
                "start":    int(_time.time()) - 300,  # last 5 minutes
                "priority": "normal",
                "tags":     "alert_type:error,alert_type:warning",
            }
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"https://api.{self.site}/api/v1/events",
                    params=params,
                    headers={
                        "DD-API-KEY":         self.api_key,
                        "DD-APPLICATION-KEY": self.app_key,
                    },
                )
                if resp.status_code != 200:
                    logger.error("Datadog %d", resp.status_code)
                    return 0
                events = resp.json().get("events", [])

            for event in events:
                alert_type = event.get("alert_type", "")
                if alert_type not in ("error", "warning"):
                    continue
                event_id  = str(event.get("id", ""))
                source_id = f"dd-{event_id}"
                host_name = event.get("host", "")
                title     = event.get("title", "Datadog Alert")

                inc = await _create_incident(
                    db,
                    title       = title[:500],
                    description = event.get("text", "")[:1000],
                    host        = host_name,
                    service     = ",".join(event.get("tags", []))[:255],
                    source      = "datadog",
                    source_id   = source_id,
                    raw_alert   = event,
                )
                if inc:
                    created += 1

            self.source.last_polled_at = datetime.utcnow()
            self.source.status = "active"
            self.source.last_error = None
        except Exception as e:
            logger.error("Datadog poll failed: %s", e)
            self.source.status = "error"
            self.source.last_error = str(e)
        return created


# ── New Relic ─────────────────────────────────────────────────────────────────

class NewRelicConnector:
    """Polls New Relic Alerts API for open violations."""

    def __init__(self, source: NMSSource):
        self.source     = source
        self.api_key    = source.api_token or settings.newrelic_api_key or ""
        self.account_id = settings.newrelic_account_id or ""

    async def poll(self, db: AsyncSession) -> int:
        if not self.api_key:
            return 0
        created = 0
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    "https://api.newrelic.com/v2/alerts_violations.json",
                    params={"only_open": "true"},
                    headers={"X-Api-Key": self.api_key},
                )
                if resp.status_code != 200:
                    logger.error("New Relic %d", resp.status_code)
                    return 0
                violations = resp.json().get("violations", [])

            for v in violations:
                v_id      = str(v.get("id", ""))
                source_id = f"nr-{v_id}"
                entity    = v.get("entity", {})
                host_name = entity.get("name", "")
                title     = f"{v.get('condition_name', 'Alert')} on {host_name}"

                inc = await _create_incident(
                    db,
                    title       = title[:500],
                    description = f"Policy: {v.get('policy_name', '')} | Condition: {v.get('condition_name', '')}",
                    host        = host_name,
                    service     = entity.get("type", ""),
                    source      = "newrelic",
                    source_id   = source_id,
                    raw_alert   = v,
                )
                if inc:
                    created += 1

            self.source.last_polled_at = datetime.utcnow()
            self.source.status = "active"
            self.source.last_error = None
        except Exception as e:
            logger.error("New Relic poll failed: %s", e)
            self.source.status = "error"
            self.source.last_error = str(e)
        return created


# ── Dynatrace ─────────────────────────────────────────────────────────────────

class DynatraceConnector:
    """Polls Dynatrace Problems API v2 for open problems."""

    def __init__(self, source: NMSSource):
        self.source    = source
        self.base_url  = (source.base_url or settings.dynatrace_url or "").rstrip("/")
        self.api_token = source.api_token or settings.dynatrace_api_token or ""

    async def poll(self, db: AsyncSession) -> int:
        if not (self.base_url and self.api_token):
            return 0
        created = 0
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self.base_url}/api/v2/problems",
                    params={"problemSelector": 'status("OPEN")'},
                    headers={"Authorization": f"Api-Token {self.api_token}"},
                )
                if resp.status_code != 200:
                    logger.error("Dynatrace %d: %s", resp.status_code, self.base_url)
                    return 0
                problems = resp.json().get("problems", [])

            for p in problems:
                p_id      = p.get("problemId", "")
                source_id = f"dt-{p_id}"
                entities  = p.get("impactedEntities", [{}])
                host_name = entities[0].get("name", "") if entities else ""
                title     = p.get("title", "Dynatrace Problem")
                severity  = p.get("severityLevel", "")

                inc = await _create_incident(
                    db,
                    title       = f"{title} [{severity}]"[:500],
                    description = p.get("displayId", "") + " " + str(p.get("affectedEntities", "")),
                    host        = host_name,
                    service     = p.get("entityLabel", ""),
                    source      = "dynatrace",
                    source_id   = source_id,
                    raw_alert   = p,
                )
                if inc:
                    created += 1

            self.source.last_polled_at = datetime.utcnow()
            self.source.status = "active"
            self.source.last_error = None
        except Exception as e:
            logger.error("Dynatrace poll failed %s: %s", self.base_url, e)
            self.source.status = "error"
            self.source.last_error = str(e)
        return created


# ── Poll all sources ───────────────────────────────────────────────────────────

CONNECTOR_MAP = {
    "prometheus": PrometheusConnector,
    "zabbix":     ZabbixConnector,
    "solarwinds": SolarWindsConnector,
    "prtg":       PRTGConnector,
    "nagios":     NagiosConnector,
    "icinga2":    IcingaConnector,
    "datadog":    DatadogConnector,
    "newrelic":   NewRelicConnector,
    "dynatrace":  DynatraceConnector,
}


async def poll_all() -> int:
    """
    Poll all enabled NMS sources.
    Called by the background scheduler every NMS_POLL_SECONDS.
    Creates incidents and triggers the agent automatically.
    """
    from backend.database import AsyncSessionLocal
    from backend.agent.executor import AgentExecutor

    executor = AgentExecutor()
    total_created = 0

    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(NMSSource).where(NMSSource.enabled == True)
        )
        sources = r.scalars().all()

        if not sources:
            return 0

        for source in sources:
            cls = CONNECTOR_MAP.get(source.nms_type)
            if not cls:
                continue

            connector = cls(source)
            try:
                n = await connector.poll(db)
                total_created += n
                if n:
                    logger.info("NMS %s: %d new incidents", source.name, n)
            except Exception as e:
                logger.error("NMS %s poll error: %s", source.name, e)
                source.status = "error"
                source.last_error = str(e)

        await db.commit()

        # Trigger agent on all NEW incidents
        if total_created > 0:
            new_r = await db.execute(
                select(Incident)
                .where(Incident.status == IncidentStatus.NEW)
                .limit(20)
            )
            new_incidents = new_r.scalars().all()
            for inc in new_incidents:
                try:
                    await executor.run(inc.id, db)
                    await db.commit()
                except Exception as e:
                    logger.error("Agent failed on %s: %s", inc.number, e)
                    await db.rollback()

    logger.info("NMS poll complete: %d new incidents created", total_created)
    return total_created
