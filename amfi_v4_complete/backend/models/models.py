"""AMFI v4 — SQLAlchemy ORM models."""
import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Integer, String, Text, Boolean, DateTime, Float,
    JSON, ForeignKey, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


# ── Enums ──────────────────────────────────────────────────────────────────────

class IncidentStatus(str, enum.Enum):
    NEW           = "new"
    TRIAGING      = "triaging"
    L1_RUNNING    = "l1_running"
    L1_WAITING    = "l1_waiting"
    L1_FAILED     = "l1_failed"
    L2_RUNNING    = "l2_running"
    L2_WAITING    = "l2_waiting"
    L2_FAILED     = "l2_failed"
    L3_ESCALATED  = "l3_escalated"
    RESOLVED      = "resolved"
    CLOSED        = "closed"
    FALSE_POSITIVE = "false_positive"


class Priority(str, enum.Enum):
    P1 = "p1"
    P2 = "p2"
    P3 = "p3"
    P4 = "p4"


class FaultCategory(str, enum.Enum):
    HIGH_CPU         = "high_cpu"
    HIGH_MEMORY      = "high_memory"
    DISK_FULL        = "disk_full"
    SERVICE_DOWN     = "service_down"
    NETWORK_DOWN     = "network_down"
    HIGH_LATENCY     = "high_latency"
    DATABASE_ISSUE   = "database_issue"
    SECURITY_ALERT   = "security_alert"
    HARDWARE_FAILURE = "hardware_failure"
    APPLICATION_ERROR = "application_error"
    UNKNOWN          = "unknown"


# ── Incident ───────────────────────────────────────────────────────────────────

class Incident(Base):
    __tablename__ = "incidents"

    id:               Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    number:           Mapped[str]           = mapped_column(String(20), unique=True, index=True, nullable=False)
    title:            Mapped[str]           = mapped_column(String(500), nullable=False)
    description:      Mapped[Optional[str]] = mapped_column(Text)
    affected_host:    Mapped[Optional[str]] = mapped_column(String(255), index=True)
    affected_service: Mapped[Optional[str]] = mapped_column(String(255))
    source:           Mapped[str]           = mapped_column(String(50), default="manual", nullable=False)
    source_alert_id:  Mapped[Optional[str]] = mapped_column(String(255), index=True)
    fault_category:   Mapped[Optional[str]] = mapped_column(String(50))
    priority:         Mapped[Optional[str]] = mapped_column(String(10), default="p3")
    status:           Mapped[str]           = mapped_column(String(30), default="new", nullable=False, index=True)
    sla_response_due: Mapped[Optional[datetime]] = mapped_column(DateTime)
    sla_resolve_due:  Mapped[Optional[datetime]] = mapped_column(DateTime)
    sla_breached:     Mapped[bool]          = mapped_column(Boolean, default=False)
    resolution:       Mapped[Optional[str]] = mapped_column(Text)
    root_cause:       Mapped[Optional[str]] = mapped_column(Text)
    resolved_by:      Mapped[Optional[str]] = mapped_column(String(100))
    attempt_count:    Mapped[int]           = mapped_column(Integer, default=0)
    raw_alert:        Mapped[Optional[dict]]= mapped_column(JSON)
    created_at:       Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    resolved_at:      Mapped[Optional[datetime]] = mapped_column(DateTime)

    steps:     Mapped[list["IncidentStep"]] = relationship(
        "IncidentStep", back_populates="incident",
        order_by="IncidentStep.sequence", cascade="all, delete-orphan",
    )
    approvals: Mapped[list["Approval"]] = relationship(
        "Approval", back_populates="incident", cascade="all, delete-orphan",
    )


# ── Incident Step ──────────────────────────────────────────────────────────────

