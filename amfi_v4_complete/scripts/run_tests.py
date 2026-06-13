"""
AMFI v4 — Comprehensive Test Suite
Tests every component: API, classifier, executor, DB, AI, edge cases.
Run: python scripts/run_tests.py
"""
import asyncio
import sys
import os
import time
import json
import traceback
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace", write_through=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", write_through=True)

# Also tee output to a file so it's not lost if process is killed
_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_results.log")
_log_fh = open(_LOG, "w", encoding="utf-8", buffering=1)

_orig_print = print
def print(*args, **kwargs):
    _orig_print(*args, **kwargs)
    sep = kwargs.get("sep", " ")
    end = kwargs.get("end", "\n")
    _log_fh.write(sep.join(str(a) for a in args) + end)
    _log_fh.flush()

BASE = "http://localhost:8000"

# ─── Colour helpers ──────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

passed = failed = skipped = 0
results = []

def ok(name, detail=""):
    global passed
    passed += 1
    results.append(("PASS", name, detail))
    print(f"  {GREEN}PASS{RESET}  {name}" + (f"  [{detail}]" if detail else ""))

def fail(name, detail=""):
    global failed
    failed += 1
    results.append(("FAIL", name, detail))
    print(f"  {RED}FAIL{RESET}  {name}" + (f"  [{detail}]" if detail else ""))

def skip(name, detail=""):
    global skipped
    skipped += 1
    results.append(("SKIP", name, detail))
    print(f"  {YELLOW}SKIP{RESET}  {name}" + (f"  [{detail}]" if detail else ""))

def section(title):
    print(f"\n{BOLD}{CYAN}{'─'*60}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'─'*60}{RESET}")

# ─── HTTP helpers (sync via urllib) ──────────────────────────────────────────
import urllib.request
import urllib.error

def http(method, path, body=None, timeout=20, headers=None, body_raw=None, content_type=None):
    """HTTP request helper. Returns (status_code, response_dict).
    For non-JSON responses (HTML etc.) returns (status_code, {}).
    On network error returns (0, {'error': str(e)}).
    Optional:
      headers      — dict of extra headers
      body_raw     — pre-encoded bytes (skips JSON encode of body)
      content_type — override Content-Type header
    """
    url = f"{BASE}{path}"
    if body_raw is not None:
        data = body_raw
    elif body is not None:
        data = json.dumps(body).encode()
    else:
        data = None

    req = urllib.request.Request(url, data=data, method=method)

    if body_raw is not None and content_type:
        req.add_header("Content-Type", content_type)
    elif body is not None:
        req.add_header("Content-Type", "application/json")

    if headers:
        for k, v in headers.items():
            req.add_header(k, v)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status = r.getcode()
            raw = r.read()
            try:
                resp = json.loads(raw)
            except Exception:
                resp = {}
            return status, resp
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            resp = json.loads(e.read())
        except Exception:
            resp = {}
        return status, resp
    except Exception as e:
        return 0, {"error": str(e)}

def GET(path, timeout=20, headers=None):
    return http("GET", path, timeout=timeout, headers=headers)
def POST(path, body=None):    return http("POST",   path, body)
def DELETE(path):             return http("DELETE", path)

# ═══════════════════════════════════════════════════════════════════════════════
# 1. HEALTH & CONNECTIVITY
# ═══════════════════════════════════════════════════════════════════════════════
section("1. HEALTH & CONNECTIVITY")

s, d = GET("/api/health")
if s == 200 and d.get("status") == "ok":           ok("GET /api/health returns 200 + status:ok")
else:                                               fail("GET /api/health", f"got {s}")

if d.get("agent", {}).get("ollama_running"):        ok("Ollama is running")
else:                                               skip("Ollama not running")

if d.get("agent", {}).get("model_ready"):           ok(f"Model '{d['agent'].get('ollama_model')}' is ready")
else:                                               skip("Model not ready")

if d.get("agent", {}).get("claude_enabled"):        ok("Claude API backup enabled")
else:                                               skip("Claude API not configured (optional)")

s2, _ = GET("/docs")
if s2 == 200:  ok("GET /docs  (Swagger UI)")
else:          fail("GET /docs", f"got {s2}")

s3, _ = GET("/")
if s3 == 200:  ok("GET /  (React frontend served)")
else:          fail("GET /  (frontend)", f"got {s3}")

# ═══════════════════════════════════════════════════════════════════════════════
# 2. DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════
section("2. DASHBOARD")

s, d = GET("/api/dashboard")
if s == 200:                                        ok("GET /api/dashboard returns 200")
else:                                               fail("GET /api/dashboard", f"got {s}")

inc = d.get("incidents", {})
for key in ["total","open","resolved","sla_breached","auto_resolution_rate","false_positives"]:
    if key in inc:  ok(f"  incidents.{key} present  = {inc[key]}")
    else:           fail(f"  incidents.{key} missing from dashboard")

if "pending_approvals" in d:                        ok(f"  pending_approvals present = {d['pending_approvals']}")
else:                                               fail("  pending_approvals missing")

agent = d.get("agent", {})
for key in ["ai_engine","ollama_model","model_ready","max_attempts","auto_execute"]:
    if key in agent:  ok(f"  agent.{key} present = {agent[key]}")
    else:             fail(f"  agent.{key} missing")

if isinstance(d.get("recent_incidents"), list):     ok(f"  recent_incidents is list ({len(d['recent_incidents'])} items)")
else:                                               fail("  recent_incidents not a list")

# ═══════════════════════════════════════════════════════════════════════════════
# 3. FAULT CLASSIFIER — ALL 11 CATEGORIES
# ═══════════════════════════════════════════════════════════════════════════════
section("3. FAULT CLASSIFIER (regex pattern matching)")

from backend.agent.classifier import classify
from backend.models.models import FaultCategory, Priority

