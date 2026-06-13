"""
AMFI v4 — Remediation actions
Deterministic fixes executed via SSH.
Each action returns {success, output, error, action_name}.
"""
import logging
from typing import Optional
from backend.agent.tools.ssh import run_ssh_command

logger = logging.getLogger("amfi.actions")


async def restart_service(
    host: str, service: str, user: str,
    key_path: Optional[str] = None, port: int = 22,
    password: Optional[str] = None,
) -> dict:
    """Restart a systemd service."""
    cmd = f"systemctl restart {service} 2>&1 && sleep 3 && systemctl is-active {service}"
    result = await run_ssh_command(host, cmd, user, key_path, port, password)
    return {**result, "action": f"restart_service:{service}", "step_type": "action"}


async def clear_old_logs(
    host: str, user: str,
    key_path: Optional[str] = None, port: int = 22,
    password: Optional[str] = None,
    days: int = 7,
) -> dict:
    """Remove log files older than *days* days and truncate large journal."""
    cmd = (
        f"find /var/log -type f -name '*.log' -mtime +{days} -delete 2>&1; "
        f"find /var/log -type f -name '*.gz'  -mtime +{days} -delete 2>&1; "
        f"journalctl --vacuum-time={days}d 2>&1; "
        f"df -h /var/log 2>/dev/null | tail -1"
    )
    result = await run_ssh_command(host, cmd, user, key_path, port, password)
    return {**result, "action": "clear_old_logs", "step_type": "action"}


async def clear_tmp_files(
    host: str, user: str,
    key_path: Optional[str] = None, port: int = 22,
    password: Optional[str] = None,
) -> dict:
    """Clear /tmp files older than 3 days."""
    cmd = "find /tmp -type f -mtime +3 -delete 2>&1; df -h /tmp 2>/dev/null | tail -1"
    result = await run_ssh_command(host, cmd, user, key_path, port, password)
    return {**result, "action": "clear_tmp_files", "step_type": "action"}


async def clear_memory_cache(
    host: str, user: str,
    key_path: Optional[str] = None, port: int = 22,
    password: Optional[str] = None,
) -> dict:
    """Drop page cache, dentries, and inodes — safe on Linux, no data loss."""
    cmd = (
        "sync; echo 3 > /proc/sys/vm/drop_caches 2>&1 && "
        "echo 'Cache cleared' && free -h | grep Mem"
    )
    result = await run_ssh_command(host, cmd, user, key_path, port, password)
    return {**result, "action": "clear_memory_cache", "step_type": "action"}


async def kill_top_process(
    host: str, user: str,
    key_path: Optional[str] = None, port: int = 22,
    password: Optional[str] = None,
) -> dict:
    """Find and kill the process consuming the most CPU."""
    cmd = (
        "TOP_PID=$(ps aux --sort=-%cpu | awk 'NR==2{print $2}'); "
        "TOP_CMD=$(ps aux --sort=-%cpu | awk 'NR==2{print $11}'); "
        "echo \"Killing PID $TOP_PID ($TOP_CMD)\"; "
        "kill -15 $TOP_PID 2>&1; sleep 2; "
        "kill -9 $TOP_PID 2>/dev/null; "
        "echo 'Done' && top -bn1 | head -3"
    )
    result = await run_ssh_command(host, cmd, user, key_path, port, password)
    return {**result, "action": "kill_top_process", "step_type": "action"}


# ── Verification commands ──────────────────────────────────────────────────────

async def verify_disk_usage(
    host: str, user: str,
    key_path: Optional[str] = None, port: int = 22,
    password: Optional[str] = None,
    threshold: int = 90,
) -> dict:
    """Check all filesystems — success if none exceed threshold%."""
    from backend.agent.tools.diagnostics import check_disk
    result = await check_disk(host, user, key_path, port, password)
    critical = result.get("parsed", {}).get("critical", [])
    success  = not any(f["used_pct"] >= threshold for f in critical)
    return {**result, "success": success, "action": "verify_disk", "step_type": "verify"}


async def verify_cpu_usage(
    host: str, user: str,
    key_path: Optional[str] = None, port: int = 22,
    password: Optional[str] = None,
    threshold: int = 85,
) -> dict:
    """Check CPU — success if usage is below threshold%."""
    from backend.agent.tools.diagnostics import check_cpu
    result = await check_cpu(host, user, key_path, port, password)
    used   = result.get("parsed", {}).get("cpu_used_pct")
    success = used is None or used < threshold
    return {**result, "success": success, "action": "verify_cpu", "step_type": "verify"}


async def verify_memory_usage(
    host: str, user: str,
    key_path: Optional[str] = None, port: int = 22,
    password: Optional[str] = None,
    threshold: int = 85,
) -> dict:
    """Check memory — success if usage is below threshold%."""
    from backend.agent.tools.diagnostics import check_memory
    result  = await check_memory(host, user, key_path, port, password)
    used    = result.get("parsed", {}).get("mem_used_pct")
    success = used is None or used < threshold
    return {**result, "success": success, "action": "verify_memory", "step_type": "verify"}


async def verify_service_running(
    host: str, service: str, user: str,
    key_path: Optional[str] = None, port: int = 22,
    password: Optional[str] = None,
) -> dict:
    """Verify a service is active (running)."""
    from backend.agent.tools.diagnostics import check_service
    result  = await check_service(host, service, user, key_path, port, password)
    success = result.get("parsed", {}).get("running", False)
    return {**result, "success": success, "action": f"verify_service:{service}", "step_type": "verify"}