class IncidentStep(Base):
    __tablename__ = "incident_steps"

    id:               Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id:      Mapped[int]           = mapped_column(Integer, ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    sequence:         Mapped[int]           = mapped_column(Integer, default=0)
    level:            Mapped[Optional[str]] = mapped_column(String(10))   # l1, l2, l3
    step_type:        Mapped[Optional[str]] = mapped_column(String(50))   # ping, diagnostic, ai_interpret, action, verify
    status:           Mapped[str]           = mapped_column(String(20), default="pending")
    action:           Mapped[Optional[str]] = mapped_column(String(255))
    command:          Mapped[Optional[str]] = mapped_column(Text)
    raw_output:       Mapped[Optional[str]] = mapped_column(Text)
    parsed_result:    Mapped[Optional[dict]]= mapped_column(JSON)
    ai_interpretation:Mapped[Optional[str]] = mapped_column(Text)
    success:          Mapped[Optional[bool]]= mapped_column(Boolean)
    error:            Mapped[Optional[str]] = mapped_column(Text)
    duration_ms:      Mapped[Optional[int]] = mapped_column(Integer)
    created_at:       Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow)

    incident: Mapped["Incident"] = relationship("Incident", back_populates="steps")


# ── Approval ───────────────────────────────────────────────────────────────────

class Approval(Base):
    __tablename__ = "approvals"

    id:               Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id:      Mapped[int]           = mapped_column(Integer, ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    token:            Mapped[str]           = mapped_column(String(64), unique=True, index=True,
                                                             default=lambda: uuid.uuid4().hex)
    action:           Mapped[str]           = mapped_column(String(255))
    host:             Mapped[Optional[str]] = mapped_column(String(255))
    risk_level:       Mapped[str]           = mapped_column(String(20), default="high")
    reason:           Mapped[Optional[str]] = mapped_column(Text)
    rollback:         Mapped[Optional[str]] = mapped_column(Text)
    incident_summary: Mapped[Optional[str]] = mapped_column(Text)
    steps_so_far:     Mapped[Optional[dict]]= mapped_column(JSON)
    status:           Mapped[str]           = mapped_column(String(20), default="pending", index=True)
    decided_by:       Mapped[Optional[str]] = mapped_column(String(100))
    decision_note:    Mapped[Optional[str]] = mapped_column(Text)
    decided_at:       Mapped[Optional[datetime]] = mapped_column(DateTime)
    expires_at:       Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at:       Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow)

    incident: Mapped["Incident"] = relationship("Incident", back_populates="approvals")


# ── Host / CMDB ────────────────────────────────────────────────────────────────

class Host(Base):
    __tablename__ = "hosts"

    id:               Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    hostname:         Mapped[str]           = mapped_column(String(255), unique=True, index=True)
    ip_address:       Mapped[Optional[str]] = mapped_column(String(45))
    os:               Mapped[Optional[str]] = mapped_column(String(100))
    environment:      Mapped[Optional[str]] = mapped_column(String(50))   # prod, staging, dev
    criticality:      Mapped[str]           = mapped_column(String(20), default="medium")
    business_service: Mapped[Optional[str]] = mapped_column(String(255))
    owner_email:      Mapped[Optional[str]] = mapped_column(String(255))
    ssh_user:         Mapped[str]           = mapped_column(String(100), default="root")
    ssh_key_path:     Mapped[Optional[str]] = mapped_column(String(500))
    ssh_port:         Mapped[int]           = mapped_column(Integer, default=22)
    auto_remediate:   Mapped[bool]          = mapped_column(Boolean, default=True)
    approval_required:Mapped[bool]          = mapped_column(Boolean, default=False)
    never_touch:      Mapped[bool]          = mapped_column(Boolean, default=False)
    known_issues:     Mapped[Optional[str]] = mapped_column(Text)
    services:         Mapped[Optional[list]]= mapped_column(JSON)  # list of service names
    created_at:       Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow)


# ── Resolution (agent memory) ──────────────────────────────────────────────────

