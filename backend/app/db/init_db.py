"""
GenAI DocQA Platform — Database Initialization

Runs ONCE at startup before the app accepts any requests.
Called from main.py lifespan startup sequence.

WHAT THIS FILE DOES:
    1. Enable PostgreSQL extensions (pgvector, uuid-ossp)
    2. Create a default admin user (so you can log in immediately)

IMPORTANT — VECTOR STORE ABSTRACTION:
    This file contains pgvector-specific setup (CREATE EXTENSION vector).
    We use pgvector as the default vector store backend.

    The system is designed to support multiple vector stores:
        VECTOR_STORE_BACKEND=pgvector   ← default (Phase 4)
        VECTOR_STORE_BACKEND=pinecone   ← future
        VECTOR_STORE_BACKEND=chroma     ← future
        VECTOR_STORE_BACKEND=qdrant     ← future

    Switching vector stores (real-world migration process):
        Step 1: Export embeddings from pgvector
        Step 2: Upload to new vector store
        Step 3: Change VECTOR_STORE_BACKEND env var
        Step 4: Update vector_store.py implementation
        Embeddings stay the SAME — only storage changes.

    The abstraction layer lives in:
        app/services/vector_store.py (built in Phase 4)
        class VectorStore(ABC): upsert, search, delete
        class PgVectorStore(VectorStore): pgvector implementation
        class PineconeStore(VectorStore): Pinecone implementation

    When you switch to Pinecone:
        → This extension setup is no longer needed
        → Just change VECTOR_STORE_BACKEND=pinecone
        → Nothing else changes in the rest of the codebase

IDEMPOTENT:
    Every operation uses IF NOT EXISTS or ON CONFLICT DO NOTHING
    Safe to run multiple times — won't fail or duplicate data
"""

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.database import engine

log = structlog.get_logger(__name__)


async def init_db() -> None:
    """
    Initialize the database on first startup.

    Called from main.py lifespan:
        async with engine.begin() as conn:
            await init_db()

    Everything here is IDEMPOTENT:
        CREATE EXTENSION IF NOT EXISTS → safe to run multiple times
        ON CONFLICT DO NOTHING         → safe to run multiple times
    """
    async with engine.begin() as conn:

        # ── Step 1: Enable PostgreSQL Extensions ──────────────
        await _enable_extensions(conn)

        # ── Step 2: Create default admin user ─────────────────
        await _seed_admin_user(conn)

    log.info("database_initialization_complete")


