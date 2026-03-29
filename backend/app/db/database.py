"""
GenAI DocQA Platform — Async Database Engine & Session Factory

This file is the foundation of all database interaction.
Everything that touches PostgreSQL goes through what's defined here.

THREE THINGS DEFINED HERE:
    1. engine          — the async connection pool to PostgreSQL
    2. AsyncSessionLocal — session factory (one session per request)
    3. Base            — parent class all SQLAlchemy models inherit from

THE ASYNC DIFFERENCE:
    Sync engine:  await db.execute() BLOCKS the thread
                  → only 1 request handled at a time while DB query runs
    Async engine: await db.execute() yields control to event loop
                  → server handles other requests while DB query runs
                  → 10x more concurrent throughput

THE CRITICAL SETTING:
    expire_on_commit=False
    Without this: accessing any model attribute after commit() crashes
    With this: model attributes remain readable after commit()
    This is MANDATORY for async SQLAlchemy

USAGE:
    # In dependencies.py (already done):
    async def get_db():
        async with AsyncSessionLocal() as session:
            yield session

    # In any route:
    @router.get("/users")
    async def get_users(db: AsyncSession = Depends(get_db)):
        result = await db.execute(select(User))
        return result.scalars().all()
"""

import structlog
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

log = structlog.get_logger(__name__)


# ================================================================
# 1. ASYNC ENGINE — The Connection Pool
# ================================================================

engine = create_async_engine(
    # Connection string from settings
    # MUST be postgresql+asyncpg:// — validated in config.py
    url=settings.DATABASE_URL,

    # ── Connection Pool Settings ──────────────────────────────
    # The pool keeps connections open and reuses them
    # Opening a new connection takes ~5ms — pooling avoids this

    # Maximum number of connections kept in the pool
    # 20 means up to 20 simultaneous DB operations
    pool_size=settings.DB_POOL_SIZE,

    # Extra connections allowed when pool is full
    # If pool_size=20 and max_overflow=10 → max 30 simultaneous connections
    max_overflow=settings.DB_MAX_OVERFLOW,

    # How long to wait (seconds) for a connection from the pool
    # If all 30 connections are busy → wait 30s → raise TimeoutError
    pool_timeout=settings.DB_POOL_TIMEOUT,

    # Recycle connections after this many seconds
    # Prevents issues with PostgreSQL closing idle connections
    pool_recycle=settings.DB_POOL_RECYCLE,

    # Test connections before using them
    # If a connection was closed by PostgreSQL → get a fresh one
    # Prevents "connection closed" errors on idle connections
    pool_pre_ping=True,

    # ── Logging Settings ──────────────────────────────────────
    # echo=True prints every SQL statement — useful for debugging
    # echo=False in production — too noisy
    echo=settings.DEBUG,

    # echo_pool=True prints connection pool events (checkout, checkin)
    # Only useful when debugging connection pool issues
    echo_pool=False,
)


# ================================================================
# 2. SESSION FACTORY — Creates Sessions Per Request
# ================================================================

AsyncSessionLocal = async_sessionmaker(
    # Which engine to use
    bind=engine,

    # ── CRITICAL SETTING ──────────────────────────────────────
    # expire_on_commit=False
    #
    # DEFAULT BEHAVIOR (expire_on_commit=True):
    #   After session.commit(), SQLAlchemy marks ALL loaded objects
    #   as "expired". The next attribute access triggers a new DB query.
    #   In async code, this query needs await — but attribute access
    #   can't be awaited → MissingGreenlet error (very confusing)
    #
    # Example of the crash:
    #   user = await db.get(User, user_id)
    #   await db.commit()
    #   print(user.email)  # ← CRASH: MissingGreenlet
    #                      # because SQLAlchemy tries to do a sync
    #                      # DB query to refresh the expired object
    #
    # WITH expire_on_commit=False:
    #   Objects keep their values after commit()
    #   No automatic refresh → no sync DB query → no crash
    #   We manually refresh when needed with await db.refresh(obj)
    #
    # THIS IS MANDATORY FOR ASYNC SQLALCHEMY — NOT OPTIONAL
    expire_on_commit=False,

    # Session class to use
    class_=AsyncSession,

    # Don't automatically begin a transaction on session creation
    # We control transactions explicitly
    autobegin=True,

    # Don't automatically flush before queries
    # We control flushes explicitly with await db.flush()
    autoflush=False,
)


# ================================================================
# 3. BASE CLASS — Parent for All SQLAlchemy Models
# ================================================================

class Base(DeclarativeBase):
    """
    Base class for all SQLAlchemy database models.

    All models inherit from this:
        class User(Base):
            __tablename__ = "users"
            ...

        class Document(Base):
            __tablename__ = "documents"
            ...

    WHY inherit from Base?
        SQLAlchemy uses Base.metadata to track all table definitions.
        Alembic reads Base.metadata to know what the schema should look like.
        Without inheriting from Base, the model is invisible to both.

    DeclarativeBase (SQLAlchemy 2.0 style) vs declarative_base() (1.x style):
        Old:  Base = declarative_base()           # SQLAlchemy 1.x
        New:  class Base(DeclarativeBase): pass   # SQLAlchemy 2.0
        We use the new 2.0 style — it's the modern standard.
    """
    pass


# ================================================================
# ENGINE EVENT LISTENERS
# Hooks that run on connection events
# ================================================================

@event.listens_for(engine.sync_engine, "connect")
def on_connect(dbapi_connection, connection_record):
    """
    Runs every time a new connection is opened from the pool.

    We use this to set PostgreSQL session-level settings:
        - Search path for schemas
        - Statement timeout (prevent runaway queries)

    Note: event.listens_for uses the sync engine internally —
    this is intentional and the correct pattern for asyncpg.
    """
    # Set statement timeout to 30 seconds
    # Prevents a single slow query from blocking a connection forever
    # A query running > 30s is likely a bug or runaway operation
    cursor = dbapi_connection.cursor()
    cursor.execute("SET statement_timeout = '30s'")
    cursor.close()

    log.debug("database_connection_opened")


@event.listens_for(engine.sync_engine, "checkout")
def on_checkout(dbapi_connection, connection_record, connection_proxy):
    """
    Runs every time a connection is borrowed from the pool.
    Useful for debugging connection pool exhaustion.
    """
    log.debug("database_connection_checked_out")


@event.listens_for(engine.sync_engine, "checkin")
def on_checkin(dbapi_connection, connection_record):
    """
    Runs every time a connection is returned to the pool.
    """
    log.debug("database_connection_checked_in")