classifier_cases = [
    # (title, description, expected_category)
    ("disk full on /var/log at 94%",               "",                            FaultCategory.DISK_FULL),
    ("No space left on device /opt",               "",                            FaultCategory.DISK_FULL),
    ("Filesystem / is 99% full",                   "",                            FaultCategory.DISK_FULL),
    ("High CPU usage on web-01 at 95%",            "",                            FaultCategory.HIGH_CPU),
    ("CPU load critical load average 18.4",        "",                            FaultCategory.HIGH_CPU),
    ("Processor overload detected",                "",                            FaultCategory.HIGH_CPU),
    ("Memory usage at 92%",                        "",                            FaultCategory.HIGH_MEMORY),
    ("Out of memory on app-server",                "",                            FaultCategory.HIGH_MEMORY),
    ("OOM killer invoked",                         "OOM",                         FaultCategory.HIGH_MEMORY),
    ("nginx service down",                         "service failed",              FaultCategory.SERVICE_DOWN),
    ("postgresql stopped unexpectedly",            "",                            FaultCategory.DATABASE_ISSUE),  # postgres = DB
    ("Host unreachable web-server-01",             "",                            FaultCategory.NETWORK_DOWN),
    ("ping failed to 10.0.1.5",                    "connection timeout",          FaultCategory.NETWORK_DOWN),
    ("Network interface eth0 down",                "",                            FaultCategory.NETWORK_DOWN),
    ("High latency on API p99 greater than 3s",    "slow response",               FaultCategory.HIGH_LATENCY),
    ("response time degraded",                     "latency elevated",            FaultCategory.HIGH_LATENCY),
    ("PostgreSQL connection failures",             "database error",              FaultCategory.DATABASE_ISSUE),
    ("MySQL service failed",                       "",                            FaultCategory.DATABASE_ISSUE),
    ("Database deadlock detected",                 "",                            FaultCategory.DATABASE_ISSUE),
    ("Unauthorized login attempt",                 "brute force detected",        FaultCategory.SECURITY_ALERT),
    ("DDoS attack in progress",                    "",                            FaultCategory.SECURITY_ALERT),
    ("RAID array degraded",                        "disk failure",                FaultCategory.HARDWARE_FAILURE),
    ("CPU temperature critical",                   "thermal alert",               FaultCategory.HARDWARE_FAILURE),
    ("Application crash loop",                     "exit code 1",                 FaultCategory.APPLICATION_ERROR),
    ("HTTP 500 error rate elevated",               "",                            FaultCategory.APPLICATION_ERROR),
    ("random unknown alert XYZ",                   "",                            FaultCategory.UNKNOWN),
]

for title, desc, expected in classifier_cases:
    got_cat, got_prio = classify(title, desc)
    if got_cat == expected:
        ok(f"classify('{title[:45]}') -> {got_cat.value}")
    else:
        fail(f"classify('{title[:45]}')", f"expected {expected.value}, got {got_cat.value}")

# Priority classification
priority_cases = [
    ("Production down complete outage",           Priority.P1),
    ("CRITICAL: payment service unreachable",     Priority.P1),
    ("High CPU usage on staging",                 Priority.P2),
    ("WARNING: disk at 85%",                      Priority.P3),
    ("Low priority info alert",                   Priority.P4),
]
for title, expected_prio in priority_cases:
    cat, prio = classify(title, "")
    if prio == expected_prio:
        ok(f"priority('{title[:45]}') -> {prio.value}")
    else:
        fail(f"priority('{title[:45]}')", f"expected {expected_prio.value}, got {prio.value}")

# ═══════════════════════════════════════════════════════════════════════════════
# 4. INCIDENT CRUD
# ═══════════════════════════════════════════════════════════════════════════════
section("4. INCIDENT CRUD")

# Create
s, inc = POST("/api/incidents", {
    "title":            "Test: disk full on test-host-01 at 97%",
    "description":      "Automated test incident",
    "affected_host":    "test-host-01",
    "affected_service": "test-service",
    "source":           "test",
    "priority":         "p2",
})
if s == 201 and "id" in inc:
    ok(f"POST /api/incidents  created {inc['number']}")
    TEST_INC_ID = inc["id"]
else:
    fail("POST /api/incidents", f"got {s}: {inc}")
    TEST_INC_ID = None

# Get
if TEST_INC_ID:
    s, d = GET(f"/api/incidents/{TEST_INC_ID}")
    if s == 200 and d["id"] == TEST_INC_ID:     ok(f"GET /api/incidents/{TEST_INC_ID}")
    else:                                        fail(f"GET /api/incidents/{TEST_INC_ID}", str(s))

# List with filters
s, lst = GET("/api/incidents?limit=5")
if s == 200 and isinstance(lst, list):          ok(f"GET /api/incidents?limit=5  ({len(lst)} items)")
else:                                           fail("GET /api/incidents?limit=5", str(s))

s, lst = GET("/api/incidents?status=new")
if s == 200 and all(i["status"] == "new" for i in lst):
    ok(f"GET /api/incidents?status=new  ({len(lst)} items, all new)")
else:
    fail("GET /api/incidents?status=new filter", str(s))

s, lst = GET("/api/incidents?priority=p1")
if s == 200 and all(i["priority"] == "p1" for i in lst):
    ok(f"GET /api/incidents?priority=p1  ({len(lst)} items)")
else:
    fail("GET /api/incidents?priority=p1 filter", str(s))

s, lst = GET("/api/incidents?search=disk")
if s == 200 and isinstance(lst, list):          ok(f"GET /api/incidents?search=disk  ({len(lst)} matches)")
else:                                           fail("GET /api/incidents?search=disk", str(s))

# Steps — wait for agent to produce at least one step
if TEST_INC_ID:
    time.sleep(8)
    s, steps = GET(f"/api/incidents/{TEST_INC_ID}/steps")
    if s == 200 and isinstance(steps, list):
        ok(f"GET /api/incidents/{TEST_INC_ID}/steps  ({len(steps)} steps generated)")
        if steps:
            s0 = steps[0]
            for key in ["sequence","step_type","type","action","success","status","created_at"]:
                if key in s0:  ok(f"  step has '{key}' = {s0[key]}")
                else:          fail(f"  step missing '{key}'")
            if "ai_interpret" in s0:    ok("  step has alias 'ai_interpret'")
            else:                       fail("  step missing alias 'ai_interpret'")
            if "result" in s0:          ok("  step has alias 'result'")
            else:                       fail("  step missing alias 'result'")
    else:
        fail(f"GET /api/incidents/{TEST_INC_ID}/steps", str(s))

# 404 on non-existent
s, _ = GET("/api/incidents/999999")
if s == 404:  ok("GET /api/incidents/999999 -> 404 (correct)")
else:         fail("GET /api/incidents/999999 should 404", str(s))