class Resolution(Base):
    __tablename__ = "resolutions"

    id:               Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id:      Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("incidents.id", ondelete="SET NULL"))
    host:             Mapped[Optional[str]] = mapped_column(String(255), index=True)
    fault_category:   Mapped[Optional[str]] = mapped_column(String(50), index=True)
    fix_action:       Mapped[Optional[str]] = mapped_column(String(255))
    success:          Mapped[bool]          = mapped_column(Boolean, default=True)
    time_to_fix_min:  Mapped[Optional[float]] = mapped_column(Float)
    resolved_at_level:Mapped[Optional[str]] = mapped_column(String(20))  # agent_l1, agent_l2, l3_human
    notes:            Mapped[Optional[str]] = mapped_column(Text)
    created_at:       Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow)


# ── NMS Source ─────────────────────────────────────────────────────────────────

class NMSSource(Base):
    __tablename__ = "nms_sources"

    id:            Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    name:          Mapped[str]           = mapped_column(String(100), unique=True)
    nms_type:      Mapped[str]           = mapped_column(String(50))  # prometheus, zabbix, solarwinds, prtg
    base_url:      Mapped[Optional[str]] = mapped_column(String(500))
    username:      Mapped[Optional[str]] = mapped_column(String(255))
    password:      Mapped[Optional[str]] = mapped_column(String(255))
    api_token:     Mapped[Optional[str]] = mapped_column(Text)
    enabled:       Mapped[bool]          = mapped_column(Boolean, default=True)
    poll_interval: Mapped[int]           = mapped_column(Integer, default=300)
    last_polled_at:Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_error:    Mapped[Optional[str]] = mapped_column(Text)
    status:        Mapped[str]           = mapped_column(String(20), default="unknown")
    created_at:    Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow)


# ── SLA Policy ─────────────────────────────────────────────────────────────────

class SLAPolicy(Base):
    __tablename__ = "sla_policies"

    id:               Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    priority:         Mapped[str]           = mapped_column(String(10), index=True)
    customer:         Mapped[Optional[str]] = mapped_column(String(255))
    response_minutes: Mapped[int]           = mapped_column(Integer)
    resolve_minutes:  Mapped[int]           = mapped_column(Integer)


# ── User ───────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id:              Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    username:        Mapped[str]           = mapped_column(String(100), unique=True, index=True)
    email:           Mapped[Optional[str]] = mapped_column(String(255), unique=True)
    hashed_password: Mapped[str]           = mapped_column(String(255))
    role:            Mapped[str]           = mapped_column(String(50), default="viewer")
    full_name:       Mapped[Optional[str]] = mapped_column(String(255))
    is_active:       Mapped[bool]          = mapped_column(Boolean, default=True)
    created_at:      Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow)


# ── Monitoring ─────────────────────────────────────────────────────────────────

class DeviceType(str, enum.Enum):
    LINUX   = "linux"
    WINDOWS = "windows"
    NETWORK = "network"   # routers / switches via SNMP
    GENERIC = "generic"   # ICMP-only


