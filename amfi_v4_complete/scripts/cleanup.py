"""Cleanup stale test data."""
import urllib.request
import json

BASE = "http://localhost:8000"

# Delete stale test monitored hosts (IDs 1 and 2 from previous test runs)
for hid in [1, 2]:
    try:
        req = urllib.request.Request(f"{BASE}/api/monitored-hosts/{hid}", method="DELETE")
        r = urllib.request.urlopen(req, timeout=10)
        print(f"Deleted monitored-host/{hid}: {r.getcode()}")
    except urllib.error.HTTPError as e:
        print(f"Delete host/{hid}: HTTP {e.code} (already gone)")
    except Exception as e:
        print(f"Delete host/{hid} error: {e}")

# Check agent queue
r = urllib.request.urlopen(f"{BASE}/api/health", timeout=5)
d = json.loads(r.read())
counts = d.get("incident_counts", {})
print(f"Queue: l1_running={counts.get('l1_running',0)}, new={counts.get('new',0)}")