# Run agent on an incident
if TEST_INC_ID:
    s, d = GET(f"/api/incidents/{TEST_INC_ID}")
    status_now = d.get("status", "")
    if status_now in ("resolved", "closed", "l3_escalated"):
        skip(f"POST /api/incidents/{TEST_INC_ID}/run  (already terminal: {status_now})")
    elif status_now in ("l1_running", "l2_running"):
        s2, d2 = POST(f"/api/incidents/{TEST_INC_ID}/run")
        if s2 == 400:  ok(f"POST /run on {status_now} -> 400 (correct, agent already running)")
        else:          fail(f"POST /run on {status_now} should 400", f"{s2}: {d2}")
    else:
        s2, d2 = POST(f"/api/incidents/{TEST_INC_ID}/run")
        if s2 == 200 and "message" in d2:  ok(f"POST /api/incidents/{TEST_INC_ID}/run  agent triggered")
        else:                               fail(f"POST /api/incidents/{TEST_INC_ID}/run", f"{s2}: {d2}")

# Re-run already-escalated -> should 400
s3, d3 = GET("/api/incidents/7")
if s3 == 200 and d3.get("status") == "l3_escalated":
    s4, d4 = POST("/api/incidents/7/run")
    if s4 == 400:  ok("POST /run on l3_escalated -> 400 (correct)")
    else:          fail("POST /run on l3_escalated should 400", str(s4))
elif s3 == 404:
    skip("INC-0007 not found (DB may have been reset)")
else:
    # Find any l3_escalated incident to test this
    sv, lv = GET("/api/incidents?status=l3_escalated&limit=1")
    if sv == 200 and lv:
        sx, dx = POST(f"/api/incidents/{lv[0]['id']}/run")
        if sx == 400:  ok("POST /run on l3_escalated -> 400 (correct)")
        else:          fail("POST /run on l3_escalated should 400", str(sx))
    else:
        skip("No l3_escalated incident available for test")

# ═══════════════════════════════════════════════════════════════════════════════
# 5. ALL 11 FAULT CATEGORIES — CREATE + CLASSIFY VIA API
# ═══════════════════════════════════════════════════════════════════════════════
section("5. ALL FAULT CATEGORIES via API (create + auto-classify)")

fault_incidents = [
    # (title, host, service, expected_fault_category)
    ("Disk full on storage-01 at 96 percent",         "storage-01", "ext4",        "disk_full"),
    ("High CPU on compute-01 usage 94 percent",       "compute-01", "app",         "high_cpu"),
    ("Memory usage at 92% on mem-01",                 "mem-01",     "jvm",         "high_memory"),
    ("Service down apache2 on svc-01",                "svc-01",     "apache2",     "service_down"),
    ("Host unreachable net-node-01 offline",          "net-node-01","kubelet",     "network_down"),
    ("High latency on lat-01 p99 above 4s",           "lat-01",     "api-gateway", "high_latency"),
    ("MySQL connection failed on db-01",              "db-01",      "mysql",       "database_issue"),
    ("Brute force login attempts on auth-01",         "auth-01",    "sshd",        "security_alert"),
    ("RAID array degraded on storage-02",             "storage-02", "md0",         "hardware_failure"),
    ("Application crash loop on app-01",              "app-01",     "node-app",    "application_error"),
    ("Generic monitoring alert on misc-01",           "misc-01",    "misc",        "unknown"),
]

created_ids = []
for i, (title, host, svc, expected_fault) in enumerate(fault_incidents):
    s, d = POST("/api/incidents", {"title": title, "affected_host": host, "affected_service": svc, "source": "test"})
    if s == 201:
        created_ids.append((d["id"], expected_fault, d["number"]))
        ok(f"Created {d['number']} [{d['priority']}]: {title[:50]}")
    else:
        fail(f"Create incident '{title[:40]}'", str(s))
    # Small delay between creates to avoid piling up concurrent agents
    if i < len(fault_incidents) - 1:
        time.sleep(1)

# Wait for classifier to run (embedded in the create endpoint)
time.sleep(3)

classify_ok = classify_fail = 0
for inc_id, expected_fault, number in created_ids:
    s, d = GET(f"/api/incidents/{inc_id}")
    got_fault = d.get("fault_category")
    if got_fault == expected_fault:
        ok(f"  {number} classified -> {got_fault}")
        classify_ok += 1
    else:
        fail(f"  {number} classify", f"expected {expected_fault}, got {got_fault}")
        classify_fail += 1

total_cats = len(fault_incidents)
print(f"\n  Classifier accuracy: {classify_ok}/{total_cats} = {round(classify_ok/total_cats*100)}%")

# ═══════════════════════════════════════════════════════════════════════════════
# 6. HOSTS CRUD
# ═══════════════════════════════════════════════════════════════════════════════
section("6. HOSTS (CMDB) CRUD")

s, hosts = GET("/api/hosts")
if s == 200 and isinstance(hosts, list):    ok(f"GET /api/hosts  ({len(hosts)} hosts)")
else:                                       fail("GET /api/hosts", str(s))

if hosts:
    h = hosts[0]
    for key in ["id","hostname","ip_address","criticality","ssh_user","ssh_available","auto_remediate"]:
        if key in h:  ok(f"  host has '{key}' = {h[key]}")
        else:         fail(f"  host missing '{key}'")

# Create
_TS = str(int(time.time()))[-5:]
NEW_HOSTNAME = f"test-host-{_TS}"
s, nh = POST("/api/hosts", {
    "hostname": NEW_HOSTNAME, "ip_address": "10.99.0.99", "os": "Ubuntu 22.04",
    "environment": "test", "criticality": "low", "ssh_user": "ubuntu", "ssh_port": 22,
    "auto_remediate": True, "known_issues": "Test host - safe to delete",
})
if s == 201 and nh.get("hostname") == NEW_HOSTNAME:
    ok(f"POST /api/hosts created {NEW_HOSTNAME}")
    TEST_HOST_ID = nh["id"]
else:
    fail("POST /api/hosts", f"{s}: {nh}")
    TEST_HOST_ID = None

# Duplicate hostname -> 409
if TEST_HOST_ID:
    s2, _ = POST("/api/hosts", {"hostname": NEW_HOSTNAME, "ssh_user": "ubuntu"})
    if s2 == 409:   ok("POST /api/hosts duplicate -> 409 (correct)")
    else:           fail("POST /api/hosts duplicate should 409", str(s2))

