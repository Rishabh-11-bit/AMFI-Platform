"""
AMFI v4 — Monitoring Collector
Polls monitored hosts and returns metric dicts.

Supports:
  linux   — SSH → /proc/stat, /proc/meminfo, df, /proc/loadavg, /proc/net/dev
  windows — SSH → PowerShell WMI queries
  network — SNMP → ifOperStatus, ifInOctets, ifOutOctets, sysUpTime
  generic — ICMP ping only
"""
import asyncio
import logging
import time
from typing import Optional

logger = logging.getLogger("amfi.monitoring.collector")

# ── SNMP availability check ────────────────────────────────────────────────────
try:
    from pysnmp.hlapi.v3arch.asyncio import (
        SnmpEngine, CommunityData, UsmUserData, UdpTransportTarget,
        ContextData, ObjectType, ObjectIdentity, getCmd, nextCmd,
    )
    # Auth protocol helpers (may not exist in all pysnmp builds — guard each)
    try:
        from pysnmp.hlapi.v3arch.asyncio import (
            usmHMACSHAAuthProtocol, usmHMACMD5AuthProtocol,
            usmAesCfb128Protocol,  usmDESPrivProtocol,
        )
    except ImportError:
        usmHMACSHAAuthProtocol = usmHMACMD5AuthProtocol = None
        usmAesCfb128Protocol   = usmDESPrivProtocol     = None
    SNMP_AVAILABLE = True
except Exception:
    SNMP_AVAILABLE = False
    UsmUserData = None
    logger.debug("pysnmp not available — SNMP collection disabled")


def _build_auth_data(host):
    """Return CommunityData (v1/v2c) or UsmUserData (v3) for a host."""
    version = getattr(host, "snmp_version", "2c") or "2c"
    if version == "3" and UsmUserData is not None:
        auth_key = getattr(host, "snmp_v3_auth_key", None) or ""
        priv_key = getattr(host, "snmp_v3_priv_key", None) or ""
        user     = getattr(host, "snmp_v3_user", None)    or "amfi"
        # Pick auth protocol
        auth_proto_str = (getattr(host, "snmp_v3_auth_protocol", None) or "SHA").upper()
        priv_proto_str = (getattr(host, "snmp_v3_priv_protocol", None) or "AES").upper()
        auth_proto = (
            usmHMACSHAAuthProtocol if (auth_proto_str == "SHA" and usmHMACSHAAuthProtocol)
            else usmHMACMD5AuthProtocol if usmHMACMD5AuthProtocol
            else None
        )
        priv_proto = (
            usmAesCfb128Protocol if (priv_proto_str == "AES" and usmAesCfb128Protocol)
            else usmDESPrivProtocol if usmDESPrivProtocol
            else None
        )
        kwargs = {"userName": user}
        if auth_key and auth_proto:
            kwargs["authKey"]      = auth_key
            kwargs["authProtocol"] = auth_proto
        if priv_key and priv_proto and auth_proto:
            kwargs["privKey"]      = priv_key
            kwargs["privProtocol"] = priv_proto
        return UsmUserData(**kwargs)
    # Default: v2c community string (mpModel=1)
    community = getattr(host, "snmp_community", "public") or "public"
    return CommunityData(community, mpModel=1)


# ══════════════════════════════════════════════════════════════════════════════
# Public entry point
# ══════════════════════════════════════════════════════════════════════════════

async def poll_host(host) -> dict:
    """
    Poll a MonitoredHost ORM object.
    Returns {metric_name: float_value, ...}
    Always includes ping_up and ping_ms.
    """
    metrics: dict[str, float] = {}

    # ── ICMP / TCP reachability ────────────────────────────────────────────────
    ping = await _ping(host.ip_address or host.hostname)
    metrics["ping_up"] = 1.0 if ping["up"] else 0.0
    if ping["latency_ms"] is not None:
        metrics["ping_ms"] = float(ping["latency_ms"])

    if not ping["up"]:
        logger.debug("Host %s (%s) is DOWN — skipping deep metrics", host.hostname, host.ip_address)
        return metrics

    # ── Device-type specific collection ───────────────────────────────────────
    try:
        if host.device_type == "linux":
            metrics.update(await _collect_linux(host))
        elif host.device_type == "windows":
            metrics.update(await _collect_windows(host))
        elif host.device_type == "network":
            metrics.update(await _collect_snmp(host))
        # generic → ping only (already done)
    except Exception as e:
        logger.warning("Deep collection failed for %s: %s", host.hostname, e)

    return metrics


