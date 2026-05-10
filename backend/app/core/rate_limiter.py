"""
app/core/rate_limiter.py — Redis sliding window rate limiting middleware.

Why sliding window over fixed window:
    Fixed window resets every 60s on the clock.
    A user can send 60 requests at 11:00:59 and 60 at 11:01:01
    — 120 requests in 2 seconds. The reset window is exploitable.

    Sliding window always looks back exactly 60 seconds from NOW.
    No exploit possible. Always exactly N requests per any 60s period.

How it works (Redis sorted set):
    Key:   "rl:{user_id}:{endpoint_prefix}"
    Items: {timestamp → score} — timestamp IS the score
    Every request:
        1. Remove items older than window (ZREMRANGEBYSCORE)
        2. Add current timestamp (ZADD)
        3. Count items (ZCARD)
        4. Set key expiry (EXPIRE)
        5. If count > limit → 429 Too Many Requests

All 4 Redis commands run in one atomic pipeline — no race conditions.
"""

from __future__ import annotations

import time

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

import structlog

log = structlog.get_logger(__name__)

# ─────────────────────────────────────────────────────────────
# RATE LIMIT CONFIGURATION
# ─────────────────────────────────────────────────────────────

# Window size in seconds — we look back this far on every request
WINDOW_SECONDS = 60

# Per-endpoint limits — requests allowed per WINDOW_SECONDS
# Keyed by URL path prefix for fast matching
ENDPOINT_LIMITS: dict[str, int] = {
    "/api/v1/chat":    20,   # LLM generation — most expensive, strictest limit
    "/api/v1/query":   30,   # RAG queries — slightly cheaper than full chat
    "/api/v1/upload":  10,   # Document upload + processing — heavy background work
    "/api/v1/auth":    20,   # Login/register — prevent brute force attacks
}

# Default limit for any endpoint not listed above
DEFAULT_LIMIT = 60

# Paths that are NEVER rate limited
# Health checks and metrics must always be reachable by monitoring tools
EXEMPT_PATHS = {
    "/api/v1/health",
    "/api/v1/ready",
    "/metrics",
    "/docs",
    "/openapi.json",
    "/redoc",
}


def _get_limit_for_path(path: str) -> int:
    """
    Look up the rate limit for a given request path.

    Checks each endpoint prefix in order — first match wins.
    Falls back to DEFAULT_LIMIT if no prefix matches.

    Example:
        "/api/v1/chat/stream" → matches "/api/v1/chat" → limit 20
        "/api/v1/documents"   → no match             → limit 60
    """
    for prefix, limit in ENDPOINT_LIMITS.items():
        if path.startswith(prefix):
            return limit
    return DEFAULT_LIMIT


def _make_redis_key(user_identifier: str, path: str) -> str:
    """
    Build the Redis key for this user + endpoint combination.

    Format: "rl:{identifier}:{path_prefix}"

    We use path prefix (not full path) so all chat variants
    share one counter:
        /api/v1/chat          → "rl:user123:/api/v1/chat"
        /api/v1/chat/stream   → "rl:user123:/api/v1/chat"

    user_identifier is either the JWT user_id (authenticated)
    or the client IP address (unauthenticated).
    """
    # Match the same prefix logic used in _get_limit_for_path
    for prefix in ENDPOINT_LIMITS:
        if path.startswith(prefix):
            return f"rl:{user_identifier}:{prefix}"
    return f"rl:{user_identifier}:{path}"


def _get_user_identifier(request: Request) -> str:
    """
    Extract a stable identifier for rate limiting.

    Priority:
    1. user_id from JWT (set by get_current_user dependency) — most accurate
       Each user has their own independent rate limit bucket.
    2. X-Forwarded-For header — real IP behind load balancer / proxy
    3. request.client.host — direct client IP (fallback)

    Using IP for unauthenticated requests prevents anonymous abuse
    while still allowing legitimate public endpoints.
    """
    # Check if auth dependency already decoded the JWT and stored user_id
    # This is set in dependencies.py get_current_user() via request.state
    if hasattr(request.state, "user_id") and request.state.user_id:
        return f"user:{request.state.user_id}"

    # Fall back to IP address for unauthenticated requests
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # X-Forwarded-For can be a comma-separated list — take the first IP
        client_ip = forwarded_for.split(",")[0].strip()
        return f"ip:{client_ip}"

    # Direct connection (local dev, no proxy)
    if request.client:
        return f"ip:{request.client.host}"

    return "ip:unknown"


