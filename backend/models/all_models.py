"""
AMFI Platform — All Database Models
Covers all 8 pipeline modules:
  1. Event Ingestion
  2. Event Enrichment
  3. Event Correlation & Deduplication
  4. Decision Engine
  5. Diagnostics
  6. Remediation Execution
  7. Verification & Closure
  8. Feedback & Continuous Learning
"""
from datetime import datetime
from enum import Enum
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean,
    JSON, Float, ForeignKey, Enum as SQLEnum
)
from sqlalchemy.orm import relationship
from backend.database import Base


# ═══════════════════════════════════════════════════════════════════════════════
# SHARED ENUMS
# ═══════════════════════════════════════════════════════════════════════════════

class Severity(str, Enum):
    CRITICAL = "critical"
    MAJOR    = "major"
    MINOR    = "minor"
    WARNING  = "warning"
    INFO     = "info"
    UNKNOWN  = "unknown"


class IngestionSource(str, Enum):
    ALERTMANAGER = "alertmanager"
    WEBHOOK      = "webhook"
    SNMP_TRAP    = "snmp_trap"
    SYSLOG       = "syslog"
    MQTT         = "mqtt"
    MANUAL       = "manual"


# ═══════════════════════════════════════════════════════════════════════════════
# MODULE 1 — RAW EVENTS (Ingestion)
# ═══════════════════════════════════════════════════════════════════════════════

class RawEventStatus(str, Enum):
    RECEIVED  = "received"
    VALIDATED = "validated"
    FORWARDED = "forwarded"
    DUPLICATE = "duplicate"
    INVALID   = "invalid"


class RawEvent(Base):
    """Every alert received from any source, stored as-is."""
    __tablename__ = "raw_events"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    source           = Column(SQLEnum(IngestionSource), nullable=False, index=True)
    source_host      = Column(String(255), nullable=True)
    source_id        = Column(String(255), nullable=True, index=True)
    tool_name        = Column(String(100), nullable=True)
    severity         = Column(SQLEnum(Severity), default=Severity.UNKNOWN, index=True)
    title            = Column(String(500), nullable=False)
    message          = Column(Text, nullable=True)
    affected_host    = Column(String(255), nullable=True, index=True)
    affected_service = Column(String(255), nullable=True)
    raw_payload      = Column(JSON, nullable=True)
    snmp_oid         = Column(String(500), nullable=True)
    snmp_community   = Column(String(100), nullable=True)
    syslog_facility  = Column(Integer, nullable=True)
    syslog_priority  = Column(Integer, nullable=True)
    syslog_program   = Column(String(100), nullable=True)
    mqtt_topic       = Column(String(500), nullable=True)
    status           = Column(SQLEnum(RawEventStatus), default=RawEventStatus.RECEIVED, index=True)
    validation_error = Column(Text, nullable=True)
    received_at      = Column(DateTime, default=datetime.utcnow, index=True)
    validated_at     = Column(DateTime, nullable=True)
    forwarded_at     = Column(DateTime, nullable=True)

    # Relations
    enriched_event   = relationship("EnrichedEvent", back_populates="raw_event", uselist=False)


# ═══════════════════════════════════════════════════════════════════════════════
# MODULE 2 — ENRICHED EVENTS
# ═══════════════════════════════════════════════════════════════════════════════

class EnrichedEvent(Base):
    """Raw event + CMDB context + service map + blast radius."""
    __tablename__ = "enriched_events"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    raw_event_id     = Column(Integer, ForeignKey("raw_events.id"), nullable=False, index=True)

    # CMDB lookup results
    ci_id            = Column(String(100), nullable=True)   # Config Item ID
    ci_name          = Column(String(255), nullable=True)
    ci_type          = Column(String(100), nullable=True)   # server, switch, firewall
    ci_owner         = Column(String(255), nullable=True)
    ci_environment   = Column(String(50), nullable=True)    # prod, staging, dev
    ci_location      = Column(String(255), nullable=True)

    # Service map
    business_service = Column(String(255), nullable=True)   # Which business service affected
    service_criticality = Column(String(20), nullable=True) # critical, high, medium, low
    dependent_services  = Column(JSON, nullable=True)       # List of downstream services

    # Impact / blast radius
    blast_radius     = Column(Integer, default=0)           # # of affected services
    impact_score     = Column(Float, default=0.0)           # 0.0 - 10.0
    affected_users   = Column(Integer, default=0)

    # Historical context
    similar_incidents_count = Column(Integer, default=0)
    last_similar_incident   = Column(DateTime, nullable=True)
    known_issue      = Column(Boolean, default=False)
    known_issue_ref  = Column(String(255), nullable=True)

    enriched_at      = Column(DateTime, default=datetime.utcnow)

    # Relations
    raw_event        = relationship("RawEvent", back_populates="enriched_event")
    correlated_event = relationship("CorrelatedEvent", back_populates="enriched_event", uselist=False)