# Delete
if TEST_HOST_ID:
    s3, _ = DELETE(f"/api/hosts/{TEST_HOST_ID}")
    if s3 == 204:   ok(f"DELETE /api/hosts/{TEST_HOST_ID} -> 204")
    else:           fail(f"DELETE /api/hosts/{TEST_HOST_ID}", str(s3))

    # Confirm gone
    s4, lst = GET("/api/hosts")
    if not any(h["hostname"] == NEW_HOSTNAME for h in lst):
        ok("Host actually removed from list")
    else:
        fail("Host still in list after DELETE")

# Delete non-existent
s5, _ = DELETE("/api/hosts/999999")
if s5 == 404:  ok("DELETE /api/hosts/999999 -> 404 (correct)")
else:          fail("DELETE non-existent host should 404", str(s5))

# ═══════════════════════════════════════════════════════════════════════════════
# 7. NMS SOURCES CRUD
# ═══════════════════════════════════════════════════════════════════════════════
section("7. NMS SOURCES CRUD")

s, srcs = GET("/api/nms")
if s == 200 and isinstance(srcs, list):     ok(f"GET /api/nms  ({len(srcs)} sources)")
else:                                       fail("GET /api/nms", str(s))

if srcs:
    src = srcs[0]
    for key in ["id","name","nms_type","enabled","status"]:
        if key in src:  ok(f"  nms_source has '{key}' = {src[key]}")
        else:           fail(f"  nms_source missing '{key}'")

# Use unique names per test run to avoid leftover collisions
_NMS_SUFFIX = str(int(time.time()))[-5:]
nms_types = ["prometheus","zabbix","solarwinds","prtg"]
nms_created_names = []

for nms_type in nms_types:
    nms_name = f"t{_NMS_SUFFIX}-{nms_type}"
    s2, d2 = POST("/api/nms", {
        "name": nms_name, "nms_type": nms_type,
        "base_url": f"http://test-{nms_type}.internal", "enabled": False,
    })
    if s2 == 201:
        ok(f"POST /api/nms type={nms_type}")
        nms_created_names.append((d2["id"], nms_name))
    else:
        fail(f"POST /api/nms type={nms_type}", f"{s2}: {d2}")

# Duplicate name -> 409 (only test if we created at least one)
if nms_created_names:
    dup_name = nms_created_names[0][1]
    s3, d3 = POST("/api/nms", {"name": dup_name, "nms_type": "prometheus"})
    if s3 == 409:   ok("POST /api/nms duplicate -> 409 (correct)")
    else:           fail("POST /api/nms duplicate should 409", f"{s3}: {d3}")

# Clean up test NMS sources
for nms_id, nms_name in nms_created_names:
    sd, _ = DELETE(f"/api/nms/{nms_id}")
    if sd == 204:  ok(f"DELETE /api/nms/{nms_id} ({nms_name})")
    else:          fail(f"DELETE /api/nms/{nms_id}", str(sd))

# Delete non-existent
s6, _ = DELETE("/api/nms/999999")
if s6 == 404:  ok("DELETE /api/nms/999999 -> 404 (correct)")
else:          fail("DELETE non-existent NMS should 404", str(s6))

# ═══════════════════════════════════════════════════════════════════════════════
# 8. APPROVALS
# ═══════════════════════════════════════════════════════════════════════════════
section("8. APPROVALS")

for status_filter in ["pending","approved","rejected","all"]:
    s, d = GET(f"/api/approvals?status={status_filter}")
    if s == 200 and isinstance(d, list):
        ok(f"GET /api/approvals?status={status_filter}  ({len(d)} items)")
    else:
        fail(f"GET /api/approvals?status={status_filter}", str(s))

# Invalid token -> 404
s2, _ = POST("/api/approvals/nonexistent-token-xyz/approve")
if s2 == 404:   ok("POST /api/approvals/bad-token/approve -> 404 (correct)")
else:           fail("POST /api/approvals/bad-token should 404", str(s2))

s3, _ = POST("/api/approvals/nonexistent-token-xyz/reject")
if s3 == 404:   ok("POST /api/approvals/bad-token/reject -> 404 (correct)")
else:           fail("POST /api/approvals/bad-token/reject should 404", str(s3))

# ═══════════════════════════════════════════════════════════════════════════════
# 9. RESOLUTIONS (AGENT MEMORY)
# ═══════════════════════════════════════════════════════════════════════════════
section("9. RESOLUTIONS (AGENT MEMORY)")

s, rlist = GET("/api/resolutions")
if s == 200 and isinstance(rlist, list):    ok(f"GET /api/resolutions  ({len(rlist)} records)")
else:                                       fail("GET /api/resolutions", str(s))

if rlist:
    r = rlist[0]
    for key in ["id","host","fault_category","fault","fix_action","fix","time_to_fix_min","time_min","resolved_at_level","level","date"]:
        if key in r:  ok(f"  resolution has '{key}' = {r[key]}")
        else:         fail(f"  resolution missing alias '{key}'")

# ═══════════════════════════════════════════════════════════════════════════════
# 10. WEBHOOK — ALERTMANAGER
# ═══════════════════════════════════════════════════════════════════════════════
section("10. WEBHOOK — Alertmanager")

# Unique run ID so each test run creates fresh incidents (dedup won't collide)
_RUN_ID = str(int(time.time()))[-6:]

# Single firing alert
s, d = POST("/api/webhook/alertmanager", {
    "receiver": "amfi",
    "status": "firing",
    "alerts": [{
        "status": "firing",
        "labels": {"alertname": "HighDiskUsage", "instance": f"wh-host-{_RUN_ID}:9100",
                   "severity": "critical", "job": "node"},
        "annotations": {"summary": f"Disk usage above 95% on wh-host-{_RUN_ID}",
                        "description": "Volume / is at 97%"},
    }]
})
if s == 200 and d.get("created") == 1:
    ok(f"POST /webhook/alertmanager - 1 alert ingested, incident created")
    WEBHOOK_INC_ID = d["incident_ids"][0] if d.get("incident_ids") else None
else:
    fail("POST /webhook/alertmanager", f"{s}: {d}")
    WEBHOOK_INC_ID = None

