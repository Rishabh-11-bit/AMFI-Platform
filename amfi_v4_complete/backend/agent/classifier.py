"""
AMFI v4 — Fault Classifier
Pure regex pattern matching on alert title + description.
No AI involved — deterministic and fast.
"""
import re
import logging
from backend.models.models import FaultCategory, Priority

logger = logging.getLogger("amfi.classifier")

# ── Fault category patterns (ordered — first match wins) ──────────────────────

_PATTERNS: list[tuple[FaultCategory, list[str]]] = [
    (FaultCategory.DISK_FULL, [
        r"disk.*(full|usage|critical|alert)",
        r"no\s+space\s+left",
        r"filesystem.*(full|100%)",
        r"inode.*(exhausted|full)",
        r"storage.*(full|critical)",
        r"disk\s*usage\s*[>≥]\s*\d{2,3}\s*%",
        r"\d{2,3}\s*%\s*(disk|storage|volume)",
        r"/(var|tmp|opt|data|home|log)\s+\d{2,3}%",
        r"out\s+of\s+disk",
    ]),
    (FaultCategory.HIGH_CPU, [
        r"(high|critical)\s+cpu",
        r"cpu\s+(high|critical|alert|overload|spike)",
        r"cpu\s*usage\s*[>≥]\s*\d{2,3}\s*%",
        r"\d{2,3}\s*%\s*cpu",
        r"load\s+average\s+(high|critical|\d)",
        r"cpu\s+load\s+(high|critical)",
        r"processor\s+(high|overload)",
        r"(100|9[0-9])\s*%\s*(cpu|processor)",
    ]),
    (FaultCategory.HIGH_MEMORY, [
        r"(high|critical)\s+(memory|ram|mem)",
        r"(memory|ram|mem)\s+(high|critical|alert|exhausted|full|usage)",
        r"(memory|ram)\s*usage\s*[>≥]?\s*(at\s+)?\d{2,3}\s*%",
        r"\d{2,3}\s*%\s*(memory|ram|mem)",
        r"out\s+of\s+memory",
        r"\boom\b",
        r"swap\s+(high|full|critical|in\s+use)",
        r"memory\s+pressure",
        r"(memory|mem)\s+\S+\s+\d{2,3}\s*%",
    ]),
    # DATABASE first — so "mysql service failed" hits DB, not service_down
    (FaultCategory.DATABASE_ISSUE, [
        r"(database|db)\s+(down|error|failed|unavailable|crash|connection)",
        r"(mysql|postgres|postgresql|mariadb|oracle|mssql|mongodb|cassandra|couchdb)\s+(down|error|failed|unavailable|stopped|connection)",
        r"(db|database)\s+(connection|query)\s+(failed|error|timeout)",
        r"replication\s+(lag|failed|error)",
        r"deadlock",
        r"table\s+(locked|full)",
        r"query\s+(timeout|failed)",
        r"(mysql|postgres|postgresql|mariadb|oracle|mssql|mongodb)\s+service\s+(failed|down|stopped)",
    ]),
    # APPLICATION_ERROR before SERVICE_DOWN — so "application crash loop" → app_error not service_down
    (FaultCategory.APPLICATION_ERROR, [
        r"(application|app)\s+(error|crash|exception|fault)",
        r"crash\s+(loop|report|detected)",
        r"exception.*error",
        r"(5[0-9]{2})\s+(error|response)",
        r"http\s+5[0-9]{2}",
        r"(error\s+rate|failure\s+rate)\s+(high|elevated)",
        r"(deployment|release)\s+(failed|error)",
        r"exit\s+code\s+[1-9]",
        r"(app|application)\s+restart(ing|ed|s)?",
    ]),
    (FaultCategory.SERVICE_DOWN, [
        r"service\s+(down|stopped|failed|unavailable|not\s+running)",
        r"(down|stopped|failed|crashed)\s+service",
        r"process\s+(down|stopped|failed)",
        r"(nginx|apache|httpd|redis|rabbitmq|kafka|elasticsearch|mongodb)\s+(down|failed|stopped|unavailable)",
        r"application\s+(down|unavailable)",
        r"web\s+(server|app)\s+down",
        r"unit\s+.*\s+(failed|inactive|dead)",
        r"\S+\s+service\s+(is\s+)?(down|stopped|not\s+running)",
        r"(stopped|failed)\s+unexpectedly",
    ]),
    (FaultCategory.NETWORK_DOWN, [
        r"(host|node|server)\s+(unreachable|down|not\s+responding|offline)",
        r"ping\s+(failed|timeout|unreachable)",
        r"network\s+(down|unreachable|disconnected|outage)",
        r"interface\s+\S*\s*(down|disconnected)",
        r"(connection|connectivity)\s+(lost|down|failed|timeout)",
        r"(link|port)\s+down",
        r"switch\s+(down|offline)",
        r"firewall\s+(down|block)",
        r"dns\s+(failure|timeout|down)",
        r"network\s+interface.*down",
    ]),
    (FaultCategory.HIGH_LATENCY, [
        r"(high|slow|elevated)\s+(latency|response\s+time)",
        r"latency\s+(high|elevated|spike|critical)",
        r"response\s+time\s+(high|slow|degraded)",
        r"timeout\s+(high|frequent)",
        r"slow\s+(query|request|api|response)",
        r"(api|endpoint)\s+slow",
        r"p9[05]\s+latency",
        r"p99\s*(>|above|over)",
    ]),
    (FaultCategory.SECURITY_ALERT, [
        r"(security|intrusion|breach|attack|exploit)",
        r"(brute\s+force|ddos|dos\s+attack|sql\s+injection|xss)",
        r"unauthorized\s+(access|login|attempt)",
        r"suspicious\s+(activity|login|traffic)",
        r"(firewall|ids|ips)\s+(alert|block|detect)",
        r"malware|ransomware|rootkit",
        r"failed\s+login\s+attempt",
    ]),
    (FaultCategory.HARDWARE_FAILURE, [
        r"(hardware|psu|fan)\s+(fail|error|fault|critical|warn)",
        r"raid\s+(degraded|failed|array)",
        r"(drive|disk)\s+(fail|bad|error|degraded)",
        r"(cpu|memory)\s+(fail|fault|hardware\s+error)",
        r"(temperature|thermal)\s+(high|critical|alert)",
        r"hardware\s+error",
        r"(hdd|ssd)\s+(fail|warn)",
        r"(disk|drive|storage)\s+(hardware|physical)\s+(error|fail)",
        r"physical\s+(disk|drive)\s+(fail|error)",
    ]),
]

