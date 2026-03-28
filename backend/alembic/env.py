"""
Alembic environment configuration.

This file runs every time you execute an alembic command:
    alembic upgrade head
    alembic downgrade -1
    alembic revision --autogenerate

THE ASYNC BRIDGE PROBLEM:
    Alembic was designed for synchronous SQLAlchemy.
    Our app uses async SQLAlchemy (create_async_engine).
    These don't work together directly.

THE SOLUTION:
    asyncio.run() → async connection → conn.run_sync() → Alembic runs sync inside

This is the official Alembic async pattern from their documentation.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

# ── Import our app's settings and Base ───────────────────────
# settings.DATABASE_URL = the connection string from .env
# Base.metadata = all table definitions from all our models
from app.config import settings
from app.db.database import Base

# ── Import ALL models here ────────────────────────────────────
# WHY? Alembic autogenerate works by comparing:
#   Python models (what schema SHOULD look like)
#   vs Database (what schema ACTUALLY looks like)
#
# If a model is not imported here → Alembic can't see it
# → autogenerate produces empty migrations (silent failure)
#
# As we add models in each phase, we add imports here too.
# Phase 1: no models yet (added in Phase 2+)
# Phase 2: User, LLMKey
# Phase 3: Document, DocumentChunk
# (we import them all here as they get created)

# These imports will be uncommented as phases progress:
# from app.models.user import User                    # Phase 2
# from app.models.llm_key import LLMKey              # Phase 2
# from app.models.document import Document            # Phase 3
# from app.models.chunk import DocumentChunk          # Phase 3

# ── Alembic Config object ─────────────────────────────────────
# Gives access to values in alembic.ini
config = context.config

# ── Set up logging from alembic.ini ──────────────────────────
# Reads the [loggers], [handlers], [formatters] sections
# This makes Alembic print migration progress to console
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── Tell Alembic what our schema should look like ────────────
# Base.metadata contains all table definitions from all models
# that inherit from Base (our SQLAlchemy declarative base)
# This is what autogenerate compares against the actual database
target_metadata = Base.metadata


def do_run_migrations(connection) -> None:
    """
    Run migrations synchronously.

    This function runs INSIDE the async connection via run_sync().
    Alembic itself is synchronous — this is where it actually works.

    Args:
        connection: a synchronous SQLAlchemy connection
                    (extracted from the async connection by run_sync)
    """
    context.configure(
        # The database connection to use
        connection=connection,

        # What the schema SHOULD look like (our Python models)
        target_metadata=target_metadata,

        # Compare server defaults (e.g. server_default=func.now())
        # Without this, autogenerate misses server-side defaults
        compare_server_default=True,

        # Compare column types strictly
        # Without this, autogenerate misses type changes
        compare_type=True,

        # Schema to use (None = default public schema)
        include_schemas=False,

        # Naming convention for constraints
        # This ensures FK, unique, check constraints have consistent names
        # Prevents "unnamed constraint" issues during migrations
        render_as_batch=False,
    )

    # Run the actual migration
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """
    Create async engine and run migrations through it.

    THE BRIDGE:
        Alembic (sync) needs a sync connection.
        Our engine is async.
        conn.run_sync(do_run_migrations) bridges the gap:
            - conn is async
            - run_sync() extracts a sync connection from it
            - passes that sync connection to do_run_migrations()
            - Alembic runs normally inside do_run_migrations()
    """
    # Create a fresh async engine using DATABASE_URL from settings
    # NOT from alembic.ini — settings is the single source of truth
    connectable = create_async_engine(
        settings.DATABASE_URL,
        # Echo=False in migrations — we don't need to see every SQL
        echo=False,
    )

    # Connect to the database asynchronously
    async with connectable.connect() as connection:
        # THE KEY LINE: run_sync() takes a sync callable and
        # passes it a sync version of our async connection
        # This is how Alembic (sync) works inside async SQLAlchemy
        await connection.run_sync(do_run_migrations)

    # Dispose the engine after migrations complete
    # Closes all connections in the pool — clean shutdown
    await connectable.dispose()


def run_migrations_online() -> None:
    """
    Entry point for running migrations.

    Called by Alembic when you run:
        alembic upgrade head
        alembic downgrade -1
        alembic revision --autogenerate

    asyncio.run() starts the event loop and runs our async
    migration function synchronously from Alembic's perspective.
    """
    asyncio.run(run_async_migrations())


# ── Run migrations ────────────────────────────────────────────
# context.is_offline_mode() = True when running with --sql flag
# (generates SQL script instead of running against DB)
# We only support online mode (running directly against DB)
if context.is_offline_mode():
    raise RuntimeError(
        "Offline mode (--sql) is not supported in this project. "
        "Run migrations directly against the database: "
        "alembic upgrade head"
    )
else:
    run_migrations_online()