# ═══════════════════════════════════════════════════════════════════════════════
# MODULE 3 — CORRELATED EVENTS
# ═══════════════════════════════════════════════════════════════════════════════

class CorrelationStatus(str, Enum):
    ROOT_CAUSE  = "root_cause"
    SYMPTOM     = "symptom"
    STANDALONE  = "standalone"
    SUPPRESSED  = "suppressed"


class CorrelatedEvent(Base):
    """Result of correlation engine — root cause identified, symptoms grouped."""
    __tablename__ = "correlated_events"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    enriched_event_id   = Column(Integer, ForeignKey("enriched_events.id"), nullable=False, index=True)

    correlation_group   = Column(String(100), nullable=True, index=True)  # Group ID
    correlation_status  = Column(SQLEnum(CorrelationStatus), default=CorrelationStatus.STANDALONE)
    root_cause_event_id = Column(Integer, ForeignKey("correlated_events.id"), nullable=True)
    symptom_count       = Column(Integer, default=0)  # How many events suppressed under this
    confidence_score    = Column(Float, default=1.0)  # ML confidence 0.0 - 1.0
    correlation_rule    = Column(String(255), nullable=True)  # Which rule fired

    correlated_at       = Column(DateTime, default=datetime.utcnow)

    # Relations
    enriched_event      = relationship("EnrichedEvent", back_populates="correlated_event")
    incident            = relationship("Incident", back_populates="correlated_event", uselist=False)


# ═══════════════════════════════════════════════════════════════════════════════
# MODULE 4 — DECISION ENGINE OUTPUT → INCIDENT
# ═══════════════════════════════════════════════════════════════════════════════

class IncidentStatus(str, Enum):
    NEW         = "new"
    ASSIGNED    = "assigned"
    IN_PROGRESS = "in_progress"
    PENDING     = "pending"
    RESOLVED    = "resolved"
    CLOSED      = "closed"

class IncidentPriority(str, Enum):
    CRITICAL = "critical"
    HIGH     = "high"
    MEDIUM   = "medium"
    LOW      = "low"

class DecisionPath(str, Enum):
    TICKET         = "ticket"          # Path A — create ticket
    AUTO_REMEDIATE = "auto_remediate"  # Path B — run remediation
    NOTIFY         = "notify"          # Path C — send notifications
    ESCALATE       = "escalate"        # Path D — escalate


class Incident(Base):
    """
    Central incident record — created by the Decision Engine.
    Links all pipeline stages together.
    """
    __tablename__ = "incidents"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    correlated_event_id = Column(Integer, ForeignKey("correlated_events.id"), nullable=True)

    title               = Column(String(500), nullable=False)
    description         = Column(Text, nullable=True)
    status              = Column(SQLEnum(IncidentStatus), default=IncidentStatus.NEW, index=True)
    priority            = Column(SQLEnum(IncidentPriority), default=IncidentPriority.MEDIUM, index=True)
    source              = Column(String(100), nullable=True)

    # Decision engine output
    decision_path       = Column(SQLEnum(DecisionPath), nullable=True)
    decision_reason     = Column(Text, nullable=True)
    auto_remediate      = Column(Boolean, default=False)
    requires_approval   = Column(Boolean, default=False)

    # Assignment
    assigned_to         = Column(String(100), nullable=True)
    assigned_team       = Column(String(100), nullable=True)
    created_by          = Column(String(100), nullable=True)

    # SLA
    sla_deadline        = Column(DateTime, nullable=True)
    sla_breached        = Column(Boolean, default=False)
    escalated           = Column(Boolean, default=False)
    escalated_at        = Column(DateTime, nullable=True)

    # Resolution
    resolution_notes    = Column(Text, nullable=True)
    root_cause_analysis = Column(Text, nullable=True)

    # Timestamps
    created_at          = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at          = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    resolved_at         = Column(DateTime, nullable=True)
    closed_at           = Column(DateTime, nullable=True)

    # Relations
    correlated_event    = relationship("CorrelatedEvent", back_populates="incident")
    diagnostics         = relationship("DiagnosticRun", back_populates="incident")
    remediation_jobs    = relationship("RemediationJob", back_populates="incident")
    notifications       = relationship("NotificationLog", back_populates="incident")
    audit_logs          = relationship("AuditLog", back_populates="incident")