# ── Priority determination ─────────────────────────────────────────────────────

_PRIORITY_PATTERNS: list[tuple[Priority, list[str]]] = [
    (Priority.P1, [
        r"(production|prod)\s*(down|outage|fail)",
        r"(critical|p1|sev1|severity\s*1)",
        r"(outage|down)\s*(affecting|impact)",
        r"(complete|total)\s+(outage|failure)",
        r"(payment|checkout|login|auth)\s+(down|fail)",
    ]),
    (Priority.P2, [
        r"(high|p2|sev2|severity\s*2)",
        r"(major|significant)\s+(degradation|impact)",
        r"(partial|intermittent)\s+(outage|failure)",
        r"(slow|degraded)\s+(significantly|severely)",
    ]),
    (Priority.P3, [
        r"(warning|warn|p3|sev3|medium|moderate)",
        r"(minor|partial)\s+(degradation|impact)",
        r"(non-critical|non\s+critical)",
    ]),
    (Priority.P4, [
        r"(low|p4|sev4|info|informational|minor)",
        r"(no\s+user\s+impact)",
    ]),
]

# Default priority per fault category
_CATEGORY_DEFAULT_PRIORITY: dict[FaultCategory, Priority] = {
    FaultCategory.DISK_FULL:          Priority.P2,
    FaultCategory.HIGH_CPU:           Priority.P2,
    FaultCategory.HIGH_MEMORY:        Priority.P2,
    FaultCategory.SERVICE_DOWN:       Priority.P1,
    FaultCategory.NETWORK_DOWN:       Priority.P1,
    FaultCategory.HIGH_LATENCY:       Priority.P3,
    FaultCategory.DATABASE_ISSUE:     Priority.P1,
    FaultCategory.SECURITY_ALERT:     Priority.P1,
    FaultCategory.HARDWARE_FAILURE:   Priority.P2,
    FaultCategory.APPLICATION_ERROR:  Priority.P2,
    FaultCategory.UNKNOWN:            Priority.P3,
}


def classify(title: str, description: str = "") -> tuple[FaultCategory, Priority]:
    """
    Returns (fault_category, priority) for an alert.
    Uses pure regex — no AI, fully deterministic.
    """
    text = f"{title} {description}".lower()

    # Fault category — first match wins
    category = FaultCategory.UNKNOWN
    for cat, patterns in _PATTERNS:
        for pat in patterns:
            if re.search(pat, text):
                category = cat
                break
        if category != FaultCategory.UNKNOWN:
            break

    # Priority — explicit keyword first, then category default
    priority = _CATEGORY_DEFAULT_PRIORITY.get(category, Priority.P3)
    for prio, patterns in _PRIORITY_PATTERNS:
        for pat in patterns:
            if re.search(pat, text):
                priority = prio
                break
        else:
            continue
        break

    logger.debug("classify('%s') → %s / %s", title[:60], category.value, priority.value)
    return category, priority
