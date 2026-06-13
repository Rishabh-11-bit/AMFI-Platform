"""
Export training data from resolved incidents.
Run: python scripts/export_training.py

Exports all resolved incidents as fine-tuning examples.
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

async def main():
    from backend.database import AsyncSessionLocal, init_db
    from backend.services.training.collector import get_stats, generate_synthetic_examples
    from backend.models.models import Incident, IncidentStatus, IncidentStep
    from backend.services.training.collector import export_resolved_incident
    from sqlalchemy import select

    await init_db()

    async with AsyncSessionLocal() as db:
        # Export all resolved incidents
        r = await db.execute(
            select(Incident).where(Incident.status == IncidentStatus.RESOLVED)
        )
        incidents = r.scalars().all()

        print(f"\nExporting {len(incidents)} resolved incidents...")
        exported = 0
        for inc in incidents:
            if await export_resolved_incident(inc.id, db):
                exported += 1
                print(f"  Exported: {inc.number} — {inc.title[:50]}")

        print(f"\nExported {exported}/{len(incidents)} incidents")

        # Show stats
        stats = await get_stats(db)
        print(f"\nTraining Data Stats:")
        print(f"  Total examples: {stats['exported_examples']}")
        print(f"  By category:    {stats['by_fault_category']}")
        print(f"  Status:         {stats['message']}")

        # Offer to generate synthetic data if needed
        if stats['exported_examples'] < 200:
            print(f"\nYou have fewer than 200 real examples.")
            ans = input("Generate 100 synthetic examples using AI? (y/n): ").strip().lower()
            if ans == 'y':
                print("Generating synthetic examples (requires Ollama or Claude API)...")
                n = await generate_synthetic_examples(100)
                print(f"Generated {n} synthetic examples")

if __name__ == "__main__":
    asyncio.run(main())
