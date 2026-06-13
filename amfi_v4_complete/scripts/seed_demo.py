"""
AMFI v4 — Demo Data Seeder
Populates the database with realistic production-like data:
  • 6 hosts (CMDB)
  • 2 NMS sources
  • 12 incidents in various states with full step timelines
  • Resolutions (agent memory)

Run: python scripts/seed_demo.py
"""
import asyncio
import sys
import os
from datetime import datetime, timedelta
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, func
from backend.database import init_db, AsyncSessionLocal
from backend.models.models import (
    Incident, IncidentStep, IncidentStatus,
    Host, NMSSource, Resolution, Approval, AuditLog,
)

# ─────────────────────────────────────────────────────────────────────────────

HOSTS = [
    dict(hostname="web-01",        ip_address="10.0.1.10", os="Ubuntu 22.04",  environment="prod",    criticality="high",     business_service="Customer Portal",    ssh_user="ubuntu",  ssh_port=22, auto_remediate=True,  approval_required=False),
    dict(hostname="web-02",        ip_address="10.0.1.11", os="Ubuntu 22.04",  environment="prod",    criticality="high",     business_service="Customer Portal",    ssh_user="ubuntu",  ssh_port=22, auto_remediate=True,  approval_required=False),
    dict(hostname="db-server-01",  ip_address="10.0.2.10", os="Ubuntu 20.04",  environment="prod",    criticality="critical", business_service="Core Database",      ssh_user="ubuntu",  ssh_port=22, auto_remediate=True,  approval_required=True,  known_issues="Disk fills every 3 weeks on /var/log - safe to auto-clean"),
    dict(hostname="app-server-01", ip_address="10.0.3.10", os="CentOS 7",      environment="prod",    criticality="high",     business_service="Payment Gateway",    ssh_user="root",    ssh_port=22, auto_remediate=True,  approval_required=False),
    dict(hostname="redis-01",      ip_address="10.0.4.10", os="Ubuntu 22.04",  environment="prod",    criticality="medium",   business_service="Session Cache",      ssh_user="ubuntu",  ssh_port=22, auto_remediate=True,  approval_required=False),
    dict(hostname="k8s-node-01",   ip_address="10.0.5.10", os="Ubuntu 22.04",  environment="prod",    criticality="critical", business_service="Kubernetes Cluster", ssh_user="ubuntu",  ssh_port=22, auto_remediate=False, approval_required=True,  never_touch=False, known_issues="Do not restart kubelet without team approval"),
]

NMS_SOURCES = [
    dict(name="Production Prometheus", nms_type="prometheus", base_url="http://prometheus.internal:9093", enabled=True,  poll_interval=300, status="active",  last_polled_at=datetime.utcnow() - timedelta(minutes=4)),
    dict(name="Zabbix Monitoring",     nms_type="zabbix",     base_url="http://zabbix.internal",          enabled=False, poll_interval=300, status="unknown", last_error="Not configured yet"),
]

# Incidents: (title, host, service, fault_category, priority, status, created_mins_ago, resolved_mins_ago_or_None)
INCIDENTS_DEF = [
    # Resolved incidents (agent fixed them)
    ("High disk usage on db-server-01 — /var/log at 94%",           "db-server-01",  "postgresql",  "disk_full",      "p2", "resolved",      180, 150),
    ("CPU spike on web-01 — load average 18.4",                      "web-01",        "nginx",       "high_cpu",       "p2", "resolved",      240, 200),
    ("nginx service down on web-02",                                  "web-02",        "nginx",       "service_down",   "p1", "resolved",       90,  60),
    ("Memory pressure on app-server-01 — 91% used",                  "app-server-01", "java-app",    "high_memory",    "p2", "resolved",      300, 260),
    ("Redis service not responding on redis-01",                      "redis-01",      "redis",       "service_down",   "p1", "resolved",       60,  40),
    # Escalated
    ("Database connection failures — postgresql on db-server-01",    "db-server-01",  "postgresql",  "database_issue", "p1", "l3_escalated",   45, None),
    ("Network unreachable — k8s-node-01 offline",                    "k8s-node-01",   "kubelet",     "network_down",   "p1", "l3_escalated",   30, None),
    # Active / running
    ("High CPU on app-server-01 — 88% for 15 min",                  "app-server-01", "java-app",    "high_cpu",       "p2", "l1_running",     10, None),
    # New — not yet picked up
    ("Disk usage warning on web-01 — /var/www at 85%",              "web-01",        "nginx",       "disk_full",      "p3", "new",             2, None),
    ("High latency on Customer Portal — p99 > 3s",                  "web-01",        "nginx",       "high_latency",   "p2", "new",             1, None),
    # False positive
    ("CPU alert — web-02 (during deployment, expected)",             "web-02",        "nginx",       "high_cpu",       "p3", "false_positive", 500, None),
    # Closed
    ("Disk full on redis-01 — cleaned manually",                     "redis-01",      "redis",       "disk_full",      "p2", "closed",         700, None),
]