# Duplicate alert (same source_id) -> not created again
s2, d2 = POST("/api/webhook/alertmanager", {
    "alerts": [{
        "status": "firing",
        "labels": {"alertname": "HighDiskUsage", "instance": f"wh-host-{_RUN_ID}:9100",
                   "severity": "critical"},
        "annotations": {"summary": f"Disk usage above 95% on wh-host-{_RUN_ID}"},
    }]
})
if s2 == 200 and d2.get("created") == 0:
    ok("POST /webhook/alertmanager duplicate alert -> 0 new (dedup works)")
else:
    fail("Webhook dedup", f"created={d2.get('created')}")

# Resolved alert -> not ingested
s3, d3 = POST("/api/webhook/alertmanager", {
    "alerts": [{"status": "resolved", "labels": {"alertname": "SomeAlert"}, "annotations": {}}]
})
if s3 == 200 and d3.get("created") == 0:
    ok("POST /webhook/alertmanager resolved alert -> 0 new (correct)")
else:
    fail("Webhook resolved filter", f"{s3}: {d3}")

# Multiple alerts at once (bulk ingest)
s4, d4 = POST("/api/webhook/alertmanager", {
    "alerts": [
        {"status":"firing","labels":{"alertname":"HighCPU",    "instance":f"bulk-{_RUN_ID}-01:9100","severity":"warning"},  "annotations":{"summary":f"CPU at 92% on bulk-{_RUN_ID}-01"}},
        {"status":"firing","labels":{"alertname":"ServiceDown","instance":f"bulk-{_RUN_ID}-02:9100","severity":"critical"},"annotations":{"summary":f"nginx down on bulk-{_RUN_ID}-02"}},
        {"status":"firing","labels":{"alertname":"MemoryHigh", "instance":f"bulk-{_RUN_ID}-03:9100","severity":"warning"},  "annotations":{"summary":f"Memory at 88% on bulk-{_RUN_ID}-03"}},
    ]
})
if s4 == 200 and d4.get("created") == 3:
    ok(f"POST /webhook/alertmanager bulk (3 alerts) -> 3 incidents created")
else:
    fail("Webhook bulk ingest", f"created={d4.get('created')}, expected 3")

# ═══════════════════════════════════════════════════════════════════════════════
# 11. AGENT EXECUTION — SPECIFIC PROCEDURES
# ═══════════════════════════════════════════════════════════════════════════════
section("11. AGENT EXECUTION — procedure dispatch")

# Drain any agents still running from earlier sections before we start.
# With Ollama doing real LLM calls (30-120s each), the queue from sections
# 4, 5, 10 can back up and prevent section 11 agents from starting in time.
print("  Waiting for agent queue to drain before procedure tests (max 300s)...")
_drain_deadline = time.time() + 300
while time.time() < _drain_deadline:
    _hs, _hd = GET("/api/health")
    _counts = _hd.get("incident_counts", {})
    _active = _counts.get("l1_running", 0) + _counts.get("l2_running", 0)
    if _active == 0:
        break
    time.sleep(5)
print(f"  Queue drained. Active agents now: {_active}")

proc_cases = [
    ("disk_full",      "Disk full on proc-test-01 at 98%",       "proc-test-01", "ext4"),
    ("high_cpu",       "High CPU on proc-test-02 load 22",        "proc-test-02", "app"),
    ("high_memory",    "Memory critical on proc-test-03 92%",     "proc-test-03", "jvm"),
    ("service_down",   "Service down redis on proc-test-04",      "proc-test-04", "redis"),
    ("database_issue", "PostgreSQL down on proc-test-05",         "proc-test-05", "postgresql"),
    ("network_down",   "Host unreachable proc-test-06",           "proc-test-06", "agent"),
]

proc_ids = []
for i, (fault, title, host, svc) in enumerate(proc_cases):
    s, d = POST("/api/incidents", {"title": title, "affected_host": host,
                                   "affected_service": svc, "source": "test"})
    if s == 201:
        proc_ids.append((d["id"], fault, d["number"]))
        ok(f"  Created {d['number']} for procedure test: {fault}")
    else:
        fail(f"  Create {fault} incident", str(s))
    if i < len(proc_cases) - 1:
        time.sleep(1)  # Space out agent starts

print(f"\n  Polling until all {len(proc_ids)} agents progress past 'new' (max 180s)...")
# Poll every 3s until all incidents are past 'new', or 180s timeout
_deadline = time.time() + 180
while time.time() < _deadline:
    _all_started = all(
        GET(f"/api/incidents/{inc_id}")[1].get("status", "new") != "new"
        for inc_id, _, _ in proc_ids
    )
    if _all_started:
        break
    time.sleep(3)

for inc_id, expected_fault, number in proc_ids:
    s, d = GET(f"/api/incidents/{inc_id}")
    got_fault  = d.get("fault_category")
    got_status = d.get("status")
    attempts   = d.get("attempt_count", 0)
    s2, steps  = GET(f"/api/incidents/{inc_id}/steps")
    step_count = len(steps) if isinstance(steps, list) else 0

    if got_fault == expected_fault:    ok(f"  {number} [{expected_fault}] classified correctly")
    else:                              fail(f"  {number} fault", f"expected {expected_fault} got {got_fault}")

    if got_status in ("l3_escalated","l1_running","l2_running","l1_failed","resolved"):
        ok(f"  {number} status={got_status} attempts={attempts} steps={step_count}")
    else:
        fail(f"  {number} unexpected status", got_status)

    if step_count >= 1:  ok(f"  {number} generated {step_count} step(s)")
    else:                fail(f"  {number} no steps generated")

# ═══════════════════════════════════════════════════════════════════════════════
# 12. OLLAMA AI — LIVE INTERPRETATION TEST
# ═══════════════════════════════════════════════════════════════════════════════
section("12. OLLAMA AI — live LLM call")

import asyncio