# ══════════════════════════════════════════════════════════════════════════════
# ICMP / TCP ping
# ══════════════════════════════════════════════════════════════════════════════

async def _ping(target: str) -> dict:
    """Try icmplib first, fall back to TCP port checks."""
    # ── icmplib (real ICMP, needs root/admin or elevated on Windows) ──────────
    try:
        import icmplib
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: icmplib.ping(target, count=3, timeout=2, privileged=False),
        )
        return {
            "up":         result.is_alive,
            "latency_ms": round(result.avg_rtt, 1) if result.is_alive else None,
            "packet_loss": result.packet_loss,
            "method":     "icmp",
        }
    except Exception:
        pass

    # ── TCP fallback (SSH port 22, then 443, then 80) ─────────────────────────
    for port in (22, 443, 80):
        t0 = time.monotonic()
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(target, port), timeout=3
            )
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            ms = round((time.monotonic() - t0) * 1000, 1)
            return {"up": True, "latency_ms": ms, "packet_loss": 0.0, "method": f"tcp_{port}"}
        except Exception:
            continue

    return {"up": False, "latency_ms": None, "packet_loss": 1.0, "method": "none"}


# ══════════════════════════════════════════════════════════════════════════════
# Linux — SSH
# ══════════════════════════════════════════════════════════════════════════════

_LINUX_CMD = r"""
bash -s << 'METRICS_EOF'
set -e
# CPU — read /proc/stat twice 0.5s apart
read -r _ u1 n1 s1 i1 w1 q1 r1 _ < /proc/stat
sleep 0.5
read -r _ u2 n2 s2 i2 w2 q2 r2 _ < /proc/stat
idle1=$((i1+w1)); total1=$((u1+n1+s1+i1+w1+q1+r1))
idle2=$((i2+w2)); total2=$((u2+n2+s2+i2+w2+q2+r2))
didle=$((idle2-idle1)); dtotal=$((total2-total1))
if [ $dtotal -gt 0 ]; then
  cpu=$(awk "BEGIN{printf \"%.1f\",100*(1-$didle/$dtotal)}")
else
  cpu=0.0
fi
echo "cpu=$cpu"
# RAM
ram=$(awk '/MemTotal/{t=$2}/MemAvailable/{a=$2}END{printf "%.1f",100*(1-a/t)}' /proc/meminfo 2>/dev/null || echo 0)
echo "ram=$ram"
# Disk /
disk=$(df / 2>/dev/null | awk 'NR==2{gsub(/%/,"",$5);print $5}' || echo 0)
echo "disk=$disk"
# Load 1min
load=$(awk '{print $1}' /proc/loadavg 2>/dev/null || echo 0)
echo "load=$load"
# Network I/O (sum all non-loopback interfaces, bytes/s over 1s)
_net_read(){ awk '/:/{gsub(/:/,"");if($1!="lo")rx+=$2;if($1!="lo")tx+=$10}END{print rx" "tx}' /proc/net/dev; }
read -r rx1 tx1 <<< "$(_net_read)"; sleep 1; read -r rx2 tx2 <<< "$(_net_read)"
net_rx=$(( (rx2 - rx1) * 8 ))   # bps
net_tx=$(( (tx2 - tx1) * 8 ))
echo "net_rx=$net_rx"
echo "net_tx=$net_tx"
METRICS_EOF
""".strip()