# Realistic step sequences per fault category
STEP_TEMPLATES = {
    "disk_full": [
        ("ping",         "Ping host",           True,  None,  "Host {host}: reachable (12ms via tcp_22)"),
        ("diagnostic",   "Check disk usage",    True,  "df -h --output=target,pcent,avail,size | head -20", "Filesystem      Use% Avail  Size\n/              45%  52G    94G\n/var/log        94%  1.2G   22G\n/tmp             8%  9.1G   10G"),
        ("ai_interpret", "AI: interpret disk",  True,  None,  None),  # filled dynamically
        ("action",       "Clear old log files", True,  "find /var/log -type f -name '*.log' -mtime +7 -delete 2>&1; journalctl --vacuum-time=7d 2>&1", "Deleted 847 files, freed 18.4 GB\nVacuumed 2 journal files, freed 3.1 GB"),
        ("action",       "Clear /tmp files",    True,  "find /tmp -type f -mtime +3 -delete 2>&1", "Deleted 156 files"),
        ("verify",       "Verify disk dropped", True,  "df -h /var/log | tail -1", "/var/log        41%  12.8G  22G"),
    ],
    "high_cpu": [
        ("ping",         "Ping host",           True,  None,  "Host {host}: reachable (8ms via tcp_22)"),
        ("diagnostic",   "Check CPU usage",     True,  "top -bn1 | head -5", "%Cpu(s): 88.2 us,  4.1 sy,  0.0 ni,  6.1 id\nload average: 18.41, 16.22, 12.08"),
        ("diagnostic",   "Check top processes", True,  "ps aux --sort=-%cpu | head -15", "USER     PID  %CPU %MEM COMMAND\nwww-data 3821  87.2  2.1 /usr/sbin/apache2\nroot     1024   0.8  0.1 /usr/lib/systemd/systemd"),
        ("ai_interpret", "AI: interpret CPU",   True,  None,  None),
        ("action",       "Kill top CPU process",True,  "kill -15 3821; sleep 2; kill -9 3821 2>/dev/null", "Killed PID 3821 (apache2)\nDone"),
        ("verify",       "Verify CPU normal",   True,  "top -bn1 | grep Cpu", "%Cpu(s):  4.2 us,  1.1 sy,  0.0 ni, 93.5 id"),
    ],
    "service_down": [
        ("ping",         "Ping host",            True,  None, "Host {host}: reachable (5ms via tcp_22)"),
        ("diagnostic",   "Check service status", False, "systemctl status {service} 2>&1 | head -30", "● nginx.service - A high performance web server\n   Loaded: loaded (/lib/systemd/system/nginx.service)\n   Active: failed (Result: exit-code)\nProcess: 4521 ExecStart=/usr/sbin/nginx (code=exited, status=1/FAILURE)\nnginx: [emerg] bind() to 0.0.0.0:80 failed (98: Address already in use)"),
        ("diagnostic",   "Check service logs",   True,  "journalctl -u {service} -n 30 --no-pager", "Jun 07 08:21:14 nginx[4521]: nginx: [emerg] bind() to 0.0.0.0:80 failed\nJun 07 08:20:55 systemd[1]: nginx.service: Main process exited\nJun 07 08:20:55 systemd[1]: nginx.service: Failed with result 'exit-code'"),
        ("ai_interpret", "AI: interpret service",True,  None, None),
        ("diagnostic",   "Check disk space",     True,  "df -h / | tail -1", "/                31%  44G   65G"),
        ("action",       "Restart service",      True,  "systemctl restart {service} && sleep 3 && systemctl is-active {service}", "active"),
        ("verify",       "Verify service running",True, "systemctl is-active {service}", "active"),
    ],
    "high_memory": [
        ("ping",         "Ping host",             True, None, "Host {host}: reachable (11ms via tcp_22)"),
        ("diagnostic",   "Check memory",          True, "free -h", "              total        used        free      shared  buff/cache   available\nMem:            31G         28G        512M        1.2G        2.1G        1.8G\nSwap:           8.0G        3.2G        4.8G"),
        ("diagnostic",   "Check top processes",   True, "ps aux --sort=-%mem | head -10", "USER     PID  %CPU %MEM COMMAND\ntomcat   8821   2.1 42.8 /usr/bin/java -Xmx12g -jar app.jar\ntomcat   8834   0.8 22.4 /usr/bin/java -Xmx6g -jar worker.jar"),
        ("ai_interpret", "AI: interpret memory",  True, None, None),
        ("action",       "Clear memory cache",    True, "sync; echo 3 > /proc/sys/vm/drop_caches && free -h | grep Mem", "Cache cleared\nMem:  31G  18G  8.4G  1.1G  4.1G  11G"),
        ("verify",       "Verify memory normal",  True, "free -h | grep Mem", "Mem:  31G  19G  7.8G  1.1G  4.1G  10G"),
    ],
    "database_issue": [
        ("ping",         "Ping host",             True,  None, "Host {host}: reachable (9ms via tcp_22)"),
        ("diagnostic",   "Check DB service",      False, "systemctl status postgresql 2>&1 | head -20", "● postgresql.service\n   Active: active (running) since...\nConnections: 498/500 (99.6%)"),
        ("diagnostic",   "Check service logs",    True,  "journalctl -u postgresql -n 30 --no-pager 2>&1", "FATAL: sorry, too many clients already\nFATAL: remaining connection slots are reserved\nERROR: out of shared memory"),
        ("diagnostic",   "Check disk space",      True,  "df -h /var/lib/postgresql | tail -1", "/var/lib/postgresql   67%  52G   78G"),
        ("ai_interpret", "AI: interpret DB",      True,  None, None),
        ("action",       "Clear disk if needed",  True,  "find /var/log/postgresql -name '*.log' -mtime +7 -delete 2>&1", "Deleted 23 old log files"),
        ("verify",       "Verify DB running",     True,  "systemctl is-active postgresql", "active"),
    ],
    "network_down": [
        ("ping",         "Ping host",                  False, None, "Host {host}: UNREACHABLE (timeout via none)"),
        ("ai_interpret", "AI: interpret network",      True,  None, "The host {host} is completely unreachable. All TCP probe attempts (port 22, 443) timed out after 5 seconds. This indicates either the host is powered off, the network route is broken, or a firewall rule is blocking all traffic. Manual investigation required — the agent cannot SSH into an unreachable host."),
        ("action",       "Escalate: host unreachable", True,  None, "L3 escalation brief generated and sent."),
    ],
    "high_latency": [
        ("ping",         "Ping host",             True, None, "Host {host}: reachable (42ms via tcp_22)"),
        ("diagnostic",   "Check CPU",             True, "top -bn1 | head -3", "%Cpu(s): 44.2 us,  8.1 sy,  0.0 ni, 46.1 id"),
        ("diagnostic",   "Check memory",          True, "free -h | grep Mem", "Mem:  31G  24G  2.1G  800M  4.8G  5.9G"),
        ("diagnostic",   "Check disk",            True, "df -h / | tail -1", "/    72%  18G  65G"),
        ("ai_interpret", "AI: interpret latency", True, None, None),
    ],
}

