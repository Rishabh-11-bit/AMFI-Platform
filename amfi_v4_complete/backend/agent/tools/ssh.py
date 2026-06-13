"""
AMFI v4 — SSH tool
Runs commands on remote hosts via Paramiko (sync, wrapped in executor thread).
Returns a consistent result dict for all callers.
"""
import asyncio
import logging
import socket
from typing import Optional

from backend.config import get_settings

logger   = logging.getLogger("amfi.ssh")
settings = get_settings()


async def run_ssh_command(
    host:     str,
    command:  str,
    user:     str           = "root",
    key_path: Optional[str] = None,
    port:     int           = 22,
    password: Optional[str] = None,
) -> dict:
    """
    Execute *command* on *host* over SSH.
    Returns:
      {success: bool, output: str, error: str, return_code: int}
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        _ssh_exec,
        host, command, user, key_path, port, password,
    )


def _ssh_exec(
    host:     str,
    command:  str,
    user:     str,
    key_path: Optional[str],
    port:     int,
    password: Optional[str],
) -> dict:
    """Synchronous SSH execution (runs in thread pool)."""
    try:
        import paramiko
    except ImportError:
        return {"success": False, "output": "", "error": "paramiko not installed", "return_code": -1}

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    kwargs = dict(
        hostname         = host,
        port             = port or 22,
        username         = user or "root",
        timeout          = settings.ssh_connect_timeout,
        look_for_keys    = False,
        allow_agent      = False,
    )
    if key_path:
        kwargs["key_filename"] = key_path
    elif password:
        kwargs["password"] = password
    else:
        kwargs["look_for_keys"] = True
        kwargs["allow_agent"]   = True

    try:
        client.connect(**kwargs)
        stdin, stdout, stderr = client.exec_command(command, timeout=settings.ssh_timeout)
        out = stdout.read().decode("utf-8", errors="replace").strip()
        err = stderr.read().decode("utf-8", errors="replace").strip()
        rc  = stdout.channel.recv_exit_status()
        client.close()
        return {"success": rc == 0, "output": out, "error": err, "return_code": rc}
    except paramiko.AuthenticationException as e:
        return {"success": False, "output": "", "error": f"Auth failed: {e}", "return_code": -2}
    except (socket.timeout, TimeoutError) as e:
        return {"success": False, "output": "", "error": f"Connection timeout: {e}", "return_code": -3}
    except Exception as e:
        return {"success": False, "output": "", "error": str(e), "return_code": -1}
    finally:
        try:
            client.close()
        except Exception:
            pass


async def ping_host(host: str) -> dict:
    """
    ICMP ping — try socket TCP fallback if raw ping unavailable on Windows.
    Returns {success, reachable, latency_ms}.
    """
    import asyncio
    import socket
    import time

    start = time.monotonic()

    # DNS check first — fail immediately if hostname can't be resolved
    # (avoids 10-15s Windows DNS timeout on every subsequent connection attempt)
    loop = asyncio.get_event_loop()
    try:
        await asyncio.wait_for(
            loop.run_in_executor(None, socket.getaddrinfo, host, None),
            timeout=3,
        )
    except Exception:
        ms = round((time.monotonic() - start) * 1000, 1)
        return {"success": False, "reachable": False, "latency_ms": ms, "method": "dns_fail"}

    # DNS resolved — now try TCP port 22 then 443
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, 22), timeout=2
        )
        writer.close()
        await writer.wait_closed()
        ms = round((time.monotonic() - start) * 1000, 1)
        return {"success": True, "reachable": True, "latency_ms": ms, "method": "tcp_22"}
    except Exception:
        pass

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, 443), timeout=2
        )
        writer.close()
        await writer.wait_closed()
        ms = round((time.monotonic() - start) * 1000, 1)
        return {"success": True, "reachable": True, "latency_ms": ms, "method": "tcp_443"}
    except Exception:
        pass

    ms = round((time.monotonic() - start) * 1000, 1)
    return {"success": False, "reachable": False, "latency_ms": ms, "method": "none"}
