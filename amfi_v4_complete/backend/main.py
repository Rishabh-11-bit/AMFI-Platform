"""AMFI v4 - FastAPI Application with NMS polling scheduler."""
import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from backend.utils.rate_limit import limiter

from backend.config import get_settings
from backend.database import init_db, AsyncSessionLocal
from backend.routers.api import router
from backend.routers.auth import router as auth_router
from backend.routers.webhooks import router as webhooks_router
from backend.routers.ws import router as ws_router
import backend.models.models  # register all tables

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger   = logging.getLogger("amfi.main")
settings = get_settings()

# Background tasks
_nms_task        = None
_monitor_task    = None


async def _nms_scheduler():
    """Poll NMS sources every NMS_POLL_SECONDS."""
    from backend.services.nms.connectors import poll_all
    while True:
        await asyncio.sleep(settings.nms_poll_seconds)
        try:
            n = await poll_all()
            if n:
                logger.info("NMS scheduler: %d new incidents", n)
        except Exception as e:
            logger.error("NMS scheduler error: %s", e)


async def _monitoring_scheduler():
    """
    Monitoring poll loop — checks every 30s which hosts are due for polling
    (based on last_polled_at + poll_interval) and polls them concurrently.
    Also purges MetricSample rows older than 7 days to keep the DB lean.
    """
    from sqlalchemy import select, delete as _delete
    from backend.database import AsyncSessionLocal
    from backend.models.models import MonitoredHost, MetricSample
    from backend.routers.api import _poll_and_store

    PURGE_INTERVAL = 3600   # run purge once per hour
    last_purge     = 0.0

    while True:
        await asyncio.sleep(30)
        try:
            now = datetime.utcnow()

            # Collect hosts due for a poll
            async with AsyncSessionLocal() as db:
                r = await db.execute(
                    select(MonitoredHost).where(MonitoredHost.enabled == True)
                )
                hosts = r.scalars().all()

            due = []
            for h in hosts:
                if h.last_polled_at is None:
                    due.append(h.id)
                else:
                    elapsed = (now - h.last_polled_at).total_seconds()
                    if elapsed >= h.poll_interval:
                        due.append(h.id)

            if due:
                await asyncio.gather(*[_poll_and_store(hid) for hid in due],
                                     return_exceptions=True)

            # Purge old samples
            import time
            if time.monotonic() - last_purge > PURGE_INTERVAL:
                cutoff = now - timedelta(days=7)
                async with AsyncSessionLocal() as db:
                    await db.execute(
                        _delete(MetricSample).where(MetricSample.sampled_at < cutoff)
                    )
                    await db.commit()
                last_purge = time.monotonic()
                logger.info("Monitoring: purged metric samples older than 7 days")

        except Exception as e:
            logger.error("Monitoring scheduler error: %s", e)


async def _seed_defaults():
    """Seed admin user and default SLA policies on first run."""
    from sqlalchemy import select
    from backend.models.models import User, SLAPolicy, Priority
    import bcrypt

    async with AsyncSessionLocal() as db:
        # Admin user
        r = await db.execute(select(User).where(User.username == "admin"))
        if not r.scalar_one_or_none():
            db.add(User(
                username        = "admin",
                email           = "admin@amfi.local",
                full_name       = "AMFI Admin",
                hashed_password = bcrypt.hashpw(b"amfi2024!", bcrypt.gensalt()).decode(),
                role            = "admin",
            ))
            logger.warning("Default admin created: admin / amfi2024! — CHANGE THIS PASSWORD")

        # SLA policies
        defaults = [
            (Priority.P1, settings.sla_p1_response, settings.sla_p1_resolve),
            (Priority.P2, settings.sla_p2_response, settings.sla_p2_resolve),
            (Priority.P3, settings.sla_p3_response, settings.sla_p3_resolve),
            (Priority.P4, settings.sla_p4_response, settings.sla_p4_resolve),
        ]
        for priority, resp, res in defaults:
            r = await db.execute(
                select(SLAPolicy).where(SLAPolicy.priority == priority, SLAPolicy.customer == None)
            )
            if not r.scalar_one_or_none():
                db.add(SLAPolicy(priority=priority, response_minutes=resp, resolve_minutes=res))

        await db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _nms_task, _monitor_task
    logger.info("Starting AMFI Agent v4...")

    # Database
    await init_db()
    await _seed_defaults()
    logger.info("Database ready")

    # Check AI engine
    from backend.agent.llm import check_ollama
    ollama = await check_ollama()
    if ollama["running"]:
        if ollama["model_available"]:
            logger.info("Ollama: model '%s' ready", settings.ollama_model)
        else:
            logger.warning(
                "Ollama running but model '%s' not found — run: ollama pull %s",
                settings.ollama_model, settings.ollama_model
            )
    else:
        logger.warning("Ollama not running. Install: https://ollama.ai then: ollama pull %s", settings.ollama_model)
        if settings.anthropic_api_key:
            logger.info("Claude API configured as fallback")
        else:
            logger.warning("No AI engine — diagnostics will not be interpreted")

    # Start NMS polling
    _nms_task = asyncio.create_task(_nms_scheduler())
    logger.info("NMS scheduler started — polling every %ds", settings.nms_poll_seconds)

    # Seed default threshold rules and start monitoring scheduler
    from backend.services.monitoring.thresholds import seed_default_rules
    from backend.database import AsyncSessionLocal
    async with AsyncSessionLocal() as _db:
        await seed_default_rules(_db)
    _monitor_task = asyncio.create_task(_monitoring_scheduler())
    logger.info("Monitoring scheduler started — polling interval min 30s per host")

    # Fix #12: Production security warnings
    if not settings.auth_enabled:
        logger.warning(
            "⚠️  AUTH_ENABLED=false — JWT authentication is OFF. "
            "Set AUTH_ENABLED=true in .env before production deployment."
        )
    if settings.secret_key == "change-me-generate-with-openssl-rand-hex-32":
        logger.warning(
            "⚠️  SECRET_KEY is still the default value. "
            "Generate a real key with: openssl rand -hex 32"
        )
    if settings.cors_origins == "*":
        logger.warning(
            "⚠️  CORS_ORIGINS=* — all origins allowed. "
            "Set CORS_ORIGINS=https://your-domain.com in production."
        )

    logger.info("AMFI Agent v4 ready at http://%s:%d", settings.api_host, settings.api_port)
    logger.info("API docs: http://%s:%d/docs", settings.api_host, settings.api_port)

    yield

    # Shutdown
    if _nms_task:
        _nms_task.cancel()
    if _monitor_task:
        _monitor_task.cancel()
    logger.info("AMFI Agent v4 stopped")