AI_INTERPRETATIONS = {
    "disk_full":      "The /var/log filesystem is at 94% capacity, critically close to full. The primary cause is accumulated rotated log files and journal data older than 7 days. Immediate action: clear old logs and vacuum the systemd journal. This is a routine maintenance issue — no service impact yet but will cause failures within hours if not addressed.",
    "high_cpu":       "CPU is sustained at 88% with load average of 18, driven by an apache2 worker process (PID 3821) consuming 87% alone. This is abnormal — likely a runaway request handler or stuck connection. Recommended action: kill the offending process. The parent apache2 will respawn a healthy worker automatically.",
    "service_down":   "nginx failed to start due to port 80 already being in use (EADDRINUSE). Another process is bound to port 80 — likely a previous nginx instance that didn't clean up its PID file. Recommended action: restart the service (systemctl restart forces clean socket release). No disk or dependency issues detected.",
    "high_memory":    "Memory at 91% usage with 3.2GB swap in use. Two Java processes are consuming 65% of total RAM combined. The JVM heap settings (-Xmx12g, -Xmx6g) are consuming most available memory. Dropping page cache will immediately free 4GB+ of reclaimable memory. This is safe and will not impact running processes.",
    "database_issue": "PostgreSQL has hit its connection limit (498/500 connections). No new connections can be established. Root cause: connection pool exhaustion, likely due to application connection leaks or insufficient connection pooling. Clearing disk space will help with log rotation. The service is running — restart should reset connection state.",
    "network_down":   "Host is completely unreachable. All probe attempts failed. Manual L3 investigation required.",
    "high_latency":   "CPU at 44%, memory at 77%, disk at 72% — all elevated but not critical individually. The combination creates system pressure. High latency is likely caused by memory pressure pushing to swap combined with I/O contention on disk. No single clear fix — recommend monitoring and potential infrastructure scaling.",
}

