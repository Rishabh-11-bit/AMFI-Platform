"""
AMFI v4 — Procedure Library
Hardcoded step sequences per fault category.
Each procedure is a list of step descriptors.

Step fields:
  name        : human-readable label
  step_type   : ping | diagnostic | ai_interpret | action | verify
  fn          : coroutine name in executor
  args        : extra kwargs passed to the function
  required    : if True, abort procedure on failure
  risk        : low | medium | high  (high → needs approval)
"""

from typing import Any

# Each procedure is a list of step dicts.
# The executor resolves `fn` to actual coroutines at runtime.

PROCEDURES: dict[str, list[dict[str, Any]]] = {

    # ── Disk Full ────────────────────────────────────────────────────────────
    "disk_full": [
        {"name": "Ping host",           "step_type": "ping",         "fn": "ping",              "risk": "low", "required": True},
        {"name": "Check disk usage",    "step_type": "diagnostic",   "fn": "check_disk",        "risk": "low"},
        {"name": "AI: interpret disk",  "step_type": "ai_interpret", "fn": "ai_interpret",      "risk": "low"},
        {"name": "Clear old log files", "step_type": "action",       "fn": "clear_old_logs",    "risk": "low"},
        {"name": "Clear /tmp files",    "step_type": "action",       "fn": "clear_tmp_files",   "risk": "low"},
        {"name": "Verify disk dropped", "step_type": "verify",       "fn": "verify_disk",       "risk": "low"},
    ],

    # ── High CPU ─────────────────────────────────────────────────────────────
    "high_cpu": [
        {"name": "Ping host",               "step_type": "ping",         "fn": "ping",              "risk": "low", "required": True},
        {"name": "Check CPU usage",         "step_type": "diagnostic",   "fn": "check_cpu",         "risk": "low"},
        {"name": "Check top processes",     "step_type": "diagnostic",   "fn": "check_processes",   "risk": "low"},
        {"name": "AI: interpret CPU",       "step_type": "ai_interpret", "fn": "ai_interpret",      "risk": "low"},
        {"name": "Kill top CPU process",    "step_type": "action",       "fn": "kill_top_process",  "risk": "medium"},
        {"name": "Verify CPU normal",       "step_type": "verify",       "fn": "verify_cpu",        "risk": "low"},
    ],

    # ── High Memory ──────────────────────────────────────────────────────────
    "high_memory": [
        {"name": "Ping host",              "step_type": "ping",         "fn": "ping",               "risk": "low", "required": True},
        {"name": "Check memory",           "step_type": "diagnostic",   "fn": "check_memory",       "risk": "low"},
        {"name": "Check top processes",    "step_type": "diagnostic",   "fn": "check_processes",    "risk": "low"},
        {"name": "AI: interpret memory",   "step_type": "ai_interpret", "fn": "ai_interpret",       "risk": "low"},
        {"name": "Clear memory cache",     "step_type": "action",       "fn": "clear_memory_cache", "risk": "low"},
        {"name": "Verify memory normal",   "step_type": "verify",       "fn": "verify_memory",      "risk": "low"},
    ],

    # ── Service Down ─────────────────────────────────────────────────────────
    "service_down": [
        {"name": "Ping host",               "step_type": "ping",         "fn": "ping",              "risk": "low", "required": True},
        {"name": "Check service status",    "step_type": "diagnostic",   "fn": "check_service",     "risk": "low"},
        {"name": "Check service logs",      "step_type": "diagnostic",   "fn": "check_service_logs","risk": "low"},
        {"name": "AI: interpret service",   "step_type": "ai_interpret", "fn": "ai_interpret",      "risk": "low"},
        {"name": "Check disk space",        "step_type": "diagnostic",   "fn": "check_disk",        "risk": "low"},
        {"name": "Clear disk if needed",    "step_type": "action",       "fn": "clear_old_logs",    "risk": "low"},
        {"name": "Restart service",         "step_type": "action",       "fn": "restart_service",   "risk": "low"},
        {"name": "Verify service running",  "step_type": "verify",       "fn": "verify_service",    "risk": "low"},
    ],

    # ── Network Down ─────────────────────────────────────────────────────────
    "network_down": [
        {"name": "Ping host",                 "step_type": "ping",         "fn": "ping",                    "risk": "low", "required": True},
        {"name": "Check network interfaces",  "step_type": "diagnostic",   "fn": "check_network_interfaces","risk": "low"},
        {"name": "AI: interpret network",     "step_type": "ai_interpret", "fn": "ai_interpret",            "risk": "low"},
        {"name": "Escalate: host unreachable","step_type": "action",       "fn": "escalate_l3",             "risk": "low"},
    ],

    # ── Database Issue ────────────────────────────────────────────────────────
    "database_issue": [
        {"name": "Ping host",               "step_type": "ping",         "fn": "ping",              "risk": "low", "required": True},
        {"name": "Check DB service",        "step_type": "diagnostic",   "fn": "check_db_service",  "risk": "low"},
        {"name": "Check service logs",      "step_type": "diagnostic",   "fn": "check_service_logs","risk": "low"},
        {"name": "Check disk space",        "step_type": "diagnostic",   "fn": "check_disk",        "risk": "low"},
        {"name": "AI: interpret DB",        "step_type": "ai_interpret", "fn": "ai_interpret",      "risk": "low"},
        {"name": "Clear disk if needed",    "step_type": "action",       "fn": "clear_old_logs",    "risk": "low"},
        {"name": "Restart DB service",      "step_type": "action",       "fn": "restart_db_service","risk": "medium"},
        {"name": "Verify DB running",       "step_type": "verify",       "fn": "verify_service",    "risk": "low"},
    ],

    # ── High Latency ─────────────────────────────────────────────────────────
    "high_latency": [
        {"name": "Ping host",              "step_type": "ping",         "fn": "ping",             "risk": "low", "required": True},
        {"name": "Check CPU",              "step_type": "diagnostic",   "fn": "check_cpu",        "risk": "low"},
        {"name": "Check memory",           "step_type": "diagnostic",   "fn": "check_memory",     "risk": "low"},
        {"name": "Check disk",             "step_type": "diagnostic",   "fn": "check_disk",       "risk": "low"},
        {"name": "AI: interpret latency",  "step_type": "ai_interpret", "fn": "ai_interpret",     "risk": "low"},
    ],

    # ── Default (unknown / unmatched) ─────────────────────────────────────────
    "unknown": [
        {"name": "Ping host",             "step_type": "ping",         "fn": "ping",         "risk": "low"},
        {"name": "Check disk",            "step_type": "diagnostic",   "fn": "check_disk",   "risk": "low"},
        {"name": "Check CPU",             "step_type": "diagnostic",   "fn": "check_cpu",    "risk": "low"},
        {"name": "Check memory",          "step_type": "diagnostic",   "fn": "check_memory", "risk": "low"},
        {"name": "AI: general interpret", "step_type": "ai_interpret", "fn": "ai_interpret", "risk": "low"},
    ],
}


def get_procedure(fault_category: str) -> list[dict]:
    """Return the procedure steps for *fault_category* (falls back to 'unknown')."""
    return PROCEDURES.get(fault_category, PROCEDURES["unknown"])
