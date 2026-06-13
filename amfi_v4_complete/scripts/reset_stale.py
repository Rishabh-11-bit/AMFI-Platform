"""
Reset stale running incidents and escalate old 'new' test incidents
so a clean test run isn't blocked by background agent queue.
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

async def main():
    from backend.database import AsyncSessionLocal
    from backend.models.models import Incident

    async with AsyncSessionLocal() as db:
        from sqlalchemy import select

        # 1. Reset any l1_running / l2_running (orphaned after server restart)
        r = await db.execute(
            select(Incident).where(Incident.status.in_(["l1_running", "l2_running"]))
        )
        stale = r.scalars().all()
        for inc in stale:
            inc.status = "new"
        print(f"Reset {len(stale)} stale-running -> new")

        # 2. Escalate all pre-existing 'new' incidents (from previous test runs)
        #    so they don't feed agents during the current test run.
        r2 = await db.execute(select(Incident).where(Incident.status == "new"))
        old_new = r2.scalars().all()
        for inc in old_new:
            inc.status = "l3_escalated"
        print(f"Escalated {len(old_new)} pre-existing 'new' incidents -> l3_escalated")

        await db.commit()

    print("Done. DB is clean for a fresh test run.")

asyncio.run(main())
