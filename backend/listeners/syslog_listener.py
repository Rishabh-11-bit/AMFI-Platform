"""
Syslog Listener — Module 1

Listens on UDP 514 (or TCP 514) for RFC 5424 / RFC 3164 syslog messages.
No external library needed — pure Python asyncio.

How to send logs here from a Linux server:
  Edit /etc/rsyslog.conf:
    *.* @<amfi-server-ip>:514       (UDP)
    *.* @@<amfi-server-ip>:514      (TCP)
  sudo systemctl restart rsyslog

For network devices (Cisco, Juniper):
  logging host <amfi-server-ip>
  logging trap warnings

Port note: port 514 needs root. Use 5514 in dev + NAT rule.
"""
import asyncio
import logging
import re
from datetime import datetime

from backend.config import get_settings

logger = logging.getLogger("amfi.listener.syslog")
settings = get_settings()


# RFC 3164 / 5424 priority decode
def _decode_priority(pri: int):
    facility = pri >> 3
    severity = pri & 0x7
    return facility, severity


# RFC 3164 pattern: <PRI>TIMESTAMP HOSTNAME PROGRAM: MESSAGE
_RFC3164 = re.compile(
    r"^<(\d+)>"                          # <PRI>
    r"(\w{3}\s+\d+\s+[\d:]+)\s+"        # timestamp
    r"(\S+)\s+"                          # hostname
    r"(?:(\S+?)(?:\[\d+\])?:\s*)?"      # program (optional)
    r"(.*)"                              # message
)

# RFC 5424 pattern: <PRI>VERSION TIMESTAMP HOSTNAME APP-NAME PROCID MSGID ...
_RFC5424 = re.compile(
    r"^<(\d+)>(\d)\s+"                  # <PRI>VERSION
    r"(\S+)\s+"                          # TIMESTAMP
    r"(\S+)\s+"                          # HOSTNAME
    r"(\S+)\s+"                          # APP-NAME
    r"(\S+)\s+"                          # PROCID
    r"(\S+)\s*"                          # MSGID
    r"(.*)"                              # message
)


def parse_syslog_line(line: str, source_ip: str) -> dict:
    """Parse a syslog line into a dict. Returns best-effort dict."""
    line = line.strip()

    # Try RFC 5424 first
    m = _RFC5424.match(line)
    if m:
        pri = int(m.group(1))
        facility, severity = _decode_priority(pri)
        return {
            "raw":       line,
            "facility":  facility,
            "severity":  severity,
            "timestamp": m.group(3),
            "hostname":  m.group(4) if m.group(4) != "-" else source_ip,
            "program":   m.group(5) if m.group(5) != "-" else "unknown",
            "message":   m.group(8),
            "source_ip": source_ip,
            "format":    "rfc5424",
        }

    # Try RFC 3164
    m = _RFC3164.match(line)
    if m:
        pri = int(m.group(1))
        facility, severity = _decode_priority(pri)
        return {
            "raw":       line,
            "facility":  facility,
            "severity":  severity,
            "timestamp": m.group(2),
            "hostname":  m.group(3),
            "program":   m.group(4) or "unknown",
            "message":   m.group(5),
            "source_ip": source_ip,
            "format":    "rfc3164",
        }

    # Fallback: treat entire line as message
    return {
        "raw":       line,
        "facility":  1,
        "severity":  5,
        "timestamp": datetime.utcnow().isoformat(),
        "hostname":  source_ip,
        "program":   "unknown",
        "message":   line,
        "source_ip": source_ip,
        "format":    "raw",
    }


# ── UDP Listener ──────────────────────────────────────────────────────────────

class SyslogUDPProtocol(asyncio.DatagramProtocol):
    def __init__(self, callback):
        self.callback = callback

    def datagram_received(self, data: bytes, addr):
        source_ip = addr[0]
        try:
            line = data.decode("utf-8", errors="replace")
            parsed = parse_syslog_line(line, source_ip)
            asyncio.ensure_future(self.callback(parsed))
        except Exception as e:
            logger.error("Syslog UDP parse error from %s: %s", source_ip, e)

    def error_received(self, exc):
        logger.error("Syslog UDP error: %s", exc)


# ── TCP Listener ──────────────────────────────────────────────────────────────

class SyslogTCPProtocol(asyncio.Protocol):
    def __init__(self, callback):
        self.callback = callback
        self._buffer = ""
        self._peer = "unknown"

    def connection_made(self, transport):
        self._peer = transport.get_extra_info("peername", ("unknown", 0))[0]

    def data_received(self, data: bytes):
        self._buffer += data.decode("utf-8", errors="replace")
        # Split on newlines — syslog messages are newline delimited
        lines = self._buffer.split("\n")
        self._buffer = lines[-1]  # keep incomplete last line
        for line in lines[:-1]:
            if line.strip():
                try:
                    parsed = parse_syslog_line(line, self._peer)
                    asyncio.ensure_future(self.callback(parsed))
                except Exception as e:
                    logger.error("Syslog TCP parse error: %s", e)


# ── Main Listener class ───────────────────────────────────────────────────────

class SyslogListener:
    def __init__(self, on_message_callback):
        """
        on_message_callback: async function(parsed: dict) -> None
        """
        self.callback = on_message_callback

    async def start(self):
        loop = asyncio.get_event_loop()
        host = settings.syslog_host
        port = settings.syslog_port

        try:
            if settings.syslog_protocol == "tcp":
                server = await loop.create_server(
                    lambda: SyslogTCPProtocol(self.callback),
                    host, port,
                )
                logger.info("Syslog TCP listener started on %s:%d", host, port)
                async with server:
                    await server.serve_forever()
            else:
                transport, _ = await loop.create_datagram_endpoint(
                    lambda: SyslogUDPProtocol(self.callback),
                    local_addr=(host, port),
                )
                logger.info("Syslog UDP listener started on %s:%d", host, port)
                # Keep running
                try:
                    await asyncio.Future()  # run forever
                finally:
                    transport.close()

        except PermissionError:
            logger.error(
                "Cannot bind syslog port %d — use SYSLOG_PORT=5514 in .env and NAT on server. "
                "On Linux: 'sudo setcap cap_net_bind_service=+ep $(which python3)'",
                port,
            )
        except Exception as e:
            logger.error("Syslog listener error: %s", e)