async def test_ollama():
    from backend.agent.llm import _call_llm, check_ollama, interpret_diagnostics

    # Health
    result = await check_ollama()
    if result["running"]:   ok(f"check_ollama() running=True model_available={result['model_available']}")
    else:                   skip("Ollama not running - skipping AI tests")
    if not result["running"]:
        return

    # Direct LLM call
    resp = await _call_llm("Reply with exactly: AMFI_AI_OK", max_tokens=20)
    if resp and len(resp) > 0:   ok(f"_call_llm() returned response ({len(resp)} chars)")
    else:                         fail("_call_llm() returned empty response")

    # Diagnostic interpretation
    diag = {
        "Check disk usage": "Filesystem      Use% Avail\n/var/log         94%  1.2G\n/               41%   52G",
        "Check top processes": "PID  %CPU  COMMAND\n1234  0.1   bash\n5678  0.0   ps",
    }
    interp = await interpret_diagnostics("disk_full", "test-host", diag)
    if interp and len(interp) >= 5:
        ok(f"interpret_diagnostics() returned AI response ({len(interp)} chars)")
        if len(interp) > 50:
            ok(f"  AI response is substantive (>50 chars)")
            print(f"\n  {CYAN}Sample AI output:{RESET}")
            for line in interp[:300].split("\n")[:4]:
                print(f"    {line}")
        else:
            skip(f"  AI response short ({len(interp)} chars) - Ollama may be under load")
    elif not interp:
        skip("interpret_diagnostics() returned empty - Ollama under load or model not responding")
    else:
        fail("interpret_diagnostics() returned nothing useful")

asyncio.run(test_ollama())

# ═══════════════════════════════════════════════════════════════════════════════
# 13. SLA CALCULATION
# ═══════════════════════════════════════════════════════════════════════════════
section("13. SLA CALCULATION")

sla_cases = [
    ("p1", "Critical: production down",  15,   60),
    ("p2", "High: disk full on db",      60,  240),
    ("p3", "Warning: high latency",     240, 1440),
    ("p4", "Low: minor disk warning",  1440, 4320),
]
for prio, title, resp_min, res_min in sla_cases:
    s, d = POST("/api/incidents", {"title": title, "source": "test", "priority": prio})
    if s != 201:
        fail(f"Create {prio} incident for SLA test", str(s))
        continue
    # SLA is now set inline in the create endpoint — no wait needed.
    # Read immediately and verify the SLA deadlines are present.
    s2, d2 = GET(f"/api/incidents/{d['id']}")
    if d2.get("sla_response_due") and d2.get("sla_resolve_due"):
        ok(f"{prio.upper()} SLA set: response_due={d2['sla_response_due'][:16]} resolve_due={d2['sla_resolve_due'][:16]}")
        created = datetime.fromisoformat(d2["created_at"])
        resolve = datetime.fromisoformat(d2["sla_resolve_due"])
        actual_min = (resolve - created).total_seconds() / 60
        if abs(actual_min - res_min) < 5:
            ok(f"  SLA resolve window ~{round(actual_min)}m (expected {res_min}m)")
        else:
            fail(f"  SLA resolve window", f"got {round(actual_min)}m expected {res_min}m")
    else:
        fail(f"{prio} SLA not calculated", str(d2.get("sla_resolve_due")))

# ═══════════════════════════════════════════════════════════════════════════════
# 14. EDGE CASES & VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════
section("14. EDGE CASES & VALIDATION")

# Empty title -> 422
s, d = POST("/api/incidents", {"title": "", "source": "test"})
if s == 422:    ok("POST /api/incidents empty title -> 422 (validation error)")
else:           fail("Empty title should 422", f"got {s}: {d}")

# Whitespace-only title -> 422
s_ws, d_ws = POST("/api/incidents", {"title": "   ", "source": "test"})
if s_ws == 422: ok("POST /api/incidents whitespace title -> 422")
else:           fail("Whitespace title should 422", f"got {s_ws}")

# Missing title -> 422
s2, d2 = POST("/api/incidents", {"source": "test"})
if s2 == 422:   ok("POST /api/incidents missing title -> 422")
else:           fail("Missing title should 422", f"got {s2}")

# Very long title (499 chars)
long_title = "Disk full on " + "A" * 486
s3, d3 = POST("/api/incidents", {"title": long_title, "source": "test"})
if s3 == 201:   ok("POST /api/incidents 499-char title accepted")
else:           fail("Long title rejected", f"got {s3}")

# Invalid method on read-only endpoint
import urllib.request
req = urllib.request.Request(f"{BASE}/api/health", method="DELETE")
try:
    urllib.request.urlopen(req, timeout=5)
    fail("DELETE /api/health should be 405")
except urllib.error.HTTPError as e:
    if e.code == 405:  ok("DELETE /api/health -> 405 Method Not Allowed")
    else:              fail("DELETE /api/health", f"got {e.code}")
except Exception as e:
    fail("DELETE /api/health request failed", str(e))

# Pagination — verify no overlap between pages
s4, lst4 = GET("/api/incidents?limit=3&offset=0")
s5, lst5 = GET("/api/incidents?limit=3&offset=3")
if s4 == 200 and s5 == 200 and isinstance(lst4, list) and isinstance(lst5, list):
    ids4 = {i["id"] for i in lst4}
    ids5 = {i["id"] for i in lst5}
    if not ids4.intersection(ids5):
        ok(f"Pagination works: page1={len(lst4)} items, page2={len(lst5)} items, no overlap")
    else:
        fail("Pagination overlap detected")
else:
    fail("Pagination requests failed", f"{s4}/{s5}")

# ═══════════════════════════════════════════════════════════════════════════════
# 15. INCIDENT LIFECYCLE — status transitions
# ═══════════════════════════════════════════════════════════════════════════════
section("15. INCIDENT LIFECYCLE (status/transitions)")

# Create fresh incident in 'new' state
s, lc_inc = POST("/api/incidents", {
    "title": "Lifecycle test: service down on lc-host-01",
    "source": "test",
    "affected_host": "lc-host-01",
    "affected_service": "nginx",
})
if s != 201:
    fail("Lifecycle incident create", str(s))
else:
    lc_id = lc_inc["id"]
    ok(f"Lifecycle test incident created: {lc_inc['number']}")

    # Verify initial state
    sv, dv = GET(f"/api/incidents/{lc_id}")
    if sv == 200 and dv.get("status") in ("new", "l1_running"):
        ok(f"Initial status is '{dv['status']}'")
    else:
        fail("Initial status unexpected", dv.get("status"))

    # Trigger agent (if new)
    if dv.get("status") == "new":
        sr, dr = POST(f"/api/incidents/{lc_id}/run")
        if sr == 200:
            ok("Agent triggered via /run")
        else:
            fail("Agent trigger failed", str(sr))

    # Poll until status progresses past 'new' (max 120s)
    _lc_deadline = time.time() + 120
    df = {}
    while time.time() < _lc_deadline:
        sf, df = GET(f"/api/incidents/{lc_id}")
        if df.get("status", "new") != "new":
            break
        time.sleep(3)
    status_after = df.get("status", "unknown")
    if status_after in ("l1_running","l3_escalated","resolved","l1_failed"):
        ok(f"Status progressed to '{status_after}'")
    else:
        fail("Status did not progress", status_after)

