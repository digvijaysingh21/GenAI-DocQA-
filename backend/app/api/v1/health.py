"""
GenAI DocQA Platform — Health Check Endpoints

Two endpoints that every production service must have:

    GET /api/v1/health  → Liveness check
        "Is the FastAPI process alive?"
        Never checks external dependencies (DB, Redis)
        Used by: Docker HEALTHCHECK, Kubernetes liveness probe
        Returns 200 always (if process is dead, it can't respond)

    GET /api/v1/ready   → Readiness check
        "Can this instance handle traffic right now?"
        Checks ALL dependencies: PostgreSQL + Redis
        Used by: Kubernetes readiness probe, load balancers
        Returns 200 if all dependencies OK
        Returns 503 if any dependency is down

WHY TWO ENDPOINTS?
    They answer different questions:

    Scenario: PostgreSQL restarting for 30 seconds
        /health → 200 ✅  (process is alive, just can't reach DB)
        /ready  → 503 ❌  (not ready to serve traffic)

    Load balancer sees 503 on /ready → stops sending traffic here
    PostgreSQL comes back → /ready returns 200 → traffic resumes
    All automatic. Zero manual intervention.

    If you only had /health:
        Load balancer would keep sending traffic
        Users would get DB errors for 30 seconds
        With /ready: users see nothing

RESPONSE CODES:
    200 → OK, everything working
    503 → Service Unavailable, stop sending traffic here
"""

import time

import structlog
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app import __version__
from app.config import settings

log = structlog.get_logger(__name__)

# Create the router
# Registered in main.py with: app.include_router(router, prefix="/api/v1")
# This means our routes become: /api/v1/health and /api/v1/ready
router = APIRouter()

# Track when the app started — used to calculate uptime
_start_time = time.time()


# ================================================================
# ENDPOINT 1 — Liveness Check
# ================================================================

@router.get(
    "/health",

    # What this endpoint returns — appears in Swagger UI (/docs)
    summary="Liveness check",
    description=(
        "Check if the FastAPI process is alive and responding. "
        "Does NOT check database or Redis connectivity. "
        "Used by Docker HEALTHCHECK and Kubernetes liveness probe."
    ),

    # Tags group endpoints in Swagger UI
    tags=["Health"],

    # Response codes documented in Swagger UI
    responses={
        200: {"description": "Service is alive"},
    },
)
async def health_check() -> JSONResponse:
    """
    Liveness check — is the process alive?

    This endpoint:
        ✅ Always returns 200 if the process is running
        ❌ Does NOT check PostgreSQL
        ❌ Does NOT check Redis
        ❌ Does NOT check any external service

    WHY no external checks?
        If PostgreSQL is down but the process is alive,
        we DON'T want Docker to restart the container.
        Restarting won't fix PostgreSQL — it's an external issue.
        /ready handles traffic routing when dependencies are down.

    RESPONSE:
        {
            "status": "ok",
            "version": "1.0.0",
            "environment": "development",
            "uptime_seconds": 3600.5
        }
    """
    uptime_seconds = round(time.time() - _start_time, 2)

    log.debug(
        "health_check",
        uptime_seconds=uptime_seconds,
    )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "ok",
            "version": __version__,
            "environment": settings.ENVIRONMENT,
            "uptime_seconds": uptime_seconds,
        },
    )


# ================================================================
# ENDPOINT 2 — Readiness Check
# ================================================================

@router.get(
    "/ready",
    summary="Readiness check",
    description=(
        "Check if this instance can handle traffic. "
        "Checks PostgreSQL and Redis connectivity. "
        "Returns 503 if any dependency is unavailable. "
        "Used by Kubernetes readiness probe and load balancers."
    ),
    tags=["Health"],
    responses={
        200: {"description": "Service is ready to handle traffic"},
        503: {"description": "Service not ready — dependency unavailable"},
    },
)
async def readiness_check(request: Request) -> JSONResponse:
    """
    Readiness check — can this instance handle traffic?

    Checks:
        1. PostgreSQL — can we connect and run a query?
        2. Redis — can we connect and ping?

    If ALL checks pass → 200 OK (send traffic here)
    If ANY check fails → 503 Service Unavailable (stop sending traffic)

    RESPONSE (all ready):
        {
            "status": "ready",
            "checks": {
                "database": {"status": "ok", "latency_ms": 2.3},
                "redis": {"status": "ok", "latency_ms": 0.8}
            },
            "version": "1.0.0"
        }

    RESPONSE (database down):
        {
            "status": "not_ready",
            "checks": {
                "database": {"status": "error", "error": "connection refused"},
                "redis": {"status": "ok", "latency_ms": 0.8}
            },
            "version": "1.0.0"
        }
        HTTP 503
    """
    checks = {}
    all_ready = True

    # ── Check 1: PostgreSQL ───────────────────────────────────
    try:
        from sqlalchemy import text
        from app.db.database import engine

        start = time.perf_counter()

        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

        db_latency_ms = round((time.perf_counter() - start) * 1000, 2)

        checks["database"] = {
            "status": "ok",
            "latency_ms": db_latency_ms,
        }

        log.debug("readiness_db_ok", latency_ms=db_latency_ms)

    except Exception as e:
        all_ready = False
        checks["database"] = {
            "status": "error",
            "error": str(e),
        }
        log.error("readiness_db_failed", error=str(e))

    # ── Check 2: Redis ────────────────────────────────────────
    try:
        if not hasattr(request.app.state, "redis"):
            raise RuntimeError("Redis client not initialized")

        redis = request.app.state.redis

        start = time.perf_counter()
        await redis.ping()
        redis_latency_ms = round((time.perf_counter() - start) * 1000, 2)

        checks["redis"] = {
            "status": "ok",
            "latency_ms": redis_latency_ms,
        }

        log.debug("readiness_redis_ok", latency_ms=redis_latency_ms)

    except Exception as e:
        all_ready = False
        checks["redis"] = {
            "status": "error",
            "error": str(e),
        }
        log.error("readiness_redis_failed", error=str(e))

    # ── Build response ────────────────────────────────────────
    response_body = {
        "status": "ready" if all_ready else "not_ready",
        "checks": checks,
        "version": __version__,
        "environment": settings.ENVIRONMENT,
    }

    # 200 if all checks passed, 503 if any failed
    # Load balancers understand 503 — they stop routing traffic automatically
    http_status = (
        status.HTTP_200_OK
        if all_ready
        else status.HTTP_503_SERVICE_UNAVAILABLE
    )

    log.info(
        "readiness_check_complete",
        status="ready" if all_ready else "not_ready",
        checks={k: v["status"] for k, v in checks.items()},
    )

    return JSONResponse(
        status_code=http_status,
        content=response_body,
    )