RESOLUTIONS_DATA = [
    dict(host="db-server-01",  fault_category="disk_full",      fix_action="clear_old_logs",     success=True, time_to_fix_min=28.4, resolved_at_level="agent_l1"),
    dict(host="web-01",        fault_category="high_cpu",       fix_action="kill_top_process",   success=True, time_to_fix_min=18.2, resolved_at_level="agent_l1"),
    dict(host="web-02",        fault_category="service_down",   fix_action="restart_service",    success=True, time_to_fix_min=12.7, resolved_at_level="agent_l1"),
    dict(host="app-server-01", fault_category="high_memory",    fix_action="clear_memory_cache", success=True, time_to_fix_min=22.1, resolved_at_level="agent_l1"),
    dict(host="redis-01",      fault_category="service_down",   fix_action="restart_service",    success=True, time_to_fix_min=9.8,  resolved_at_level="agent_l1"),
]


async def seed():
    await init_db()

    async with AsyncSessionLocal() as db:
        # ── Clear existing demo incidents / steps / resolutions ───────────
        print("Clearing previous data...")
        # Keep users and SLA policies, clear incident data
        for model in [AuditLog, Resolution, IncidentStep, Approval, Incident, Host, NMSSource]:
            items = (await db.execute(select(model))).scalars().all()
            for item in items:
                await db.delete(item)
        await db.commit()

        # ── Hosts ─────────────────────────────────────────────────────────
        print("Seeding hosts...")
        host_objs = {}
        for h in HOSTS:
            obj = Host(**h)
            db.add(obj)
            host_objs[h["hostname"]] = obj
        await db.commit()
        print(f"  {len(HOSTS)} hosts added")

        # ── NMS Sources ───────────────────────────────────────────────────
        print("Seeding NMS sources...")
        for n in NMS_SOURCES:
            db.add(NMSSource(**n))
        await db.commit()
        print(f"  {len(NMS_SOURCES)} NMS sources added")

        # ── Incidents + Steps ─────────────────────────────────────────────
        print("Seeding incidents with step timelines...")
        incident_objs = []

        for idx, (title, host, service, fault, priority, status, mins_ago, resolved_ago) in enumerate(INCIDENTS_DEF, start=1):
            number     = f"INC-{idx:04d}"
            created_at = datetime.utcnow() - timedelta(minutes=mins_ago)
            resolved_at= datetime.utcnow() - timedelta(minutes=resolved_ago) if resolved_ago else None

            # SLA
            sla_map = {"p1": (15, 60), "p2": (60, 240), "p3": (240, 1440), "p4": (1440, 4320)}
            resp_m, res_m = sla_map[priority]
            sla_response_due = created_at + timedelta(minutes=resp_m)
            sla_resolve_due  = created_at + timedelta(minutes=res_m)
            sla_breached     = (resolved_at or datetime.utcnow()) > sla_resolve_due

            resolution_text = None
            root_cause_text = None
            resolved_by     = None
            attempt_count   = 1 if status not in ("new",) else 0

            if status == "resolved":
                resolution_text = f"Resolved automatically by AMFI agent (fault: {fault})"
                root_cause_text = AI_INTERPRETATIONS.get(fault, "")[:300]
                resolved_by     = "agent_l1"
            elif status == "l3_escalated":
                resolution_text = f"L3 ESCALATED: Automated remediation exhausted — see escalation brief"
                root_cause_text = AI_INTERPRETATIONS.get(fault, "")[:300]
            elif status == "false_positive":
                resolution_text = "False positive — alert triggered during planned maintenance window"
            elif status == "closed":
                resolution_text = "Resolved manually by L2 engineer"
                resolved_by     = "l2_manual"

            inc = Incident(
                number           = number,
                title            = title,
                description      = f"Automated alert: {title}",
                affected_host    = host,
                affected_service = service,
                source           = "prometheus" if idx % 3 != 0 else "manual",
                source_alert_id  = f"prom-alert-{idx:04d}" if idx % 3 != 0 else None,
                fault_category   = fault,
                priority         = priority,
                status           = status,
                sla_response_due = sla_response_due,
                sla_resolve_due  = sla_resolve_due,
                sla_breached     = sla_breached,
                resolution       = resolution_text,
                root_cause       = root_cause_text,
                resolved_by      = resolved_by,
                attempt_count    = attempt_count,
                created_at       = created_at,
                resolved_at      = resolved_at,
            )
            db.add(inc)
            await db.flush()  # get id
            incident_objs.append(inc)

            # ── Steps for this incident ────────────────────────────────────
            templates = STEP_TEMPLATES.get(fault, [])
            if status in ("new",):  # no steps yet
                pass
            elif status == "false_positive":
                # One ping step
                step_t = datetime.utcnow() - timedelta(minutes=mins_ago - 2)
                db.add(IncidentStep(
                    incident_id=inc.id, sequence=1, level="l1", step_type="ping",
                    status="pending", action="Ping host",
                    raw_output=f"Host {host}: reachable (14ms via tcp_22)", success=True,
                    duration_ms=350, created_at=step_t,
                ))
            else:
                step_t = created_at + timedelta(seconds=5)
                for seq, (stype, sname, ssuccess, scmd, sout) in enumerate(templates, start=1):
                    raw_out = sout.replace("{host}", host).replace("{service}", service) if sout else None

                    ai_interp = None
                    if stype == "ai_interpret":
                        ai_interp = AI_INTERPRETATIONS.get(fault)
                        raw_out   = ai_interp

                    # For network_down escalated: second step is already the AI interp
                    db.add(IncidentStep(
                        incident_id       = inc.id,
                        sequence          = seq,
                        level             = "l1",
                        step_type         = stype,
                        status            = "success" if ssuccess else "failed",
                        action            = sname.replace("{service}", service),
                        command           = scmd.replace("{service}", service) if scmd else None,
                        raw_output        = raw_out,
                        ai_interpretation = ai_interp,
                        success           = ssuccess,
                        duration_ms       = random.randint(300, 8000),
                        created_at        = step_t,
                    ))
                    step_t += timedelta(seconds=random.randint(3, 30))

            print(f"  {number}: {title[:60]} [{status}]")

        await db.commit()

        # ── Resolutions (agent memory) ─────────────────────────────────────
        print("Seeding resolutions (agent memory)...")
        for res_data in RESOLUTIONS_DATA:
            db.add(Resolution(**res_data, created_at=datetime.utcnow() - timedelta(hours=random.randint(1, 72))))
        await db.commit()
        print(f"  {len(RESOLUTIONS_DATA)} resolution records added")

        # ── Summary ───────────────────────────────────────────────────────
        total_r = await db.execute(select(func.count(Incident.id)))
        steps_r = await db.execute(select(func.count(IncidentStep.id)))
        print(f"\n✅ Seed complete:")
        print(f"   {len(HOSTS)} hosts | {len(NMS_SOURCES)} NMS sources")
        print(f"   {total_r.scalar()} incidents | {steps_r.scalar()} steps")
        print(f"   {len(RESOLUTIONS_DATA)} resolution records")


if __name__ == "__main__":
    asyncio.run(seed())
