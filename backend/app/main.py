"""
GenAI DocQA Platform — FastAPI Application Entry Point

This is the heart of the backend. It:
    1. Creates the FastAPI application instance
    2. Defines the lifespan (startup + shutdown logic)
    3. Registers all middleware (CORS, logging, request ID)
    4. Registers all routers (health, auth, documents, etc.)
    5. Mounts the Prometheus metrics endpoint

STARTUP ORDER (matters — each step depends on the previous):
    1. Logging setup         → everything after can produce logs
    2. Database connection   → needs logging to report success/failure
    3. Redis connection      → needs logging to report success/failure
    4. Prometheus setup      → needs logging to report success/failure
    5. App ready             → accept requests

HOW TO RUN:
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
    OR via Docker Compose (recommended):
    docker compose up
"""

import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app

from app.config import settings
from app.monitoring.logger import setup_logging
from app.monitoring.metrics import setup_prometheus

# ── Import routers ────────────────────────────────────────────
# Each router handles a group of related endpoints
# We import them here and register them below
from app.api.v1.health import router as health_router

# Future routers — imported as phases are built:
# from app.api.v1.auth import router as auth_router          # Phase 2
# from app.api.v1.llm_keys import router as llm_keys_router  # Phase 2
# from app.api.v1.documents import router as documents_router # Phase 3
# from app.api.v1.chat import router as chat_router           # Phase 9

log = structlog.get_logger(__name__)