async def check_rate_limit(
    redis_client,
    user_identifier: str,
    path: str,
) -> tuple[bool, int, int]:
    """
    Check and update the sliding window rate limit for this request.

    Uses a Redis sorted set with timestamps as both member and score.
    All operations run in a single atomic pipeline — no race conditions
    even with concurrent requests from the same user.

    Args:
        redis_client: async Redis client from app.state.redis
        user_identifier: "user:abc123" or "ip:1.2.3.4"
        path: request URL path

    Returns:
        tuple of (allowed, current_count, limit)
        allowed      → True if request should proceed
        current_count → how many requests in current window
        limit         → the limit for this endpoint
    """
    limit = _get_limit_for_path(path)
    key = _make_redis_key(user_identifier, path)
    now = time.time()
    window_start = now - WINDOW_SECONDS

    # All 4 operations in one atomic pipeline
    # Pipeline = send all commands to Redis at once, execute atomically
    # This prevents a race condition where two concurrent requests both
    # read count=59, both increment to 60, and both get allowed through
    pipe = redis_client.pipeline()

    # Step 1: Remove all timestamps older than our window
    # ZREMRANGEBYSCORE key -inf window_start
    # Everything with score < window_start is expired
    pipe.zremrangebyscore(key, 0, window_start)

    # Step 2: Add current request timestamp as both member and score
    # Using str(now) as member to handle sub-millisecond duplicates
    pipe.zadd(key, {str(now): now})

    # Step 3: Count how many requests are now in the window
    pipe.zcard(key)

    # Step 4: Set key to expire after the window
    # This auto-cleans idle users from Redis — no memory leak
    pipe.expire(key, WINDOW_SECONDS)

    results = await pipe.execute()

    # results[2] is the ZCARD result — count after adding current request
    current_count: int = results[2]
    allowed = current_count <= limit

    return allowed, current_count, limit


# ─────────────────────────────────────────────────────────────
# MIDDLEWARE CLASS
# ─────────────────────────────────────────────────────────────

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Starlette middleware that enforces per-user sliding window rate limits.

    Registered in main.py:
        app.add_middleware(RateLimitMiddleware)

    Flow for every request:
        1. Check if path is exempt → pass through immediately
        2. Check if Redis is available → pass through if not (fail open)
        3. Get user identifier (JWT user_id or IP)
        4. Run sliding window check
        5. If allowed → add rate limit headers → continue to route
        6. If blocked → return 429 with Retry-After header

    Fail open design: if Redis is down, requests pass through.
    The alternative (fail closed) would take down the entire API
    whenever Redis has a blip. Rate limiting is important but
    not more important than serving requests.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # ── 1. Exempt paths — never rate limited ──────────────
        if path in EXEMPT_PATHS:
            return await call_next(request)

        # ── 2. Skip if Redis not available ────────────────────
        redis_client = getattr(request.app.state, "redis", None)
        if redis_client is None:
            log.warning("rate_limiter_redis_unavailable", path=path)
            return await call_next(request)

        # ── 3. Get user identifier ────────────────────────────
        user_identifier = _get_user_identifier(request)

        # ── 4. Check rate limit ───────────────────────────────
        try:
            allowed, current_count, limit = await check_rate_limit(
                redis_client, user_identifier, path
            )
        except Exception as exc:
            # Redis error — fail open, log warning, continue
            log.warning(
                "rate_limit_check_failed",
                error=str(exc),
                path=path,
                user=user_identifier,
            )
            return await call_next(request)

        # ── 5. Blocked — return 429 ───────────────────────────
        if not allowed:
            log.warning(
                "rate_limit_exceeded",
                user=user_identifier,
                path=path,
                count=current_count,
                limit=limit,
            )

            # Update Prometheus counter (imported lazily to avoid circular import)
            try:
                from app.monitoring.metrics import RATE_LIMIT_HITS_TOTAL
                RATE_LIMIT_HITS_TOTAL.labels(endpoint=path).inc()
            except Exception:
                pass  # metrics are non-critical

            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "message": (
                        f"Too many requests. Limit is {limit} per "
                        f"{WINDOW_SECONDS} seconds."
                    ),
                    "limit": limit,
                    "current": current_count,
                    "retry_after_seconds": WINDOW_SECONDS,
                },
                headers={
                    # Standard rate limit headers — clients can read these
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(time.time()) + WINDOW_SECONDS),
                    "Retry-After": str(WINDOW_SECONDS),
                },
            )

        # ── 6. Allowed — add informational headers and continue ──
        remaining = max(0, limit - current_count)
        response = await call_next(request)

        # Add rate limit headers to every successful response too
        # Clients can use these to self-throttle before hitting the limit
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(
            int(time.time()) + WINDOW_SECONDS
        )

        return response