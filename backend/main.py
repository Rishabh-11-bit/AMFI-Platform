"""AMFI Platform — Main Application."""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from backend.config import get_settings
from backend.database import init_db, AsyncSessionLocal
import backend.models.all_models  # noqa
from backend.routers.api import (
    ingest_router, incident_router, remediation_router,
    cmdb_router, dashboard_router, auth_router,
)
from backend.services.ingestion_service import IngestionService
from backend.services.pipeline import run_pending_raw_events, run_sla_checks, run_remediation_polling
from backend.listeners.snmp_listener import SNMPTrapListener
from backend.listeners.syslog_listener import SyslogListener
from backend.listeners.mqtt_listener import MQTTListener

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("amfi.main")
settings = get_settings()
listener_status: dict = {"snmp": "starting", "syslog": "starting", "mqtt": "starting"}

async def _on_snmp_trap(trap: dict):
    async with AsyncSessionLocal() as db:
        await IngestionService(db).ingest_snmp(trap, trap.get("source_ip"))
        await db.commit()

async def _on_syslog(parsed: dict):
    async with AsyncSessionLocal() as db:
        await IngestionService(db).ingest_syslog(parsed, parsed.get("source_ip"))
        await db.commit()

async def _on_mqtt(topic: str, payload: dict):
    async with AsyncSessionLocal() as db:
        await IngestionService(db).ingest_mqtt(topic, payload)
        await db.commit()

async def _run_snmp():
    listener_status["snmp"] = "running"
    try:
        await SNMPTrapListener(_on_snmp_trap).start()
    except Exception as e:
        listener_status["snmp"] = f"error: {e}"

async def _run_syslog():
    listener_status["syslog"] = "running"
    try:
        await SyslogListener(_on_syslog).start()
    except Exception as e:
        listener_status["syslog"] = f"error: {e}"

async def _run_mqtt():
    listener_status["mqtt"] = "running"
    try:
        await MQTTListener(_on_mqtt).start()
    except Exception as e:
        listener_status["mqtt"] = f"error: {e}"

async def _scheduler():
    counters = {"pipeline": 0, "sla": 0, "rem": 0}
    while True:
        await asyncio.sleep(5)
        for k in counters:
            counters[k] += 5
        if counters["pipeline"] >= 5:
            counters["pipeline"] = 0
            try: await run_pending_raw_events()
            except Exception as e: logger.error("Pipeline error: %s", e)
        if counters["sla"] >= 60:
            counters["sla"] = 0
            try: await run_sla_checks()
            except Exception as e: logger.error("SLA error: %s", e)
        if counters["rem"] >= settings.remediation_poll_interval_seconds:
            counters["rem"] = 0
            try: await run_remediation_polling()
            except Exception as e: logger.error("Rem poller error: %s", e)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initialising DB...")
    await init_db()
    await _seed_admin()
    tasks = [
        asyncio.create_task(_run_snmp()),
        asyncio.create_task(_run_syslog()),
        asyncio.create_task(_run_mqtt()),
        asyncio.create_task(_scheduler()),
    ]
    logger.info("AMFI ready at http://%s:%d — docs at /docs", settings.api_host, settings.api_port)
    yield
    for t in tasks: t.cancel()

async def _seed_admin():
    from sqlalchemy import select
    from backend.models.all_models import User
    import bcrypt as _bcrypt
    
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(User).where(User.username == "admin"))
        if not r.scalar_one_or_none():
            db.add(User(username="admin", email="admin@amfi.local",
                        full_name="AMFI Admin", hashed_password=_bcrypt.hashpw(b"admin123", _bcrypt.gensalt()).decode(), role="admin"))
            await db.commit()
            logger.info("Default admin created: admin / admin123")

app = FastAPI(
    title="AMFI – IT Service Automation Platform",
    description="Ingest → Enrich → Correlate → Decide → Diagnose → Remediate → Notify",
    version="1.0.0", lifespan=lifespan, docs_url="/docs", redoc_url="/redoc",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(ingest_router,      prefix="/api/ingest",     tags=["Ingestion"])
app.include_router(incident_router,    prefix="/api/incidents",  tags=["Incidents"])
app.include_router(remediation_router, prefix="/api/remediation",tags=["Remediation"])
app.include_router(cmdb_router,        prefix="/api/cmdb",       tags=["CMDB"])
app.include_router(dashboard_router,   prefix="/api/dashboard",  tags=["Dashboard"])
app.include_router(auth_router,        prefix="/api/auth",       tags=["Auth"])

frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.exists(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

@app.get("/api/health")
async def health():
    return {"status": "healthy", "version": "1.0.0", "listeners": listener_status}
