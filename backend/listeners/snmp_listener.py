"""
SNMP Trap Listener — Module 1

Listens on UDP (default port 162, use 1162 in dev).
When a trap arrives from any network device, it:
  1. Parses the PDU via pysnmp
  2. Calls IngestionService.ingest_snmp()

To receive SNMP traps from real devices:
  - Point device's trap destination to this server IP:port
  - Open UDP 162 inbound on your firewall (or NAT 162 → 1162)
  - Make sure community string matches config SNMP_COMMUNITY

Supports: SNMPv1, SNMPv2c (community-based)
          SNMPv3 support: add USM users below in _build_dispatcher()
"""
import asyncio
import logging
from datetime import datetime

from backend.config import get_settings

logger = logging.getLogger("amfi.listener.snmp")
settings = get_settings()


class SNMPTrapListener:
    """
    Async SNMP trap receiver.
    Stores a callback that is called with parsed trap dict.
    """

    def __init__(self, on_trap_callback):
        """
        on_trap_callback: async function(trap_dict: dict) -> None
        """
        self.callback = on_trap_callback
        self._running = False
        self._transport = None

    async def start(self):
        """Start the UDP listener."""
        loop = asyncio.get_event_loop()
        self._running = True

        try:
            # Try to import pysnmp
            from pysnmp.carrier.asyncio.dgram import udp
            from pysnmp.entity import engine, config
            from pysnmp.entity.rfc3413 import ntfrcv
            from pysnmp import proto

            snmpEngine = engine.SnmpEngine()

            # SNMPv1/v2c community config
            config.addV1System(snmpEngine, "trap-area", settings.snmp_community)

            # Transport: listen on configured host:port
            config.addTransport(
                snmpEngine,
                udp.domainName,
                udp.UdpTransport().openServerMode(
                    (settings.snmp_host, settings.snmp_port)
                ),
            )

            # Callback when trap arrives
            def _trap_cb(snmpEngine, stateReference, contextEngineId, contextName, varBinds, cbCtx):
                source_ip = "unknown"
                try:
                    execContext = snmpEngine.observer.getExecutionContext(
                        "rfc3412.receiveMessage:request"
                    )
                    source_ip = str(execContext.get("transportAddress", "unknown"))
                except Exception:
                    pass

                varbinds = {}
                for oid, val in varBinds:
                    varbinds[str(oid)] = str(val)

                trap_dict = {
                    "source_ip":   source_ip,
                    "community":   settings.snmp_community,
                    "oid":         list(varbinds.keys())[0] if varbinds else "",
                    "varbinds":    varbinds,
                    "received_at": datetime.utcnow().isoformat(),
                }
                logger.info("SNMP trap received from %s: %s", source_ip, varbinds)
                asyncio.ensure_future(self.callback(trap_dict))

            ntfrcv.NotificationReceiver(snmpEngine, _trap_cb)
            snmpEngine.transportDispatcher.jobStarted(1)

            logger.info("SNMP trap listener started on %s:%d", settings.snmp_host, settings.snmp_port)

            # Run the dispatcher in a thread (it has its own event loop internally)
            await loop.run_in_executor(None, snmpEngine.transportDispatcher.runDispatcher)

        except PermissionError:
            logger.error(
                "Cannot bind to port %d — need root OR use port 1162 and set SNMP_PORT=1162 in .env. "
                "On Linux: 'sudo setcap cap_net_bind_service=+ep $(which python3)'",
                settings.snmp_port,
            )
        except ImportError:
            logger.warning("pysnmp not installed — SNMP listener disabled. pip install pysnmp")
        except Exception as e:
            logger.error("SNMP listener error: %s", e)

    def stop(self):
        self._running = False
        logger.info("SNMP listener stopped")
