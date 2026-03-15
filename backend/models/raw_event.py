"""
RawEvent Model — Module 1: Event Ingestion

Every alert that enters AMFI from any source is stored here as-is.
Downstream modules (enrichment, correlation) read from this table.
"""
from datetime import datetime
from enum import Enum
from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, Enum as SQLEnum
from backend.database import Base


class IngestionSource(str, Enum):
    """Which protocol / tool delivered this event."""
    WEBHOOK        = "webhook"        # Generic HTTP POST
    ALERTMANAGER   = "alertmanager"   # Prometheus Alertmanager
    SNMP_TRAP      = "snmp_trap"      # SNMP v2c/v3 trap
    SYSLOG         = "syslog"         # Syslog RFC 5424
    MQTT           = "mqtt"           # MQTT broker message
    MANUAL         = "manual"         # Posted directly via API (testing)


class EventSeverity(str, Enum):
    CRITICAL  = "critical"
    MAJOR     = "major"
    MINOR     = "minor"
    WARNING   = "warning"
    INFO      = "info"
    UNKNOWN   = "unknown"


class IngestionStatus(str, Enum):
    RECEIVED    = "received"    # Stored, not yet passed downstream
    VALIDATED   = "validated"   # Schema checks passed
    FORWARDED   = "forwarded"   # Handed to Module 2 (enrichment)
    DUPLICATE   = "duplicate"   # Suppressed as duplicate
    INVALID     = "invalid"     # Failed validation


class RawEvent(Base):
    """
    Raw event as received — no enrichment, no correlation yet.
    One row per alert received, regardless of source.
    """
    __tablename__ = "raw_events"

    id              = Column(Integer, primary_key=True, autoincrement=True)

    # --- Where it came from ---
    source          = Column(SQLEnum(IngestionSource), nullable=False, index=True)
    source_host     = Column(String(255), nullable=True)   # IP / hostname of sender
    source_id       = Column(String(255), nullable=True)   # External alert ID (e.g. Alertmanager fingerprint)
    tool_name       = Column(String(100), nullable=True)   # "prometheus", "nagios", "solarwinds"

    # --- What happened ---
    severity        = Column(SQLEnum(EventSeverity), default=EventSeverity.UNKNOWN, index=True)
    title           = Column(String(500), nullable=False)   # Short summary
    message         = Column(Text, nullable=True)           # Full description
    affected_host   = Column(String(255), nullable=True, index=True)  # Which server/device
    affected_service= Column(String(255), nullable=True)   # Which service (node_exporter, etc.)

    # --- Raw payload (kept for audit / debugging) ---
    raw_payload     = Column(JSON, nullable=True)           # Entire original payload

    # --- Protocol-specific fields ---
    # SNMP
    snmp_oid        = Column(String(500), nullable=True)    # e.g. 1.3.6.1.4.1.2021.11.9.0
    snmp_community  = Column(String(100), nullable=True)
    # Syslog
    syslog_facility = Column(Integer, nullable=True)        # 0-23
    syslog_priority = Column(Integer, nullable=True)        # 0-7
    syslog_program  = Column(String(100), nullable=True)    # e.g. "kernel", "sshd"
    # MQTT
    mqtt_topic      = Column(String(500), nullable=True)

    # --- Processing state ---
    status          = Column(SQLEnum(IngestionStatus), default=IngestionStatus.RECEIVED, index=True)
    validation_error= Column(Text, nullable=True)           # Why it was marked INVALID

    # --- Timestamps ---
    received_at     = Column(DateTime, default=datetime.utcnow, index=True)
    validated_at    = Column(DateTime, nullable=True)
    forwarded_at    = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<RawEvent id={self.id} source={self.source} severity={self.severity} host={self.affected_host}>"
