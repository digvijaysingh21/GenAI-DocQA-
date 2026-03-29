"""
GenAI DocQA Platform — FastAPI Dependency Injection

This file defines all shared dependencies used across routes.

WHY DEPENDENCY INJECTION?
    Without it: every route writes the same DB/Redis setup code
    With it: define once here, inject anywhere with Depends()

HOW IT WORKS:
    FastAPI sees Depends(get_db) in a route signature
    → calls get_db() automatically before the route runs
    → passes the result into the route function
    → after route finishes, resumes get_db() for cleanup

USAGE:
    from app.dependencies import get_db, get_redis, get_current_user

    @router.get("/documents")
    async def list_documents(
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ):
        ...

TESTING (how to swap real dependencies for fake ones):
    from app.dependencies import get_db
    from app.main import app

    async def override_get_db():
        yield test_db_session   # use test DB instead of real DB

    app.dependency_overrides[get_db] = override_get_db
"""

from typing import AsyncGenerator

import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.database import AsyncSessionLocal

log = structlog.get_logger(__name__)


# ================================================================
# DEPENDENCY 1 — Database Session
# ================================================================

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Provide a database session for one request.

    HOW IT WORKS:
        1. Opens a new session from the connection pool
        2. yield — gives session to the route
        3. Route runs with the session
        4. After route completes: session closes, connection
           returns to pool

    WHY yield instead of return?
        yield lets us run cleanup code AFTER the route finishes
        Even if the route raises an exception — cleanup still runs
        No leaked database connections

    USAGE:
        @router.get("/users")
        async def get_users(db: AsyncSession = Depends(get_db)):
            result = await db.execute(select(User))
            return result.scalars().all()
    """
    async with AsyncSessionLocal() as session:
        try:
            # yield gives the session to the route
            # execution pauses here until the route completes
            yield session

            # If route completed without error → commit any pending changes
            # WHY? Some routes do writes without explicit commit
            # This ensures they're saved
            await session.commit()

        except Exception:
            # If anything went wrong → rollback all changes
            # This ensures partial writes don't corrupt the database
            await session.rollback()
            raise

        # Session automatically closes when exiting async with block
        # Connection returns to the pool — ready for the next request


# ================================================================
# DEPENDENCY 2 — Redis Client
# ================================================================

async def get_redis(request: Request):
    """
    Provide the Redis client stored on app state.

    The Redis client is created ONCE at startup in main.py lifespan
    and stored on app.state.redis. This dependency retrieves it.

    WHY not create a new Redis connection per request?
        Redis connections are expensive to open (~1-5ms each)
        One shared client with connection pooling is much faster
        aioredis handles connection pooling internally

    USAGE:
        @router.get("/cached-data")
        async def get_cached(redis = Depends(get_redis)):
            cached = await redis.get("my_key")
            return cached
    """
    if not hasattr(request.app.state, "redis"):
        # Redis not connected — lifespan startup may have failed
        log.error("redis_not_available")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cache service unavailable. Please try again later.",
        )

    return request.app.state.redis


# ================================================================
# DEPENDENCY 3 — Current Authenticated User
# ================================================================

# OAuth2PasswordBearer extracts the JWT token from the
# Authorization: Bearer <token> header automatically
# token_url is where clients get a token (login endpoint)
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login",
    # auto_error=False means: if no token → return None (not 401)
    # This lets us handle the error ourselves with a better message
    auto_error=False,
)


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    """
    Verify JWT token and return the current authenticated user.

    FLOW:
        1. OAuth2PasswordBearer extracts token from Authorization header
        2. Check token is not blacklisted in Redis (logout detection)
        3. Decode and verify JWT signature → get user_id
        4. Load User from database by user_id
        5. Check user account is active
        6. Return User object to the route

    If ANY step fails → raise 401 Unauthorized

    NOTE: This is a PLACEHOLDER for Phase 1.
        Real implementation added in Phase 2 when we build:
        - JWT token creation/verification (security.py)
        - User model (models/user.py)
        - Auth routes (api/v1/auth.py)

    USAGE:
        @router.get("/profile")
        async def get_profile(
            current_user = Depends(get_current_user)
        ):
            return current_user
    """
    # Phase 1 placeholder — no auth yet
    # In Phase 2 this becomes:
    #   1. verify token is not None
    #   2. check redis blacklist
    #   3. decode JWT → user_id
    #   4. load User from DB
    #   5. check user.is_active
    #   6. return user

    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please log in.",
            # WWW-Authenticate header tells client what auth scheme to use
            headers={"WWW-Authenticate": "Bearer"},
        )

    # TODO: Implement in Phase 2
    # For now raise 501 Not Implemented
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Authentication not yet implemented. Coming in Phase 2.",
    )


async def get_current_active_user(
    current_user=Depends(get_current_user),
):
    """
    Same as get_current_user but also checks user.is_active.

    WHY a separate dependency?
        get_current_user → verify token + load user
        get_current_active_user → also check account is not disabled

    Disabled accounts can exist in the DB but cannot use the API.
    Admin can disable accounts without deleting them.

    USAGE:
        @router.get("/sensitive-data")
        async def sensitive(
            user = Depends(get_current_active_user)
        ):
            ...
    """
    # TODO: Implement in Phase 2
    # Will check current_user.is_active == True
    return current_user


async def get_current_admin_user(
    current_user=Depends(get_current_user),
):
    """
    Same as get_current_user but also checks user.role == "admin".

    WHY?
        Some endpoints are admin-only:
            - View all users
            - Delete any document
            - Trigger manual RAGAS evaluation
            - View system metrics

    Non-admin users hitting admin endpoints get 403 Forbidden.

    USAGE:
        @router.get("/admin/users")
        async def list_all_users(
            admin = Depends(get_current_admin_user)
        ):
            ...
    """
    # TODO: Implement in Phase 2
    # Will check current_user.role == "admin"
    return current_user


# ================================================================
# DEPENDENCY 4 — Pagination
# ================================================================

class PaginationParams:
    """
    Common pagination parameters for list endpoints.

    Reusable across all endpoints that return lists:
        GET /documents
        GET /sessions
        GET /messages
        etc.

    USAGE:
        @router.get("/documents")
        async def list_documents(
            pagination: PaginationParams = Depends(),
        ):
            # pagination.offset, pagination.limit available
            result = await db.execute(
                select(Document)
                .offset(pagination.offset)
                .limit(pagination.limit)
            )
    """

    def __init__(
        self,
        # Page number — starts at 1
        page: int = 1,
        # Items per page — default 20, max 100
        page_size: int = 20,
    ):
        # Validate page number
        if page < 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="page must be >= 1",
            )

        # Validate page size
        if page_size < 1 or page_size > 100:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="page_size must be between 1 and 100",
            )

        self.page = page
        self.page_size = page_size

        # offset = how many records to skip
        # page=1, size=20 → skip 0, take 20
        # page=2, size=20 → skip 20, take 20
        # page=3, size=20 → skip 40, take 20
        self.offset = (page - 1) * page_size
        self.limit = page_size