async def _collect_linux(host) -> dict:
    from backend.agent.tools.ssh import run_ssh_command
    metrics: dict[str, float] = {}

    r = await run_ssh_command(
        host        = host.ip_address or host.hostname,
        command     = _LINUX_CMD,
        user        = host.ssh_user or "root",
        key_path    = host.ssh_key_path,
        port        = host.ssh_port or 22,
        password    = host.ssh_password,
    )

    if not r["success"] and not r["output"]:
        logger.debug("Linux SSH failed for %s: %s", host.hostname, r.get("error", ""))
        return metrics

    for line in r["output"].splitlines():
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip(); val = val.strip()
        try:
            fval = float(val)
            if key == "cpu":
                metrics["cpu_percent"] = max(0.0, min(100.0, fval))
            elif key == "ram":
                metrics["ram_percent"] = max(0.0, min(100.0, fval))
            elif key == "disk":
                metrics["disk_percent"] = max(0.0, min(100.0, fval))
            elif key == "load":
                metrics["load_1m"] = max(0.0, fval)
            elif key == "net_rx":
                metrics["net_rx_bps"] = max(0.0, fval)
            elif key == "net_tx":
                metrics["net_tx_bps"] = max(0.0, fval)
        except (ValueError, TypeError):
            pass

    return metrics


# ══════════════════════════════════════════════════════════════════════════════
# Windows — SSH + PowerShell
# ══════════════════════════════════════════════════════════════════════════════

_WINDOWS_CMD = (
    "powershell -NoProfile -Command \""
    "$cpu=[math]::Round((Get-WmiObject Win32_Processor | Measure-Object LoadPercentage -Average).Average,1);"
    "$os=Get-WmiObject Win32_OperatingSystem;"
    "$ram=[math]::Round(($os.TotalVisibleMemorySize-$os.FreePhysicalMemory)/$os.TotalVisibleMemorySize*100,1);"
    "$d=Get-WmiObject Win32_LogicalDisk -Filter \\\"DeviceID='C:'\\\";"
    "$disk=[math]::Round(($d.Size-$d.FreeSpace)/$d.Size*100,1);"
    "Write-Output \\\"cpu=$cpu\\\"; Write-Output \\\"ram=$ram\\\"; Write-Output \\\"disk=$disk\\\"\""
)


async def _collect_windows(host) -> dict:
    from backend.agent.tools.ssh import run_ssh_command
    metrics: dict[str, float] = {}

    r = await run_ssh_command(
        host     = host.ip_address or host.hostname,
        command  = _WINDOWS_CMD,
        user     = host.ssh_user or "Administrator",
        key_path = host.ssh_key_path,
        port     = host.ssh_port or 22,
        password = host.ssh_password,
    )

    if not r["success"] and not r["output"]:
        return metrics

    for line in r["output"].splitlines():
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        try:
            fval = float(val.strip())
            if key.strip() == "cpu":
                metrics["cpu_percent"] = max(0.0, min(100.0, fval))
            elif key.strip() == "ram":
                metrics["ram_percent"] = max(0.0, min(100.0, fval))
            elif key.strip() == "disk":
                metrics["disk_percent"] = max(0.0, min(100.0, fval))
        except (ValueError, TypeError):
            pass

    return metrics


# ══════════════════════════════════════════════════════════════════════════════
# Network — SNMP
# ══════════════════════════════════════════════════════════════════════════════

# Standard OIDs
_OID_UPTIME        = "1.3.6.1.2.1.1.3.0"
_OID_IF_DESCR      = "1.3.6.1.2.1.2.2.1.2"    # ifDescr table
_OID_IF_STATUS     = "1.3.6.1.2.1.2.2.1.8"    # ifOperStatus (1=up, 2=down)
_OID_IF_IN_OCTETS  = "1.3.6.1.2.1.2.2.1.10"   # ifInOctets
_OID_IF_OUT_OCTETS = "1.3.6.1.2.1.2.2.1.16"   # ifOutOctets
_OID_HR_CPU        = "1.3.6.1.2.1.25.3.3.1.2" # hrProcessorLoad (HOST-RESOURCES-MIB)


