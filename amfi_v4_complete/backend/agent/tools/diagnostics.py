"""
AMFI v4 — Diagnostic commands
All read-only SSH commands that gather information.
Returns structured parsed results alongside raw output.
"""
import re
import logging
from typing import Optional
from backend.agent.tools.ssh import run_ssh_command

logger = logging.getLogger("amfi.diagnostics")


async def check_disk(host: str, user: str, key_path: Optional[str] = None,
                     port: int = 22, password: Optional[str] = None) -> dict:
    cmd = "df -h --output=target,pcent,avail,size 2>/dev/null | sort -k2 -rn | head -20"
    result = await run_ssh_command(host, cmd, user, key_path, port, password)
    parsed = _parse_disk(result["output"])
    return {**result, "command": cmd, "parsed": parsed, "step_type": "diagnostic_disk"}


def _parse_disk(output: str) -> dict:
    filesystems = []
    critical = []
    for line in output.splitlines()[1:]:  # skip header
        parts = line.split()
        if len(parts) >= 2:
            mount   = parts[0]
            pct_str = parts[1].replace("%", "")
            try:
                pct = int(pct_str)
                avail = parts[2] if len(parts) > 2 else "?"
                filesystems.append({"mount": mount, "used_pct": pct, "avail": avail})
                if pct >= 85:
                    critical.append({"mount": mount, "used_pct": pct, "avail": avail})
            except ValueError:
                pass
    return {
        "filesystems": filesystems,
        "critical":    critical,
        "issues":      [f"{f['mount']} at {f['used_pct']}% (avail: {f['avail']})" for f in critical],
    }


async def check_cpu(host: str, user: str, key_path: Optional[str] = None,
                    port: int = 22, password: Optional[str] = None) -> dict:
    cmd = "top -bn1 | head -5"
    result = await run_ssh_command(host, cmd, user, key_path, port, password)
    parsed = _parse_cpu(result["output"])
    return {**result, "command": cmd, "parsed": parsed, "step_type": "diagnostic_cpu"}


def _parse_cpu(output: str) -> dict:
    cpu_idle  = None
    cpu_used  = None
    load_avg  = []
    for line in output.splitlines():
        if "Cpu(s)" in line or "%Cpu" in line:
            m = re.search(r"(\d+\.?\d*)\s*id", line)
            if m:
                cpu_idle = float(m.group(1))
                cpu_used = round(100 - cpu_idle, 1)
        if "load average" in line.lower():
            m = re.findall(r"[\d.]+", line.split("load average")[-1])
            load_avg = [float(x) for x in m[:3]]
    return {
        "cpu_used_pct": cpu_used,
        "cpu_idle_pct": cpu_idle,
        "load_avg":     load_avg,
        "issues": (
            [f"CPU at {cpu_used}%"] if cpu_used and cpu_used > 80 else []
        ),
    }


async def check_memory(host: str, user: str, key_path: Optional[str] = None,
                       port: int = 22, password: Optional[str] = None) -> dict:
    cmd = "free -h && echo '---' && cat /proc/meminfo | grep -E 'MemTotal|MemFree|MemAvailable|SwapTotal|SwapFree' 2>/dev/null"
    result = await run_ssh_command(host, cmd, user, key_path, port, password)
    parsed = _parse_memory(result["output"])
    return {**result, "command": cmd, "parsed": parsed, "step_type": "diagnostic_memory"}


def _parse_memory(output: str) -> dict:
    mem_used_pct = None
    for line in output.splitlines():
        if line.startswith("Mem:"):
            parts = line.split()
            if len(parts) >= 3:
                try:
                    total     = _parse_mem_size(parts[1])
                    used      = _parse_mem_size(parts[2])
                    if total > 0:
                        mem_used_pct = round(used / total * 100, 1)
                except Exception:
                    pass
    return {
        "mem_used_pct": mem_used_pct,
        "issues":       [f"Memory at {mem_used_pct}%"] if mem_used_pct and mem_used_pct > 80 else [],
    }


def _parse_mem_size(s: str) -> float:
    """Parse 'free -h' output like '3.7G', '512M' to MB float."""
    s = s.strip()
    if s.endswith("G"):
        return float(s[:-1]) * 1024
    if s.endswith("M"):
        return float(s[:-1])
    if s.endswith("K"):
        return float(s[:-1]) / 1024
    return float(s)


async def check_processes(host: str, user: str, key_path: Optional[str] = None,
                          port: int = 22, password: Optional[str] = None) -> dict:
    cmd = "ps aux --sort=-%cpu 2>/dev/null | head -15 || ps aux | sort -rk3 | head -15"
    result = await run_ssh_command(host, cmd, user, key_path, port, password)
    return {**result, "command": cmd, "parsed": {"raw": result["output"][:1000]}, "step_type": "diagnostic_processes"}


async def check_service(host: str, service: str, user: str,
                        key_path: Optional[str] = None, port: int = 22,
                        password: Optional[str] = None) -> dict:
    cmd = f"systemctl status {service} 2>&1 | head -30"
    result = await run_ssh_command(host, cmd, user, key_path, port, password)
    parsed = _parse_service_status(result["output"], service)
    return {**result, "command": cmd, "parsed": parsed, "step_type": "diagnostic_service"}


def _parse_service_status(output: str, service: str) -> dict:
    running = (
        "active (running)" in output.lower()
        or "active: active" in output.lower()
    )
    failed  = "failed" in output.lower() or "inactive" in output.lower()
    return {
        "service": service,
        "running": running,
        "failed":  failed,
        "issues":  [f"{service} is {'not running' if not running else 'running'}"],
    }


async def check_service_logs(host: str, service: str, user: str,
                             key_path: Optional[str] = None, port: int = 22,
                             password: Optional[str] = None, lines: int = 50) -> dict:
    cmd = f"journalctl -u {service} -n {lines} --no-pager 2>&1 || tail -n {lines} /var/log/{service}/*.log 2>/dev/null || tail -n {lines} /var/log/syslog 2>/dev/null"
    result = await run_ssh_command(host, cmd, user, key_path, port, password)
    return {**result, "command": cmd, "parsed": {"raw": result["output"][:2000]}, "step_type": "diagnostic_logs"}


async def check_network_interfaces(host: str, user: str, key_path: Optional[str] = None,
                                   port: int = 22, password: Optional[str] = None) -> dict:
    cmd = "ip addr show 2>/dev/null || ifconfig 2>/dev/null"
    result = await run_ssh_command(host, cmd, user, key_path, port, password)
    return {**result, "command": cmd, "parsed": {"raw": result["output"][:2000]}, "step_type": "diagnostic_network"}


async def check_db_service(host: str, db_type: str, user: str,
                           key_path: Optional[str] = None, port: int = 22,
                           password: Optional[str] = None) -> dict:
    service_map = {
        "mysql":      "mysql",
        "postgres":   "postgresql",
        "postgresql": "postgresql",
        "mongodb":    "mongod",
        "redis":      "redis-server",
    }
    service = service_map.get(db_type.lower(), db_type)
    return await check_service(host, service, user, key_path, port, password)