# ═══════════════════════════════════════════════════════════════════════════════
# MODULE 5 — DIAGNOSTICS
# ═══════════════════════════════════════════════════════════════════════════════

class DiagnosticLevel(str, Enum):
    L1 = "l1"  # Auto: connectivity, service status, log analysis
    L2 = "l2"  # Deep: packet capture, memory dump, TCAM analysis


class DiagnosticStatus(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    SKIPPED   = "skipped"


class DiagnosticRun(Base):
    """Records each diagnostic workflow run against an incident."""
    __tablename__ = "diagnostic_runs"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    incident_id     = Column(Integer, ForeignKey("incidents.id"), nullable=False, index=True)

    level           = Column(SQLEnum(DiagnosticLevel), default=DiagnosticLevel.L1)
    target_host     = Column(String(255), nullable=True)
    target_type     = Column(String(50), nullable=True)  # server, switch, firewall, cisco_aci

    status          = Column(SQLEnum(DiagnosticStatus), default=DiagnosticStatus.PENDING)
    checks_run      = Column(JSON, nullable=True)   # List of check names executed
    findings        = Column(JSON, nullable=True)   # {check: result} dict
    summary         = Column(Text, nullable=True)   # Human-readable diagnosis
    recommended_action = Column(Text, nullable=True)

    started_at      = Column(DateTime, nullable=True)
    completed_at    = Column(DateTime, nullable=True)
    duration_seconds= Column(Float, nullable=True)

    incident        = relationship("Incident", back_populates="diagnostics")


# ═══════════════════════════════════════════════════════════════════════════════
# MODULE 6 — REMEDIATION
# ═══════════════════════════════════════════════════════════════════════════════

class RemediationType(str, Enum):
    ANSIBLE    = "ansible"
    PYTHON_SSH = "python_ssh"
    TERRAFORM  = "terraform"
    MANUAL     = "manual"


class RemediationStatus(str, Enum):
    PENDING           = "pending"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED          = "approved"
    REJECTED          = "rejected"
    RUNNING           = "running"
    VERIFYING         = "verifying"
    SUCCESS           = "success"
    FAILED            = "failed"
    ROLLED_BACK       = "rolled_back"


class RemediationJob(Base):
    """A single remediation attempt on an incident."""
    __tablename__ = "remediation_jobs"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    incident_id     = Column(Integer, ForeignKey("incidents.id"), nullable=False, index=True)

    remediation_type= Column(SQLEnum(RemediationType), nullable=False)
    action          = Column(String(255), nullable=False)  # e.g. "restart_service", "clear_cache"
    target_host     = Column(String(255), nullable=True)
    parameters      = Column(JSON, nullable=True)  # e.g. {"service": "nginx", "port": 80}

    # Execution
    playbook_path   = Column(String(500), nullable=True)   # Ansible playbook
    script_content  = Column(Text, nullable=True)          # Python/SSH script
    terraform_module= Column(String(255), nullable=True)

    status          = Column(SQLEnum(RemediationStatus), default=RemediationStatus.PENDING, index=True)
    attempt_number  = Column(Integer, default=1)
    max_attempts    = Column(Integer, default=3)

    # Approval gate
    requires_approval   = Column(Boolean, default=False)
    approved_by         = Column(String(100), nullable=True)
    approved_at         = Column(DateTime, nullable=True)
    rejection_reason    = Column(Text, nullable=True)

    # Output
    output          = Column(Text, nullable=True)          # stdout/stderr
    error           = Column(Text, nullable=True)
    exit_code       = Column(Integer, nullable=True)

    # Rollback
    rollback_plan   = Column(Text, nullable=True)
    rolled_back     = Column(Boolean, default=False)
    rollback_at     = Column(DateTime, nullable=True)

    # Continuous polling
    verification_checks = Column(JSON, nullable=True)      # What to check after fix
    poll_count      = Column(Integer, default=0)
    last_polled_at  = Column(DateTime, nullable=True)
    next_poll_at    = Column(DateTime, nullable=True)

    started_at      = Column(DateTime, nullable=True)
    completed_at    = Column(DateTime, nullable=True)
    created_at      = Column(DateTime, default=datetime.utcnow)

    incident        = relationship("Incident", back_populates="remediation_jobs")


# ═══════════════════════════════════════════════════════════════════════════════
# MODULE 7 — NOTIFICATIONS
# ═══════════════════════════════════════════════════════════════════════════════

class NotificationChannel(str, Enum):
    SLACK      = "slack"
    TEAMS      = "teams"
    PAGERDUTY  = "pagerduty"
    EMAIL      = "email"
    WEBHOOK    = "webhook"


class NotificationStatus(str, Enum):
    PENDING = "pending"
    SENT    = "sent"
    FAILED  = "failed"


class NotificationLog(Base):
    """Log of every notification sent."""
    __tablename__ = "notification_logs"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=False, index=True)

    channel     = Column(SQLEnum(NotificationChannel), nullable=False)
    recipient   = Column(String(255), nullable=True)  # email / Slack channel / etc
    subject     = Column(String(500), nullable=True)
    body        = Column(Text, nullable=True)
    status      = Column(SQLEnum(NotificationStatus), default=NotificationStatus.PENDING)
    error       = Column(Text, nullable=True)

    sent_at     = Column(DateTime, nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow)

    incident    = relationship("Incident", back_populates="notifications")