async def _collect_snmp(host) -> dict:
    if not SNMP_AVAILABLE:
        logger.debug("SNMP not available — skipping %s", host.hostname)
        return {}

    metrics:   dict[str, float] = {}
    target     = host.ip_address or host.hostname
    port       = host.snmp_port or 161
    auth_data  = _build_auth_data(host)

    try:
        engine = SnmpEngine()

        # ── Uptime ────────────────────────────────────────────────────────────
        uptime_val = await _snmp_get(engine, target, port, auth_data, _OID_UPTIME)
        if uptime_val is not None:
            # sysUpTime is in 1/100th seconds (TimeTicks)
            metrics["uptime_seconds"] = float(int(uptime_val)) / 100.0

        # ── CPU (HOST-RESOURCES-MIB, optional — not all devices support it) ──
        cpu_vals = await _snmp_walk(engine, target, port, auth_data, _OID_HR_CPU)
        if cpu_vals:
            avg_cpu = sum(float(v) for v in cpu_vals) / len(cpu_vals)
            metrics["cpu_percent"] = round(avg_cpu, 1)

        # ── Interface statuses ────────────────────────────────────────────────
        if_statuses = await _snmp_walk(engine, target, port, auth_data, _OID_IF_STATUS)
        if if_statuses:
            total = len(if_statuses)
            up    = sum(1 for v in if_statuses if int(v) == 1)
            metrics["if_up_count"]    = float(up)
            metrics["if_total_count"] = float(total)
            metrics["if_up_pct"]      = round(up / total * 100, 1) if total else 0.0

        # ── Interface bandwidth (in + out octets, 1s delta) ──────────────────
        rx1 = await _snmp_walk(engine, target, port, auth_data, _OID_IF_IN_OCTETS)
        tx1 = await _snmp_walk(engine, target, port, auth_data, _OID_IF_OUT_OCTETS)
        if rx1 and tx1:
            await asyncio.sleep(1)
            rx2 = await _snmp_walk(engine, target, port, auth_data, _OID_IF_IN_OCTETS)
            tx2 = await _snmp_walk(engine, target, port, auth_data, _OID_IF_OUT_OCTETS)
            if rx2 and tx2:
                total_rx_bps = sum(max(0, int(b) - int(a)) for a, b in zip(rx1, rx2)) * 8
                total_tx_bps = sum(max(0, int(b) - int(a)) for a, b in zip(tx1, tx2)) * 8
                metrics["net_rx_bps"] = float(total_rx_bps)
                metrics["net_tx_bps"] = float(total_tx_bps)

        engine.closeDispatcher()

    except Exception as e:
        logger.debug("SNMP collection error for %s: %s", host.hostname, e)

    return metrics


async def _snmp_get(engine, target: str, port: int, auth_data, oid: str):
    """Get a single SNMP OID value using pre-built auth_data."""
    try:
        transport = await UdpTransportTarget.create((target, port), timeout=3, retries=1)
        errorIndication, errorStatus, _, varBinds = await getCmd(
            engine, auth_data, transport, ContextData(),
            ObjectType(ObjectIdentity(oid)),
        )
        if errorIndication or errorStatus:
            return None
        return varBinds[0][1] if varBinds else None
    except Exception:
        return None


async def _snmp_walk(engine, target: str, port: int, auth_data, oid: str) -> list:
    """Walk an SNMP OID table and return list of values using pre-built auth_data."""
    results = []
    try:
        transport = await UdpTransportTarget.create((target, port), timeout=3, retries=1)
        async for (errorIndication, errorStatus, _, varBinds) in nextCmd(
            engine, auth_data, transport, ContextData(),
            ObjectType(ObjectIdentity(oid)),
            lexicographicMode=False,
        ):
            if errorIndication or errorStatus:
                break
            for _, val in varBinds:
                results.append(val)
    except Exception:
        pass
    return results