async def _enable_extensions(conn) -> None:
    """
    Enable required PostgreSQL extensions.

    EXTENSIONS:
        vector    → pgvector — adds VECTOR column type for embeddings
                    Required for semantic search with pgvector backend
                    NOT needed when using Pinecone/Chroma/Qdrant

        uuid-ossp → adds gen_random_uuid() function
                    Used for UUID primary keys in all tables

    IF NOT EXISTS:
        Makes this safe to run on every startup
        If extension already exists → skip silently, no error

    VECTOR STORE NOTE:
        The `vector` extension is pgvector-specific.
        If VECTOR_STORE_BACKEND changes to pinecone/chroma/qdrant:
            → This extension is harmless but unused
            → Or add a conditional: if settings.VECTOR_STORE_BACKEND == "pgvector"
        For now pgvector is our default — we always enable it.
    """
    log.info("enabling_postgresql_extensions")

    # pgvector extension — adds VECTOR(1536) column type
    # This MUST run before any migration that creates a VECTOR column
    # If this is skipped → migration fails with: type "vector" does not exist
    await conn.execute(
        text("CREATE EXTENSION IF NOT EXISTS vector")
    )
    log.info("extension_enabled", extension="vector")

    # uuid-ossp extension — adds gen_random_uuid()
    # Used for UUID primary keys: id UUID DEFAULT gen_random_uuid()
    await conn.execute(
        text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    )
    log.info("extension_enabled", extension="uuid-ossp")

    # pg_trgm extension — trigram similarity for fuzzy text search
    # Used for searching document titles, tags
    await conn.execute(
        text("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    )
    log.info("extension_enabled", extension="pg_trgm")


async def _seed_admin_user(conn) -> None:
    """
    Create the default admin user on first startup.

    WHY?
        When you deploy for the first time, the database is empty.
        No users exist. You can't log in through the UI.
        This creates one admin account automatically so you can
        immediately log in and start using the system.

    CREDENTIALS (from .env):
        Email:    settings.ADMIN_EMAIL    (default: admin@docqa.local)
        Password: settings.ADMIN_PASSWORD (default: admin123!)

    IMPORTANT:
        Change the default password immediately after first login.
        The password is HASHED with bcrypt before storing.
        We never store plain text passwords.

    ON CONFLICT DO NOTHING:
        If admin already exists (app restarted) → skip silently
        No duplicate key error, no exception

    NOTE: Full auth implementation (JWT, bcrypt, User model) is in Phase 2.
    This runs a raw SQL INSERT because the User model doesn't exist yet.
    In Phase 2, this will be replaced with proper ORM-based seeding.
    """
    log.info("seeding_admin_user", email=settings.ADMIN_EMAIL)

    # Check if the users table exists yet
    # On very first startup before migrations run, it won't exist
    table_exists = await conn.execute(
        text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'users'
            )
        """)
    )

    if not table_exists.scalar():
        log.info(
            "users_table_not_found_skipping_seed",
            hint="Run 'alembic upgrade head' to create tables"
        )
        return

    # Hash the admin password with bcrypt
    # WHY bcrypt? It's intentionally slow — makes brute force attacks hard
    # cost=12 = 2^12 = 4096 iterations — industry standard
    try:
        from passlib.context import CryptContext
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        hashed_password = pwd_context.hash(settings.ADMIN_PASSWORD)
    except ImportError:
        log.warning(
            "passlib_not_installed_skipping_admin_seed",
            hint="Install passlib[bcrypt] to enable admin seeding"
        )
        return

    # Insert admin user
    # ON CONFLICT (email) DO NOTHING:
    #   If admin already exists → skip silently
    #   Safe to run on every startup
    await conn.execute(
        text("""
            INSERT INTO users (
                id,
                email,
                hashed_password,
                full_name,
                role,
                is_active,
                created_at,
                updated_at
            )
            VALUES (
                gen_random_uuid(),
                :email,
                :hashed_password,
                :full_name,
                'admin',
                true,
                NOW(),
                NOW()
            )
            ON CONFLICT (email) DO NOTHING
        """),
        {
            "email": settings.ADMIN_EMAIL,
            "hashed_password": hashed_password,
            "full_name": "System Administrator",
        }
    )

    log.info(
        "admin_user_seeded",
        email=settings.ADMIN_EMAIL,
        note="Change password immediately after first login",
    )


async def check_db_health() -> dict:
    """
    Check database health and return status info.

    Used by the /ready endpoint to verify DB is accessible.

    Returns:
        dict with keys: connected (bool), latency_ms (float),
                        extensions (list), version (str)
    """
    import time

    try:
        start = time.perf_counter()

        async with engine.connect() as conn:
            # Check basic connectivity
            await conn.execute(text("SELECT 1"))

            # Check pgvector is enabled
            vector_result = await conn.execute(
                text("""
                    SELECT installed_version
                    FROM pg_available_extensions
                    WHERE name = 'vector'
                    AND installed_version IS NOT NULL
                """)
            )
            vector_version = vector_result.scalar()

            # Get PostgreSQL version
            version_result = await conn.execute(
                text("SELECT version()")
            )
            pg_version = version_result.scalar()

        latency_ms = (time.perf_counter() - start) * 1000

        return {
            "connected": True,
            "latency_ms": round(latency_ms, 2),
            "pgvector_enabled": vector_version is not None,
            "pgvector_version": vector_version,
            "postgresql_version": pg_version,
            "vector_store_backend": "pgvector",
        }

    except Exception as e:
        log.error("database_health_check_failed", error=str(e))
        return {
            "connected": False,
            "error": str(e),
            "latency_ms": None,
        }