class MonitoredHost(Base):
    """Hosts actively polled for metrics by the monitoring scheduler."""
    __tablename__ = "monitored_hosts"

    id:             Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    hostname:       Mapped[str]           = mapped_column(String(255), unique=True, index=True)
    ip_address:     Mapped[str]           = mapped_column(String(45), nullable=False)
    display_name:   Mapped[Optional[str]] = mapped_column(String(255))
    device_type:    Mapped[str]           = mapped_column(String(20), default="linux")  # DeviceType enum
    location:       Mapped[Optional[str]] = mapped_column(String(255))
    environment:    Mapped[str]           = mapped_column(String(50), default="prod")

    # SSH (linux / windows)
    ssh_user:       Mapped[str]           = mapped_column(String(100), default="root")
    ssh_port:       Mapped[int]           = mapped_column(Integer, default=22)
    ssh_key_path:   Mapped[Optional[str]] = mapped_column(String(500))
    ssh_password:   Mapped[Optional[str]] = mapped_column(String(255))

    # SNMP (network devices) — v2c
    snmp_community: Mapped[str]           = mapped_column(String(100), default="public")
    snmp_port:      Mapped[int]           = mapped_column(Integer, default=161)
    snmp_version:   Mapped[str]           = mapped_column(String(5), default="2c")

    # SNMP v3 auth (only used when snmp_version == "3")
    snmp_v3_user:          Mapped[Optional[str]] = mapped_column(String(100))
    snmp_v3_auth_protocol: Mapped[str]           = mapped_column(String(10), default="SHA")   # SHA | MD5
    snmp_v3_auth_key:      Mapped[Optional[str]] = mapped_column(String(255))
    snmp_v3_priv_protocol: Mapped[str]           = mapped_column(String(10), default="AES")   # AES | DES
    snmp_v3_priv_key:      Mapped[Optional[str]] = mapped_column(String(255))

    # Polling config
    enabled:        Mapped[bool]          = mapped_column(Boolean, default=True)
    poll_interval:  Mapped[int]           = mapped_column(Integer, default=60)  # seconds
    last_polled_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_seen_at:   Mapped[Optional[datetime]] = mapped_column(DateTime)
    status:         Mapped[str]           = mapped_column(String(20), default="unknown")  # up/down/degraded/unknown
    last_error:     Mapped[Optional[str]] = mapped_column(Text)
    created_at:     Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow)

    samples:  Mapped[list["MetricSample"]] = relationship(
        "MetricSample", back_populates="host", cascade="all, delete-orphan",
    )


class MetricSample(Base):
    """Time-series metric readings from monitored hosts."""
    __tablename__ = "metric_samples"

    id:         Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    host_id:    Mapped[int]           = mapped_column(Integer, ForeignKey("monitored_hosts.id", ondelete="CASCADE"), index=True)
    metric:     Mapped[str]           = mapped_column(String(50), index=True)   # cpu_percent, ram_percent, disk_percent …
    value:      Mapped[float]         = mapped_column(Float, nullable=False)
    unit:       Mapped[Optional[str]] = mapped_column(String(20))               # %, ms, bps
    sampled_at: Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow, index=True)

    host: Mapped["MonitoredHost"] = relationship("MonitoredHost", back_populates="samples")

    __table_args__ = (
        Index("ix_metric_samples_host_metric_time", "host_id", "metric", "sampled_at"),
    )


class ThresholdRule(Base):
    """Alert rules — create an incident when a metric crosses a threshold."""
    __tablename__ = "threshold_rules"

    id:               Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    name:             Mapped[str]           = mapped_column(String(255), nullable=False)
    host_id:          Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("monitored_hosts.id", ondelete="CASCADE"), nullable=True)
    device_type:      Mapped[Optional[str]] = mapped_column(String(20))   # None = all device types
    metric:           Mapped[str]           = mapped_column(String(50), nullable=False)
    operator:         Mapped[str]           = mapped_column(String(5), default="gt")   # gt, lt, gte, lte, eq
    threshold:        Mapped[float]         = mapped_column(Float, nullable=False)
    priority:         Mapped[str]           = mapped_column(String(10), default="p3")
    fault_category:   Mapped[str]           = mapped_column(String(50), default="unknown")
    cooldown_minutes: Mapped[int]           = mapped_column(Integer, default=30)
    enabled:          Mapped[bool]          = mapped_column(Boolean, default=True)
    created_at:       Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow)


# ── Audit Log ──────────────────────────────────────────────────────────────────

class AuditLog(Base):
    __tablename__ = "audit_log"

    id:          Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("incidents.id", ondelete="SET NULL"), index=True)
    actor:       Mapped[str]           = mapped_column(String(100), default="system")
    action:      Mapped[str]           = mapped_column(String(255))
    detail:      Mapped[Optional[str]] = mapped_column(Text)
    created_at:  Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow)