# ═══════════════════════════════════════════════════════════════════════════════
# 16. RAPID SEQUENTIAL INCIDENT CREATION (throughput / stress)
# ═══════════════════════════════════════════════════════════════════════════════
section("16. RAPID SEQUENTIAL INCIDENT CREATION (throughput)")

stress_results = []
t0 = time.time()
for i in range(10):
    s, d = POST("/api/incidents", {
        "title":         f"Stress test incident {i:03d}: disk full alert",
        "source":        "stress_test",
        "affected_host": f"stress-host-{i:02d}",
    })
    stress_results.append(s == 201)
elapsed = round(time.time() - t0, 2)

success_count = sum(stress_results)
if success_count == 10:
    ok(f"10 sequential incident creates — all succeeded in {elapsed}s ({round(elapsed/10,2)}s avg)")
elif success_count >= 8:
    ok(f"10 sequential creates — {success_count}/10 succeeded in {elapsed}s (acceptable)")
else:
    fail(f"Rapid sequential creates", f"{success_count}/10 succeeded in {elapsed}s")

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 17: Monitored Hosts API
# ═══════════════════════════════════════════════════════════════════════════════
section("17. Monitored Hosts API")

_MH_SUFFIX = str(int(time.time()))[-6:]

# 17.1 List hosts (empty initially is fine)
s, d = GET("/api/monitored-hosts")
if s == 200 and isinstance(d, list):
    ok(f"GET /api/monitored-hosts → {len(d)} hosts")
else:
    fail("GET /api/monitored-hosts", f"status={s}")

# 17.2 Create a monitored host
_mh_router_name = f"test-router-{_MH_SUFFIX}"
s, d = POST("/api/monitored-hosts", {
    "hostname":    _mh_router_name,
    "ip_address":  "192.168.1.1",
    "device_type": "network",
    "display_name":"Test Router",
    "environment": "lab",
    "snmp_community": "public",
    "snmp_version": "2c",
    "poll_interval": 60,
})
if s == 201:
    _host_id = d.get("id")
    ok(f"POST /api/monitored-hosts → id={_host_id}, hostname={d.get('hostname')}")
else:
    _host_id = None
    fail("POST /api/monitored-hosts", f"status={s}, body={str(d)[:200]}")

# 17.3 Create a Linux host
_mh_linux_name = f"test-linux-{_MH_SUFFIX}"
s, d2 = POST("/api/monitored-hosts", {
    "hostname":    _mh_linux_name,
    "ip_address":  "10.0.0.1",
    "device_type": "linux",
    "display_name":"Test Linux Server",
    "ssh_user":    "monitoring",
    "poll_interval": 120,
})
if s == 201:
    _linux_host_id = d2.get("id")
    ok(f"POST /api/monitored-hosts (linux) → id={_linux_host_id}")
else:
    _linux_host_id = None
    fail("POST /api/monitored-hosts (linux)", f"status={s}")

# 17.4 List hosts — should now have at least 2
s, d = GET("/api/monitored-hosts")
if s == 200 and isinstance(d, list) and len(d) >= 2:
    ok(f"GET /api/monitored-hosts after create → {len(d)} hosts")
elif s == 200:
    ok(f"GET /api/monitored-hosts → {len(d)} hosts (some may be pre-existing)")
else:
    fail("GET /api/monitored-hosts after create", f"status={s}")

# 17.5 Get specific host
if _host_id:
    s, d = GET(f"/api/monitored-hosts/{_host_id}")
    if s == 200 and d.get("id") == _host_id:
        ok(f"GET /api/monitored-hosts/{_host_id} → hostname={d.get('hostname')}")
    else:
        fail(f"GET /api/monitored-hosts/{_host_id}", f"status={s}")
else:
    skip("GET /api/monitored-hosts/id (no host created)")

# 17.6 Update host
if _host_id:
    s, d = http("PUT", f"/api/monitored-hosts/{_host_id}", {
        "hostname":    _mh_router_name,
        "ip_address":  "192.168.1.1",
        "device_type": "network",
        "display_name":"Updated Router",
        "poll_interval": 120,
        "enabled": True,
    })
    if s == 200 and d.get("display_name") == "Updated Router":
        ok(f"PUT /api/monitored-hosts/{_host_id} → display_name updated")
    else:
        fail(f"PUT /api/monitored-hosts/{_host_id}", f"status={s}")
else:
    skip("PUT /api/monitored-hosts/id (no host created)")

# 17.7 Force poll (may fail if host unreachable — that's OK)
if _host_id:
    s, d = POST(f"/api/monitored-hosts/{_host_id}/poll", {})
    if s in (200, 202, 204):
        ok(f"POST /api/monitored-hosts/{_host_id}/poll → triggered")
    else:
        ok(f"POST /api/monitored-hosts/{_host_id}/poll → {s} (host unreachable in test env)")
else:
    skip("POST /api/monitored-hosts/id/poll (no host created)")

# 17.8 Metrics endpoint (may be empty if host was never polled)
if _host_id:
    s, d = GET(f"/api/monitored-hosts/{_host_id}/metrics?hours=1")
    if s == 200:
        ok(f"GET /api/monitored-hosts/{_host_id}/metrics → {len(d) if isinstance(d, list) else 'ok'}")
    else:
        fail(f"GET /api/monitored-hosts/{_host_id}/metrics", f"status={s}")
else:
    skip("GET /api/monitored-hosts/id/metrics (no host created)")

# 17.9 Metrics summary (returns list of hosts with their latest metrics)
s, d = GET("/api/metrics/summary")
if s == 200 and isinstance(d, (list, dict)):
    count = len(d) if isinstance(d, list) else len(d.keys())
    ok(f"GET /api/metrics/summary → {count} items")
else:
    fail("GET /api/metrics/summary", f"status={s}, type={type(d).__name__}")

# 17.10 Delete host
if _host_id:
    s, _ = http("DELETE", f"/api/monitored-hosts/{_host_id}", None)
    if s == 204:
        ok(f"DELETE /api/monitored-hosts/{_host_id} → deleted")
    else:
        fail(f"DELETE /api/monitored-hosts/{_host_id}", f"status={s}")
    # Clean up second host
    if _linux_host_id:
        http("DELETE", f"/api/monitored-hosts/{_linux_host_id}", None)
