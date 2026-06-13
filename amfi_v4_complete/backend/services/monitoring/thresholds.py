"""
AMFI v4 — Threshold Evaluator
Checks metric samples against ThresholdRules and creates incidents on breach.
Respects per-rule cooldown windows to prevent alert storms.
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("amfi.monitoring.thresholds")

# Metric → human-readable unit for incident title
_UNITS = {
    "cpu_percent":  "%",
    "ram_percent":  "%",
    "disk_percent": "%",
    "load_1m":      "",
    "ping_ms":      "ms",
    "ping_up":      "",
    "net_rx_bps":   "bps",
    "net_tx_bps":   "bps",
    "if_up_pct":    "%",
}

_OPERATORS = {
    "gt":  lambda v, t: v >  t,
    "gte": lambda v, t: v >= t,
    "lt":  lambda v, t: v <  t,
    "lte": lambda v, t: v <= t,
    "eq":  lambda v, t: abs(v - t) < 0.001,
}


async def evaluate_metrics(
    db:      AsyncSession,
    host,                   # MonitoredHost ORM object
    metrics: dict,          # {metric_name: float_value}
) -> list[int]:
    """
    Evaluate all enabled ThresholdRules against the freshly-collected metrics.
    Creates incidents for any breaches not currently in cooldown.
    Returns list of created incident IDs.
    """
    from backend.models.models import ThresholdRule, Incident, SLAPolicy
    from backend.services.nms.connectors import _create_incident

    if not metrics:
        return []

    # Load rules that apply to this host (host-specific OR global)
    r = await db.execute(
        select(ThresholdRule).where(
            ThresholdRule.enabled == True,
            (ThresholdRule.host_id == host.id) | (ThresholdRule.host_id == None),
        )
    )
    rules = r.scalars().all()

    created_ids = []

    for rule in rules:
        value = metrics.get(rule.metric)
        if value is None:
            continue

        # Check device_type filter
        if rule.device_type and rule.device_type != host.device_type:
            continue

        # Evaluate operator
        op_fn = _OPERATORS.get(rule.operator)
        if not op_fn:
            continue
        if not op_fn(value, rule.threshold):
            continue

        # ── Breach detected ───────────────────────────────────────────────────
        # Check cooldown — is there already an open/recent incident for this host+fault?
        cooldown_since = datetime.utcnow() - timedelta(minutes=rule.cooldown_minutes)
        existing_r = await db.execute(
            select(func.count(Incident.id)).where(
                Incident.affected_host   == host.hostname,
                Incident.fault_category  == rule.fault_category,
                Incident.status.not_in(["resolved", "closed", "false_positive"]),
                Incident.created_at      >= cooldown_since,
            )
        )
        if (existing_r.scalar() or 0) > 0:
            logger.debug(
                "Rule '%s' breached on %s but in cooldown — skipping",
                rule.name, host.hostname,
            )
            continue

        # Build a human-readable title
        unit        = _UNITS.get(rule.metric, "")
        metric_disp = rule.metric.replace("_", " ").title()
        if rule.metric == "ping_up":
            title = f"Host unreachable: {host.hostname}"
        else:
            title = (
                f"{metric_disp} alert on {host.display_name or host.hostname}: "
                f"{value:.1f}{unit} (threshold {rule.threshold:.1f}{unit})"
            )

        inc = await _create_incident(
            db,
            title          = title,
            description    = (
                f"Monitoring rule '{rule.name}' triggered: "
                f"{rule.metric} = {value:.2f} {rule.operator} {rule.threshold} "
                f"on host {host.hostname} ({host.ip_address})."
            ),
            host           = host.hostname,
            service        = "",
            source         = "amfi_monitoring",
            source_id      = f"mon-{host.id}-{rule.id}-{int(datetime.utcnow().timestamp())}",
            raw_alert      = {"metric": rule.metric, "value": value, "threshold": rule.threshold,
                              "rule": rule.name, "host_id": host.id},
            priority       = rule.priority,
            fault_category = rule.fault_category,
        )
        if inc:
            created_ids.append(inc.id)
            logger.info(
                "Incident %s created — rule '%s' breached on %s (%.2f %s %.2f)",
                inc.number, rule.name, host.hostname, value, rule.operator, rule.threshold,
            )

    return created_ids


# ── Default threshold rules seeded on first run ────────────────────────────────

DEFAULT_RULES = [
    # CPU
    dict(name="CPU Warning",   metric="cpu_percent",  operator="gt", threshold=80.0,
         priority="p3", fault_category="high_cpu",      cooldown_minutes=30),
    dict(name="CPU Critical",  metric="cpu_percent",  operator="gt", threshold=95.0,
         priority="p1", fault_category="high_cpu",      cooldown_minutes=15),

    # Memory
    dict(name="RAM Warning",   metric="ram_percent",  operator="gt", threshold=85.0,
         priority="p2", fault_category="high_memory",   cooldown_minutes=30),
    dict(name="RAM Critical",  metric="ram_percent",  operator="gt", threshold=95.0,
         priority="p1", fault_category="high_memory",   cooldown_minutes=15),

    # Disk
    dict(name="Disk Warning",  metric="disk_percent", operator="gt", threshold=80.0,
         priority="p3", fault_category="disk_full",     cooldown_minutes=60),
    dict(name="Disk Critical", metric="disk_percent", operator="gt", threshold=92.0,
         priority="p2", fault_category="disk_full",     cooldown_minutes=20),

    # Host reachability
    dict(name="Host Down",     metric="ping_up",      operator="lt", threshold=1.0,
         priority="p1", fault_category="network_down", cooldown_minutes=10),

    # Latency
    dict(name="High Latency",  metric="ping_ms",      operator="gt", threshold=500.0,
         priority="p3", fault_category="high_latency", cooldown_minutes=30),

    # Load average
    dict(name="High Load",     metric="load_1m",      operator="gt", threshold=4.0,
         priority="p3", fault_category="high_cpu",      cooldown_minutes=30),
    dict(name="Critical Load", metric="load_1m",      operator="gt", threshold=10.0,
         priority="p2", fault_category="high_cpu",      cooldown_minutes=15),

    # Network interfaces (SNMP)
    dict(name="Interfaces Down", metric="if_up_pct",  operator="lt", threshold=80.0,
         device_type="network",
         priority="p2", fault_category="network_down", cooldown_minutes=20),
]


async def seed_default_rules(db: AsyncSession) -> None:
    """Insert default threshold rules if none exist yet."""
    from backend.models.models import ThresholdRule
    from sqlalchemy import func as _func

    count_r = await db.execute(select(_func.count(ThresholdRule.id)))
    if (count_r.scalar() or 0) > 0:
        return   # already seeded

    for rule_data in DEFAULT_RULES:
        db.add(ThresholdRule(**rule_data))

    await db.commit()
    logger.info("Seeded %d default threshold rules", len(DEFAULT_RULES))
