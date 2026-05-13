"""
app/schemas — Pydantic request/response schemas (API contract).

Schemas define what data enters and leaves the API.
They are completely separate from SQLAlchemy models.

Why separate from models:
    Models define ALL columns including sensitive ones (hashed_password).
    Schemas define only what the client should send or receive.
    This prevents accidentally exposing sensitive data in API responses.

Schemas in this package:
    auth.py     → RegisterRequest, LoginRequest, TokenPair,
                  UserResponse, LLMKeyCreate, LLMKeyResponse

    document.py → DocumentCreate, DocumentResponse,
                  ChunkPreview, UploadProgressEvent  (Phase 3)

The bridge between model and schema:
    model_config = ConfigDict(from_attributes=True)
    user = await db.get(User, id)
    return UserResponse.model_validate(user)  ← reads ORM attributes
"""

from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    TokenPair,
    UserResponse,
    LLMKeyCreate,
    LLMKeyResponse,
)

__all__ = [
    "LoginRequest",
    "RegisterRequest",
    "TokenPair",
    "UserResponse",
    "LLMKeyCreate",
    "LLMKeyResponse",
]