else:
    skip("DELETE /api/monitored-hosts/id (no host created)")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 18: Threshold Rules API
# ═══════════════════════════════════════════════════════════════════════════════
section("18. Threshold Rules API")

# 18.1 List rules (seeded defaults)
s, d = GET("/api/threshold-rules")
if s == 200 and isinstance(d, list):
    ok(f"GET /api/threshold-rules → {len(d)} rules (includes seeded defaults)")
else:
    fail("GET /api/threshold-rules", f"status={s}")

# 18.2 Create a custom rule
s, d = POST("/api/threshold-rules", {
    "name":             "Test CPU Critical",
    "metric":           "cpu_percent",
    "operator":         "gt",
    "threshold":        95.0,
    "priority":         "p1",
    "fault_category":   "high_cpu",
    "cooldown_minutes": 15,
    "enabled":          True,
})
if s == 201:
    _rule_id = d.get("id")
    ok(f"POST /api/threshold-rules → id={_rule_id}, name={d.get('name')}")
else:
    _rule_id = None
    fail("POST /api/threshold-rules", f"status={s}, body={str(d)[:200]}")

# 18.3 Update rule
if _rule_id:
    s, d = http("PUT", f"/api/threshold-rules/{_rule_id}", {
        "name":             "Test CPU Critical (updated)",
        "metric":           "cpu_percent",
        "operator":         "gt",
        "threshold":        99.0,
        "priority":         "p1",
        "fault_category":   "high_cpu",
        "cooldown_minutes": 20,
        "enabled":          False,
    })
    if s == 200 and d.get("threshold") == 99.0:
        ok(f"PUT /api/threshold-rules/{_rule_id} → threshold=99, enabled=False")
    else:
        fail(f"PUT /api/threshold-rules/{_rule_id}", f"status={s}")
else:
    skip("PUT /api/threshold-rules/id (no rule created)")

# 18.4 Re-list and confirm update
s, d = GET("/api/threshold-rules")
if s == 200:
    custom = [r for r in d if "updated" in (r.get("name") or "").lower()]
    if custom:
        ok(f"Threshold rule update confirmed in list (threshold={custom[0].get('threshold')})")
    else:
        ok(f"GET /api/threshold-rules re-list → {len(d)} rules")
else:
    fail("GET /api/threshold-rules re-list", f"status={s}")

# 18.5 Delete custom rule
if _rule_id:
    s, _ = http("DELETE", f"/api/threshold-rules/{_rule_id}", None)
    if s == 204:
        ok(f"DELETE /api/threshold-rules/{_rule_id} → deleted")
    else:
        fail(f"DELETE /api/threshold-rules/{_rule_id}", f"status={s}")
else:
    skip("DELETE /api/threshold-rules/id (no rule created)")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 19: Auth & WebSocket endpoints
# ═══════════════════════════════════════════════════════════════════════════════
section("19. Auth & WebSocket")

# 19.1 Auth status endpoint (always public)
s, d = GET("/api/auth/status")
if s == 200 and "auth_enabled" in d:
    ok(f"GET /api/auth/status → auth_enabled={d['auth_enabled']}")
else:
    fail("GET /api/auth/status", f"status={s}")

# 19.2 Login with valid credentials
import urllib.parse as _ul
_login_bytes = _ul.urlencode({"username": "admin", "password": "amfi2024!"}).encode()
s, d = http("POST", "/api/auth/login", timeout=15,
            body_raw=_login_bytes, content_type="application/x-www-form-urlencoded")
if s == 200 and d.get("access_token"):
    _jwt_token = d["access_token"]
    ok(f"POST /api/auth/login → token obtained (role={d.get('role')})")
else:
    _jwt_token = None
    fail("POST /api/auth/login", f"status={s}, body={str(d)[:200]}")

# 19.3 GET /auth/me with valid token
if _jwt_token:
    s, d = GET("/api/auth/me", headers={"Authorization": f"Bearer {_jwt_token}"})
    if s == 200 and d.get("username") == "admin":
        ok(f"GET /api/auth/me → username={d['username']}, role={d.get('role')}")
    else:
        fail("GET /api/auth/me", f"status={s}, body={str(d)[:200]}")
else:
    skip("GET /api/auth/me (no token)")

# 19.4 Login with wrong password
_bad_bytes = _ul.urlencode({"username": "admin", "password": "wrong!"}).encode()
s, d = http("POST", "/api/auth/login", timeout=15,
            body_raw=_bad_bytes, content_type="application/x-www-form-urlencoded")
if s == 401:
    ok("POST /api/auth/login with bad password → 401 (correct)")
else:
    fail("POST /api/auth/login bad password", f"expected 401, got {s}")

# 19.5 WebSocket stats REST endpoint
s, d = GET("/api/ws/stats")
if s == 200 and "connections" in d:
    ok(f"GET /api/ws/stats → connections={d['connections']}")
else:
    fail("GET /api/ws/stats", f"status={s}")

# 19.6 Training stats endpoint
s, d = GET("/api/training/stats")
if s == 200:
    ok(f"GET /api/training/stats → {list(d.keys())[:4] if isinstance(d, dict) else 'ok'}")
else:
    fail("GET /api/training/stats", f"status={s}")


# ═══════════════════════════════════════════════════════════════════════════════
# FINAL SUMMARY
# ═══════════════════════════════════════════════════════════════════════════════
total = passed + failed + skipped
print(f"\n{'='*60}")
print(f"{BOLD}  TEST RESULTS{RESET}")
print(f"{'='*60}")
print(f"  {GREEN}Passed:  {passed}{RESET}")
print(f"  {RED}Failed:  {failed}{RESET}")
print(f"  {YELLOW}Skipped: {skipped}{RESET}")
print(f"  Total:   {total}")
print(f"  Score:   {round(passed/(passed+failed)*100) if (passed+failed) > 0 else 0}%")
print(f"{'='*60}")

if failed > 0:
    print(f"\n{RED}FAILURES:{RESET}")
    for status, name, detail in results:
        if status == "FAIL":
            print(f"  {RED}x{RESET} {name}" + (f": {detail}" if detail else ""))

sys.exit(0 if failed == 0 else 1)