# ================================================================
# LIFESPAN — Startup and Shutdown Logic
# ================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager.

    Code BEFORE yield = startup (runs once before first request)
    Code AFTER yield  = shutdown (runs once after last request)

    WHY @asynccontextmanager instead of @app.on_event("startup")?
        @app.on_event is DEPRECATED in FastAPI 0.93+
        Lifespan is the modern, recommended pattern
        It's cleaner — startup and shutdown in one place
        It's testable — easier to mock in tests

    STARTUP ORDER MATTERS:
        Logging must be first — everything else produces logs
        DB must be before anything that queries the DB
        Redis must be before rate limiting middleware
    """

    # ── STARTUP ──────────────────────────────────────────────

    # Step 1: Setup logging FIRST
    # Everything after this point can produce structured JSON logs
    setup_logging()
    log.info(
        "application_starting",
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT,
        debug=settings.DEBUG,
    )

    # Step 2: Setup Prometheus metrics
    # Defines all metric objects — must happen before any route uses them
    setup_prometheus()
    log.info("prometheus_ready")

    # Step 3: Connect to PostgreSQL
    # Creates the connection pool — reused by all requests
    try:
        from app.db.database import engine
        from app.db.init_db import init_db
        async with engine.begin() as conn:
            # Quick connectivity check — does the DB respond?
            from sqlalchemy import text
            await conn.execute(text("SELECT 1"))
        log.info("database_connected", url=settings.DATABASE_URL.split("@")[-1])

        # Run initialization — enable pgvector extension, seed admin user
        # This is IDEMPOTENT — safe to run multiple times
        await init_db()
        log.info("database_initialized")

    except Exception as e:
        log.error("database_connection_failed", error=str(e))
        # We raise here — if DB is unavailable the app is useless
        # Better to fail at startup than to serve broken responses
        raise

    # Step 4: Connect to Redis
    try:
        import redis.asyncio as aioredis
        redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
        # Quick connectivity check
        await redis_client.ping()
        # Store on app state so middleware and routes can access it
        app.state.redis = redis_client
        log.info("redis_connected", url=settings.REDIS_URL)

    except Exception as e:
        log.error("redis_connection_failed", error=str(e))
        raise

    log.info(
        "application_ready",
        host=settings.BACKEND_HOST,
        port=settings.BACKEND_PORT,
        docs_url="http://localhost:8000/docs",
    )

    # ── APP RUNS HERE ─────────────────────────────────────────
    # Everything above ran at startup
    # yield hands control to FastAPI — it accepts requests now
    # Everything below runs at shutdown
    yield

    # ── SHUTDOWN ─────────────────────────────────────────────

    log.info("application_shutting_down")

    # Close Redis connection cleanly
    if hasattr(app.state, "redis"):
        await app.state.redis.aclose()
        log.info("redis_disconnected")

    # Close database connection pool cleanly
    # This waits for all in-flight queries to complete
    from app.db.database import engine
    await engine.dispose()
    log.info("database_disconnected")

    log.info("application_stopped")


# ================================================================
# FASTAPI APPLICATION INSTANCE
# ================================================================

app = FastAPI(
    # App metadata — appears in Swagger UI (/docs)
    title="GenAI DocQA Platform",
    description=(
        "Production-grade Agentic RAG Document Intelligence System. "
        "Upload documents, ask questions, get sourced answers via "
        "a 10-node LangGraph agent powered by multiple LLM providers."
    ),
    version=settings.APP_VERSION,

    # API documentation URLs
    docs_url="/docs",       # Swagger UI — interactive API explorer
    redoc_url="/redoc",     # ReDoc — clean API reference

    # Lifespan context manager (startup + shutdown)
    lifespan=lifespan,

    # In production, hide docs to avoid exposing API structure
    # We keep them on in development for testing
    openapi_url="/openapi.json" if not settings.is_production else None,
)


# ================================================================
# MIDDLEWARE
# Registered in reverse order of execution
# First added = outermost = first to see request, last to see response
# ================================================================

# ── Middleware 1: CORS ────────────────────────────────────────
# CORS = Cross-Origin Resource Sharing
# WHY? Browser blocks requests from different origins by default
# Frontend (localhost:3000) calling Backend (localhost:8000) = blocked
# This middleware tells browser: "these origins are allowed"
app.add_middleware(
    CORSMiddleware,

    # Which frontend origins can call this backend
    # In production: replace with your actual frontend domain
    allow_origins=settings.ALLOWED_ORIGINS,

    # Allow cookies and Authorization headers to be sent
    allow_credentials=True,

    # Which HTTP methods are allowed from frontend
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],

    # Which headers frontend can send
    # Authorization: Bearer <token> must be in this list
    allow_headers=["*"],

    # How long browsers cache the CORS preflight response (seconds)
    # 3600 = 1 hour — reduces preflight OPTIONS requests
    max_age=3600,
)


# ── Middleware 2: Request ID ──────────────────────────────────
# Attaches a unique ID to every request
# This ID appears in ALL log lines for that request
# So you can trace one request across all logs:
#   "show me all logs for request abc-123"
@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """
    Generate a unique request ID and attach it to every request.

    The request ID flows through:
        - Request headers (X-Request-ID)
        - Structlog context (appears in all log lines)
        - Response headers (client can use it for support tickets)
    """
    # Check if client sent a request ID (useful for distributed tracing)
    # If not, generate one
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))

    # Bind request_id to structlog context
    # Every log.info() / log.error() in this request automatically includes it
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        method=request.method,
        path=request.url.path,
    )

    # Process the request
    response = await call_next(request)

    # Add request ID to response header
    # Client can use this to reference a specific request in support
    response.headers["X-Request-ID"] = request_id

    # Clear the structlog context after request completes
    structlog.contextvars.clear_contextvars()

    return response


# ── Middleware 3: Request Logging ─────────────────────────────
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """
    Log every incoming request and its response.

    Logs:
        - Method, path, client IP (incoming)
        - Status code, response time (outgoing)

    This gives you a complete audit trail of all API activity.
    """
    import time

    start_time = time.perf_counter()

    log.info(
        "request_started",
        method=request.method,
        path=request.url.path,
        client_ip=request.client.host if request.client else "unknown",
    )

    response = await call_next(request)

    duration_ms = (time.perf_counter() - start_time) * 1000

    log.info(
        "request_completed",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=round(duration_ms, 2),
    )

    # Add response time header — useful for performance debugging
    response.headers["X-Response-Time"] = f"{duration_ms:.2f}ms"

    return response


# ================================================================
# EXCEPTION HANDLERS
# Global error handling — catch unhandled exceptions
# ================================================================

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Catch any unhandled exception and return a clean JSON error.

    WHY? Without this, FastAPI returns a raw 500 error with a
    Python traceback — exposing internal implementation details.
    This returns a clean JSON response instead.

    In development: include error details for debugging
    In production: generic message only — never expose internals
    """
    log.error(
        "unhandled_exception",
        path=request.url.path,
        method=request.method,
        error=str(exc),
        error_type=type(exc).__name__,
        exc_info=True,  # includes full traceback in logs
    )

    # In development: show the error (helps debugging)
    # In production: hide the error (security)
    detail = str(exc) if settings.is_development else "Internal server error"

    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "detail": detail,
            "request_id": request.headers.get("X-Request-ID", "unknown"),
        },
    )


# ================================================================
# ROUTERS
# Each router handles a group of related endpoints
# prefix="/api/v1" means all routes become /api/v1/...
# ================================================================

# Health check endpoints — Phase 1
# GET /api/v1/health  → liveness check
# GET /api/v1/ready   → readiness check (DB + Redis)
app.include_router(
    health_router,
    prefix="/api/v1",
    tags=["Health"],
)

# Future routers added as phases complete:
# app.include_router(auth_router,      prefix="/api/v1", tags=["Auth"])
# app.include_router(llm_keys_router,  prefix="/api/v1", tags=["LLM Keys"])
# app.include_router(documents_router, prefix="/api/v1", tags=["Documents"])
# app.include_router(chat_router,      prefix="/api/v1", tags=["Chat"])


# ================================================================
# PROMETHEUS METRICS ENDPOINT
# ================================================================

# Mount the Prometheus metrics ASGI app at /metrics
# Prometheus scrapes this endpoint every 15 seconds
# Returns all metric values in Prometheus text format
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


# ================================================================
# ROOT ENDPOINT
# ================================================================

@app.get("/", include_in_schema=False)
async def root():
    """
    Root endpoint — redirects to docs.
    Not included in OpenAPI schema (include_in_schema=False).
    """
    return {
        "name": "GenAI DocQA Platform",
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "health": "/api/v1/health",
        "metrics": "/metrics",
    }