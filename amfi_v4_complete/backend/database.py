"""AMFI v4 — Async SQLAlchemy database setup (SQLite via aiosqlite)."""
import logging
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
    async_sessionmaker,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text

from backend.config import get_settings

logger   = logging.getLogger("amfi.db")
settings = get_settings()

_IS_SQLITE = "sqlite" in settings.database_url

# Create engine — supports both SQLite+aiosqlite and PostgreSQL+asyncpg
_connect_args = {}
_engine_kwargs: dict = {}

if _IS_SQLITE:
    # NullPool: each session gets its own fresh connection → no stale lock state
    # timeout=30: wait up to 30s when DB is locked before raising OperationalError
    from sqlalchemy.pool import NullPool
    _connect_args = {"check_same_thread": False, "timeout": 30}
    _engine_kwargs = {"poolclass": NullPool}

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    connect_args=_connect_args,
    **_engine_kwargs,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    # autoflush=False prevents implicit DB writes (and write-lock acquisition)
    # before SELECT statements.  All flushes are driven by explicit db.commit().
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    pass


async def init_db() -> None:
    """Create all tables on first run. Also sets SQLite WAL mode and pragmas."""
    import backend.models.models as _models  # noqa: F401 — registers all ORM classes
    async with engine.begin() as conn:
        # Enable WAL mode for better concurrency (must be set before table creation)
        if _IS_SQLITE:
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            await conn.execute(text("PRAGMA synchronous=NORMAL"))
            await conn.execute(text("PRAGMA busy_timeout=30000"))
            await conn.execute(text("PRAGMA foreign_keys=ON"))
        await conn.run_sync(Base.metadata.create_all)

        # ── SQLite column-add migrations ─────────────────────────────────────
        # Safe to run every startup: ALTER TABLE is a no-op if the column exists
        # (the except catches "duplicate column name" from SQLite).
        if _IS_SQLITE:
            _v3_cols = [
                ("monitored_hosts", "snmp_v3_user",          "VARCHAR(100)"),
                ("monitored_hosts", "snmp_v3_auth_protocol", "VARCHAR(10) DEFAULT 'SHA'"),
                ("monitored_hosts", "snmp_v3_auth_key",      "VARCHAR(255)"),
                ("monitored_hosts", "snmp_v3_priv_protocol", "VARCHAR(10) DEFAULT 'AES'"),
                ("monitored_hosts", "snmp_v3_priv_key",      "VARCHAR(255)"),
            ]
            for tbl, col, coltype in _v3_cols:
                try:
                    await conn.execute(text(f"ALTER TABLE {tbl} ADD COLUMN {col} {coltype}"))
                except Exception:
                    pass  # column already exists — safe to ignore

    logger.info("Database initialised: %s", settings.database_url.split("@")[-1])


async def get_db():
    """FastAPI dependency — yields an async database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