app = FastAPI(
    title       = "AMFI v4 — Autonomous NOC Agent",
    description = "Purpose-built autonomous NOC incident resolution agent",
    version     = "4.0.0",
    lifespan    = lifespan,
    docs_url    = "/docs",
    redoc_url   = "/redoc",
)

# ── App-layer rate limiter (Fix #11) ──────────────────────────────────────────
# No global default — limits are applied per-endpoint only (e.g. login: 10/min).
# Works regardless of whether nginx is in front of the app.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Fix #5: CORS restricted to configured origin(s) in production.
# Set CORS_ORIGINS=https://your-noc.company.com in .env; defaults to "*" (dev).
_cors_origins = (
    [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    if settings.cors_origins != "*"
    else ["*"]
)
app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(
    CORSMiddleware,
    allow_origins     = _cors_origins,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
    allow_credentials = True,
)

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"]        = "DENY"
    return response


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """JWT gate — only active when AUTH_ENABLED=true in settings."""
    if not settings.auth_enabled:
        return await call_next(request)

    # Paths that don't need a token
    # NOTE: /ws is intentionally NOT listed here — the WS endpoint validates
    # the token itself via the ?token= query parameter.
    _PUBLIC = (
        "/api/auth/login",
        "/api/auth/status",
        "/api/health",
        "/docs",
        "/redoc",
        "/openapi.json",
    )
    path = request.url.path
    if any(path == p or path.startswith(p + "/") for p in _PUBLIC):
        return await call_next(request)

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return JSONResponse({"detail": "Authentication required"}, status_code=401)

    from jose import jwt, JWTError
    try:
        payload = jwt.decode(auth[7:], settings.secret_key, algorithms=["HS256"])
        request.state.user = payload.get("sub", "")
    except JWTError:
        return JSONResponse({"detail": "Invalid or expired token"}, status_code=401)

    return await call_next(request)


# API routes
app.include_router(router,          prefix="/api")
app.include_router(auth_router,     prefix="/api")
app.include_router(webhooks_router, prefix="/api")
app.include_router(ws_router)  # /ws (no prefix — WebSocket path must be exact)

# Serve React frontend if built
# Check multiple candidate locations so the project works regardless of folder layout
_candidates = [
    os.path.join(os.path.dirname(__file__), "..", "frontend", "dist"),          # amfi_v4_complete/frontend/dist
    os.path.join(os.path.dirname(__file__), "..", "..", "amfi_v4_frontend", "dist"),  # sibling amfi_v4_frontend/dist
    os.path.join(os.path.dirname(__file__), "..", "dist"),                       # amfi_v4_complete/dist
]
FRONTEND_DIST = next((p for p in _candidates if os.path.isdir(p)), None) or _candidates[0]
if os.path.exists(FRONTEND_DIST):
    assets_dir = os.path.join(FRONTEND_DIST, "assets")
    if os.path.exists(assets_dir):
        # Serve hashed assets with long cache — filenames change on rebuild so this is safe
        @app.get("/assets/{file_path:path}", include_in_schema=False)
        async def serve_asset(file_path: str):
            full = os.path.join(assets_dir, file_path)
            if not os.path.exists(full):
                from fastapi import HTTPException
                raise HTTPException(404)
            resp = FileResponse(full)
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return resp

    @app.get("/", include_in_schema=False)
    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str = ""):
        # Don't intercept API routes
        if full_path.startswith("api/") or full_path in ("docs", "redoc", "openapi.json"):
            from fastapi import HTTPException
            raise HTTPException(404)
        index = os.path.join(FRONTEND_DIST, "index.html")
        if os.path.exists(index):
            resp = FileResponse(index)
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return resp
        from fastapi import HTTPException
        raise HTTPException(404, "Frontend not built. Run: cd frontend && npm run build")

    logger.info("Frontend serving from %s", FRONTEND_DIST)
