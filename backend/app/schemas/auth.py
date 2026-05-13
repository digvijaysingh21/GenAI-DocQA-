"""
app/api/v1/auth.py — Authentication routes.
 
Endpoints:
    POST /auth/register  → create account, return user data
    POST /auth/login     → verify credentials, return token pair + user
    POST /auth/refresh   → rotate token pair using refresh token
    POST /auth/logout    → blacklist refresh token in Redis
    GET  /auth/me        → return current authenticated user
 
Security decisions explained in comments throughout.
"""
 
from __future__ import annotations
 
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
 
from app.core.security import (
    TOKEN_TYPE_REFRESH,
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
    verify_token,
)
from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    UserResponse,
)
 
log = structlog.get_logger(__name__)
 
router = APIRouter(prefix="/auth", tags=["Authentication"])
 
# Redis blacklist key prefix for invalidated refresh tokens
# Format: "blacklist:{token}" → "1"
# TTL = refresh token lifetime so Redis auto-cleans expired entries
BLACKLIST_PREFIX = "blacklist:"
 
 
# ─────────────────────────────────────────────────────────────
# POST /auth/register
# ─────────────────────────────────────────────────────────────
 
@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
    description=(
        "Creates a new user account. "
        "Email must be unique. Password is hashed with bcrypt before storage. "
        "Returns the created user profile (no password hash)."
    ),
)
async def register(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """
    Registration flow:
    1. Check email not already taken
    2. Hash password with bcrypt
    3. Create User row in DB
    4. Return UserResponse (no password)
    """
 
    # Step 1 — Check email uniqueness
    # We check BEFORE trying to insert to give a clearer error message.
    # A DB unique constraint would also catch this but with a generic error.
    existing = await db.execute(
        select(User).where(User.email == body.email)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )
 
    # Step 2 — Hash password
    # hash_password() uses bcrypt cost=12 — takes ~250ms intentionally
    hashed = hash_password(body.password)
 
    # Step 3 — Create user
    new_user = User(
        email=body.email,
        hashed_password=hashed,
        full_name=body.full_name,
        role="user",           # always start as regular user
        is_active=True,
        preferences={},
    )
    db.add(new_user)
    await db.commit()
    # expire_on_commit=False means new_user.id is still readable here
    # without needing await db.refresh(new_user)
 
    log.info(
        "user_registered",
        user_id=str(new_user.id),
        email=new_user.email,
    )
 
    return UserResponse.model_validate(new_user)