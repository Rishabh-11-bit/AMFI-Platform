"""
Module 5 — Diagnostics Service (L1 & L2)

L1 (Auto — runs always):
  - Connectivity test (ping)
  - Service status check (systemctl via SSH)
  - Log tail (last 50 lines of syslog/app log)
  - Disk & memory snapshot
  - Interface status check

L2 (Deep — runs for CRITICAL/HIGH after L1):
  - Full log analysis (grep for errors)
  - Process/thread dump
  - Network port scan
  - DNS resolution check

All checks run over SSH using paramiko.
Results stored as JSON in DiagnosticRun.findings.
"""
import asyncio
import logging
import json
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.all_models import (
    Incident, DiagnosticRun, DiagnosticLevel, DiagnosticStatus,
    ConfigItem, IncidentPriority
)
from backend.config import get_settings

logger = logging.getLogger("amfi.diagnostics")
settings = get_settings()


class DiagnosticsService:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def run(self, incident: Incident) -> DiagnosticRun:
        """Run appropriate diagnostic level based on incident priority."""
        level = (
            DiagnosticLevel.L2
            if incident.priority in (IncidentPriority.CRITICAL, IncidentPriority.HIGH)
            else DiagnosticLevel.L1
        )

        target_host = await self._get_target_host(incident)
        ci          = await self._get_ci(target_host)

        run = DiagnosticRun(
            incident_id  = incident.id,
            level        = level,
            target_host  = target_host,
            target_type  = ci.ci_type if ci else "unknown",
            status       = DiagnosticStatus.RUNNING,
            started_at   = datetime.utcnow(),
        )
        self.db.add(run)
        await self.db.flush()

        try:
            findings = await self._execute_checks(run, ci, level)
            run.findings    = findings
            run.checks_run  = list(findings.keys())
            run.summary     = self._summarize(findings)
            run.recommended_action = self._recommend(findings, incident)
            run.status      = DiagnosticStatus.COMPLETED
        except Exception as e:
            logger.error("Diagnostics failed for incident %s: %s", incident.id, e)
            run.status      = DiagnosticStatus.FAILED
            run.findings    = {"error": str(e)}
            run.summary     = f"Diagnostic run failed: {e}"

        run.completed_at     = datetime.utcnow()
        run.duration_seconds = (run.completed_at - run.started_at).total_seconds()
        await self.db.flush()

        logger.info("Diagnostics done: incident=%s level=%s status=%s",
                    incident.id, level, run.status)
        return run

    async def _execute_checks(self, run: DiagnosticRun, ci: ConfigItem | None,
                               level: DiagnosticLevel) -> dict:
        """Run all checks and collect findings."""
        host    = run.target_host
        findings = {}

        # ── L1 checks ─────────────────────────────────────────────────────────
        findings["ping"]            = await self._check_ping(host)
        findings["ssh_reachable"]   = await self._check_ssh(host, ci)
        findings["disk_usage"]      = await self._check_disk(host, ci)
        findings["memory_usage"]    = await self._check_memory(host, ci)
        findings["cpu_load"]        = await self._check_cpu(host, ci)
        findings["service_status"]  = await self._check_services(host, ci, run)
        findings["recent_errors"]   = await self._check_logs(host, ci)

        if level == DiagnosticLevel.L2:
            findings["open_ports"]      = await self._check_ports(host)
            findings["process_list"]    = await self._check_processes(host, ci)
            findings["dns_resolution"]  = await self._check_dns(host)
            findings["network_stats"]   = await self._check_network_stats(host, ci)

        return findings

    # ── Individual checks — each returns a dict with status + data ────────────

    async def _check_ping(self, host: str) -> dict:
        if not host:
            return {"status": "skipped", "reason": "no host"}
        try:
            base_host = host.split(":")[0]
            proc = await asyncio.create_subprocess_exec(
                "ping", "-c", "3", "-W", "2", base_host,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            output = stdout.decode()
            if "0 received" in output or "100% packet loss" in output:
                return {"status": "FAIL", "detail": "Host unreachable — 100% packet loss"}
            # Extract avg RTT
            for line in output.split("\n"):
                if "avg" in line or "rtt" in line:
                    return {"status": "OK", "detail": line.strip()}
            return {"status": "OK", "detail": "Host reachable"}
        except asyncio.TimeoutError:
            return {"status": "FAIL", "detail": "Ping timed out"}
        except Exception as e:
            return {"status": "ERROR", "detail": str(e)}

    async def _check_ssh(self, host: str, ci: ConfigItem | None) -> dict:
        if not host or not ci or not ci.ssh_user:
            return {"status": "skipped", "reason": "no SSH credentials in CMDB"}
        try:
            result = await self._ssh_exec(ci, "echo AMFI_OK")
            if "AMFI_OK" in result:
                return {"status": "OK", "detail": "SSH connection successful"}
            return {"status": "WARN", "detail": "SSH connected but unexpected output"}
        except Exception as e:
            return {"status": "FAIL", "detail": f"SSH failed: {e}"}

    async def _check_disk(self, host: str, ci: ConfigItem | None) -> dict:
        if not ci or not ci.ssh_user:
            return {"status": "skipped", "reason": "no SSH credentials"}
        try:
            output = await self._ssh_exec(ci, "df -h / /var /tmp 2>/dev/null | tail -n +2")
            issues = []
            for line in output.strip().split("\n"):
                parts = line.split()
                if len(parts) >= 5:
                    use_pct = parts[4].rstrip("%")
                    if use_pct.isdigit() and int(use_pct) > 85:
                        issues.append(f"{parts[5]} is {parts[4]} full")
            if issues:
                return {"status": "WARN", "detail": ", ".join(issues), "raw": output}
            return {"status": "OK", "detail": "Disk usage normal", "raw": output}
        except Exception as e:
            return {"status": "ERROR", "detail": str(e)}

    async def _check_memory(self, host: str, ci: ConfigItem | None) -> dict:
        if not ci or not ci.ssh_user:
            return {"status": "skipped", "reason": "no SSH credentials"}
        try:
            output = await self._ssh_exec(ci, "free -m | grep Mem")
            parts = output.split()
            if len(parts) >= 3:
                total, used = int(parts[1]), int(parts[2])
                pct = (used / total * 100) if total > 0 else 0
                status = "WARN" if pct > 85 else "OK"
                return {"status": status, "detail": f"Memory: {used}MB / {total}MB ({pct:.0f}%)"}
            return {"status": "OK", "detail": output}
        except Exception as e:
            return {"status": "ERROR", "detail": str(e)}

    async def _check_cpu(self, host: str, ci: ConfigItem | None) -> dict:
        if not ci or not ci.ssh_user:
            return {"status": "skipped", "reason": "no SSH credentials"}
        try:
            output = await self._ssh_exec(ci,
                "top -bn1 | grep 'Cpu(s)' | awk '{print $2}' | cut -d% -f1")
            cpu = float(output.strip()) if output.strip() else 0
            status = "WARN" if cpu > 85 else "OK"
            return {"status": status, "detail": f"CPU usage: {cpu:.1f}%"}
        except Exception as e:
            return {"status": "ERROR", "detail": str(e)}

    async def _check_services(self, host: str, ci: ConfigItem | None, run: DiagnosticRun) -> dict:
        if not ci or not ci.ssh_user:
            return {"status": "skipped", "reason": "no SSH credentials"}
        try:
            output = await self._ssh_exec(ci,
                "systemctl list-units --state=failed --no-legend --no-pager 2>/dev/null | head -20")
            if output.strip():
                return {"status": "WARN", "detail": f"Failed services: {output.strip()}"}
            return {"status": "OK", "detail": "No failed systemd services"}
        except Exception as e:
            return {"status": "ERROR", "detail": str(e)}

    async def _check_logs(self, host: str, ci: ConfigItem | None) -> dict:
        if not ci or not ci.ssh_user:
            return {"status": "skipped", "reason": "no SSH credentials"}
        try:
            output = await self._ssh_exec(ci,
                "journalctl -n 50 -p err --no-pager 2>/dev/null || tail -50 /var/log/syslog 2>/dev/null")
            error_count = output.lower().count("error") + output.lower().count("critical")
            if error_count > 10:
                return {"status": "WARN", "detail": f"{error_count} errors in recent logs", "sample": output[-500:]}
            return {"status": "OK", "detail": f"{error_count} errors in recent logs"}
        except Exception as e:
            return {"status": "ERROR", "detail": str(e)}

    async def _check_ports(self, host: str) -> dict:
        try:
            base_host = host.split(":")[0]
            proc = await asyncio.create_subprocess_exec(
                "nmap", "-F", "--open", base_host,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            return {"status": "OK", "detail": stdout.decode()[-500:]}
        except Exception as e:
            return {"status": "skipped", "detail": f"nmap not available: {e}"}

    async def _check_processes(self, host: str, ci: ConfigItem | None) -> dict:
        if not ci or not ci.ssh_user:
            return {"status": "skipped", "reason": "no SSH credentials"}
        try:
            output = await self._ssh_exec(ci,
                "ps aux --sort=-%cpu | head -10 2>/dev/null")
            return {"status": "OK", "detail": output}
        except Exception as e:
            return {"status": "ERROR", "detail": str(e)}

    async def _check_dns(self, host: str) -> dict:
        try:
            base_host = host.split(":")[0]
            proc = await asyncio.create_subprocess_exec(
                "nslookup", base_host,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            output = stdout.decode()
            if "NXDOMAIN" in output or "can't find" in output:
                return {"status": "FAIL", "detail": f"DNS resolution failed for {base_host}"}
            return {"status": "OK", "detail": f"DNS OK for {base_host}"}
        except Exception as e:
            return {"status": "ERROR", "detail": str(e)}

    async def _check_network_stats(self, host: str, ci: ConfigItem | None) -> dict:
        if not ci or not ci.ssh_user:
            return {"status": "skipped", "reason": "no SSH credentials"}
        try:
            output = await self._ssh_exec(ci, "ss -s 2>/dev/null || netstat -s 2>/dev/null | head -20")
            return {"status": "OK", "detail": output[:500]}
        except Exception as e:
            return {"status": "ERROR", "detail": str(e)}

    # ── SSH helper ────────────────────────────────────────────────────────────

    async def _ssh_exec(self, ci: ConfigItem, command: str) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._ssh_exec_sync, ci, command)

    def _ssh_exec_sync(self, ci: ConfigItem, command: str) -> str:
        try:
            import paramiko
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            connect_kwargs = dict(
                hostname=ci.ip_address or ci.hostname,
                username=ci.ssh_user,
                timeout=settings.ssh_timeout_seconds,
                banner_timeout=settings.ssh_timeout_seconds,
            )
            if ci.ssh_key_path:
                connect_kwargs["key_filename"] = ci.ssh_key_path
            client.connect(**connect_kwargs)
            _, stdout, stderr = client.exec_command(command, timeout=settings.ssh_timeout_seconds)
            output = stdout.read().decode("utf-8", errors="replace")
            client.close()
            return output
        except ImportError:
            return "[paramiko not installed]"

    # ── Summary and recommendations ───────────────────────────────────────────

    def _summarize(self, findings: dict) -> str:
        issues = [
            f"{check}: {data.get('detail','')}"
            for check, data in findings.items()
            if isinstance(data, dict) and data.get("status") in ("FAIL", "WARN")
        ]
        if not issues:
            return "All diagnostic checks passed. System appears healthy."
        return "Issues found: " + " | ".join(issues)

    def _recommend(self, findings: dict, incident: Incident) -> str:
        recs = []
        if findings.get("ping", {}).get("status") == "FAIL":
            recs.append("Host unreachable — check network connectivity and firewall rules")
        if findings.get("disk_usage", {}).get("status") == "WARN":
            recs.append("Clean up disk space: remove old logs, tmp files, rotate logs")
        if findings.get("memory_usage", {}).get("status") == "WARN":
            recs.append("High memory — consider restarting memory-intensive services or adding swap")
        if findings.get("cpu_load", {}).get("status") == "WARN":
            recs.append("High CPU — identify top process and consider restarting or scaling")
        if findings.get("service_status", {}).get("status") == "WARN":
            recs.append("Restart failed systemd services: systemctl restart <service>")
        return " | ".join(recs) if recs else "No specific recommendation — manual investigation required"

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _get_target_host(self, incident: Incident) -> str | None:
        if incident.correlated_event and incident.correlated_event.enriched_event:
            return incident.correlated_event.enriched_event.raw_event.affected_host
        return None

    async def _get_ci(self, host: str | None) -> ConfigItem | None:
        if not host:
            return None
        from sqlalchemy import select
        base = host.split(":")[0]
        result = await self.db.execute(
            select(ConfigItem).where(
                (ConfigItem.hostname == base) | (ConfigItem.ip_address == base)
            ).limit(1)
        )
        return result.scalar_one_or_none()