# ═══════════════════════════════════════════════════════════════════════════════
# CMDB — Configuration Items (used by Module 2)
# ═══════════════════════════════════════════════════════════════════════════════

class ConfigItem(Base):
    """CMDB — inventory of all monitored hosts and services."""
    __tablename__ = "config_items"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    ci_id           = Column(String(100), unique=True, nullable=False, index=True)
    hostname        = Column(String(255), nullable=False, index=True)
    ip_address      = Column(String(45), nullable=True)
    ci_type         = Column(String(100), nullable=True)   # server, switch, firewall, vm
    os              = Column(String(100), nullable=True)
    environment     = Column(String(50), nullable=True)    # prod, staging, dev
    location        = Column(String(255), nullable=True)
    owner           = Column(String(255), nullable=True)
    team            = Column(String(100), nullable=True)
    business_service= Column(String(255), nullable=True)
    criticality     = Column(String(20), nullable=True)
    dependent_on    = Column(JSON, nullable=True)   # list of ci_ids this depends on
    supports        = Column(JSON, nullable=True)   # list of ci_ids that depend on this
    tags            = Column(JSON, nullable=True)
    ssh_user        = Column(String(100), nullable=True)   # for remediation
    ssh_key_path    = Column(String(500), nullable=True)
    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ═══════════════════════════════════════════════════════════════════════════════
# AUDIT LOG — Full traceability
# ═══════════════════════════════════════════════════════════════════════════════

class AuditLog(Base):
    """Every state change logged for compliance and feedback loop."""
    __tablename__ = "audit_logs"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=True, index=True)
    entity_type = Column(String(50), nullable=True)   # incident, remediation, diagnostic
    entity_id   = Column(Integer, nullable=True)
    action      = Column(String(100), nullable=False)  # created, status_changed, approved, etc
    old_value   = Column(Text, nullable=True)
    new_value   = Column(Text, nullable=True)
    actor       = Column(String(100), nullable=True)   # user or "system"
    note        = Column(Text, nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow, index=True)

    incident    = relationship("Incident", back_populates="audit_logs")


# ═══════════════════════════════════════════════════════════════════════════════
# USERS — Authentication
# ═══════════════════════════════════════════════════════════════════════════════

class User(Base):
    __tablename__ = "users"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    username        = Column(String(100), unique=True, nullable=False)
    email           = Column(String(255), unique=True, nullable=True)
    hashed_password = Column(String(255), nullable=False)
    full_name       = Column(String(255), nullable=True)
    role            = Column(String(50), default="operator")  # admin, operator, viewer
    is_active       = Column(Boolean, default=True)
    created_at      = Column(DateTime, default=datetime.utcnow)
