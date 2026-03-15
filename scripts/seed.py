"""
Seed Script — creates initial data for testing.
Run: python scripts/seed.py

Creates:
  - Admin user (admin / admin123)
  - 3 sample CMDB entries (web server, DB server, switch)
  - 1 sample Prometheus alert
"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from backend.database import AsyncSessionLocal, init_db
from backend.models.all_models import User, ConfigItem
import bcrypt as _bcrypt




async def seed():
    await init_db()
    async with AsyncSessionLocal() as db:

        # ── Admin user ────────────────────────────────────────────────────────
        r = await db.execute(select(User).where(User.username == "admin"))
        if not r.scalar_one_or_none():
            db.add(User(username="admin", email="admin@amfi.local",
                        full_name="AMFI Admin", hashed_password=_bcrypt.hashpw(b"admin123", _bcrypt.gensalt()).decode(), role="admin"))
            print("Created user: admin / admin123")

        # ── CMDB entries ──────────────────────────────────────────────────────
        sample_cis = [
            dict(ci_id="WEB-001", hostname="web-server-01", ip_address="10.0.1.10",
                 ci_type="server", os="Ubuntu 22.04", environment="prod",
                 owner="ops@example.com", team="server-ops",
                 business_service="e-commerce", criticality="critical",
                 supports=["DB-001"], dependent_on=[],
                 ssh_user="ubuntu", ssh_key_path="/app/ssh-keys/web-server-01.pem"),

            dict(ci_id="DB-001", hostname="db-server-01", ip_address="10.0.1.20",
                 ci_type="server", os="Ubuntu 22.04", environment="prod",
                 owner="dba@example.com", team="dba-team",
                 business_service="e-commerce", criticality="critical",
                 supports=[], dependent_on=["WEB-001"],
                 ssh_user="ubuntu", ssh_key_path="/app/ssh-keys/db-server-01.pem"),

            dict(ci_id="SW-001", hostname="core-switch-01", ip_address="10.0.0.1",
                 ci_type="switch", environment="prod",
                 owner="netops@example.com", team="network-ops",
                 business_service="all", criticality="critical",
                 supports=["WEB-001", "DB-001"], dependent_on=[]),
        ]

        for ci_data in sample_cis:
            r = await db.execute(select(ConfigItem).where(ConfigItem.ci_id == ci_data["ci_id"]))
            if not r.scalar_one_or_none():
                db.add(ConfigItem(**ci_data))
                print(f"Created CI: {ci_data['ci_id']} ({ci_data['hostname']})")

        await db.commit()
        print("\nSeed complete!")
        print("─" * 50)
        print("Login:  http://localhost:8000/docs  (API)")
        print("UI:     http://localhost:80")
        print("Creds:  admin / admin123")
        print()
        print("Test event ingestion:")
        print('  curl -X POST http://localhost:8000/api/ingest/manual \\')
        print('    -H "Content-Type: application/json" \\')
        print('    -d \'{"title":"High CPU on web-server-01","severity":"critical","affected_host":"10.0.1.10"}\'')


if __name__ == "__main__":
    asyncio.run(seed())
