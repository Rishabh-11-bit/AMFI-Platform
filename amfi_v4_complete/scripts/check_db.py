"""Check SQLite database integrity and run server startup test."""
import sqlite3
import os
import sys

db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "amfi_v4.db")
print(f"DB path: {db_path}")
print(f"DB exists: {os.path.exists(db_path)}")
print(f"DB size: {os.path.getsize(db_path) / 1024 / 1024:.1f} MB")

try:
    conn = sqlite3.connect(db_path)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    print(f"Tables: {tables}")
    integrity = conn.execute("PRAGMA integrity_check").fetchone()
    print(f"Integrity: {integrity[0]}")
    wal = conn.execute("PRAGMA journal_mode").fetchone()
    print(f"Journal mode: {wal[0]}")
    count = conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
    print(f"Incident count: {count}")
    conn.close()
except Exception as e:
    print(f"DB error: {e}")
    sys.exit(1)

# Test importing the app
print("\nTesting app import...")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from backend.main import app
    print("App imported OK")
except Exception as e:
    print(f"App import error: {e}")
    import traceback
    traceback.print_exc()
