"""
app/models/llm_key.py — LLM API key storage table (BYOK pattern).

Maps to the 'llm_keys' table in PostgreSQL.

BYOK = Bring Your Own Key. Users store their own LLM provider API keys.
We encrypt them before storage using AES-256-GCM (app/core/security.py).
The raw key is NEVER stored. Only decrypted in memory at call time.

Relationships:
    LLMKey → User  (many-to-one)  llm_key.user
    User   → LLMKey (one-to-many) user.llm_keys
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base

if TYPE_CHECKING:
    from app.models.user import User


# Valid LLM provider names — enforced at the schema layer (schemas/auth.py)
# Listed here as documentation of what the system supports
SUPPORTED_PROVIDERS = {
    "groq",        # default free provider
    "openai",      # GPT-4o, GPT-4o-mini
    "anthropic",   # Claude 3.5 Sonnet
    "google",      # Gemini 1.5 Pro
    "mistral",     # Mistral Large
    "cohere",      # Command R+
    "ollama",      # local models
}


class LLMKey(Base):
    """
    Stores one encrypted LLM API key for one user.

    One user can have multiple keys — one per provider, or multiple
    keys for the same provider (e.g., different Groq keys for different
    projects or budget limits).

    Security guarantees:
    - api_key_encrypted is AES-256-GCM encrypted — unreadable without
      the server's ENCRYPTION_KEY environment variable
    - key_hint shows only the last 4 characters — safe to display
    - The raw key exists in plain text only in two moments:
        1. When the user submits it (HTTP request body, TLS encrypted)
        2. When we decrypt it to make an LLM API call (in memory only)
    - Raw key is never logged, never returned in API responses,
      never stored anywhere except encrypted in this column

    Tenant isolation:
    Every query on this table MUST include user_id = current_user.id.
    This is enforced in app/api/v1/llm_keys.py — never query by id alone.
    """

    __tablename__ = "llm_keys"

    # ── Primary key ──────────────────────────────────────────
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
        comment="Unique key identifier",
    )

    # ── Foreign key → users ───────────────────────────────────
    # ondelete="CASCADE" → if the user is deleted, all their keys
    # are automatically deleted by PostgreSQL at the DB level.
    # This works even if you delete via raw SQL bypassing SQLAlchemy.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,  # Index for fast lookup: "give me all keys for user X"
        comment="Owner of this key — references users.id",
    )

    # ── Provider identification ───────────────────────────────
    provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment=(
            "LLM provider name: 'groq', 'openai', 'anthropic', "
            "'google', 'mistral', 'cohere', 'ollama'"
        ),
    )

    # ── The encrypted key ─────────────────────────────────────
    # Contains: base64(nonce + AES-256-GCM ciphertext)
    # Decrypted only in memory when making an actual LLM API call.
    # See: app/core/security.py encrypt_api_key() / decrypt_api_key()
    api_key_encrypted: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment=(
            "AES-256-GCM encrypted API key. "
            "Format: base64(12-byte nonce + ciphertext + 16-byte auth tag). "
            "Never query or return this column directly in API responses."
        ),
    )

    # ── Safe display hint ─────────────────────────────────────
    # Shows last 4 characters of the original key.
    # Example: if key is "gsk_abc123xyz789", hint is "...789"
    # Safe to display in UI — cannot be used to reconstruct the key.
    key_hint: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment=(
            "Last 4 characters of the raw key for UI display. "
            "Example: '...789'. Safe to return in API responses."
        ),
    )

    # ── Status ────────────────────────────────────────────────
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="true",
        comment=(
            "Whether this key is currently active. "
            "Inactive keys are skipped by the LLM router. "
            "Set to false instead of deleting when a key is rotated."
        ),
    )

    # ── Testing metadata ──────────────────────────────────────
    # Updated when user hits POST /llm-keys/{id}/test
    # The LLM router checks this to skip keys that haven't been tested
    # or were last tested too long ago.
    last_tested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment=(
            "When this key was last verified with a live API call. "
            "None = never tested. Updated by POST /llm-keys/{id}/test."
        ),
    )

    # ── Timestamps ────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="When this key was stored",
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="Last modification timestamp",
    )

    # ── Relationship back to User ─────────────────────────────
    # back_populates="llm_keys" connects to User.llm_keys defined in user.py
    # lazy="selectin" loads the user in a second SELECT (safe for async)
    user: Mapped["User"] = relationship(
        "User",
        back_populates="llm_keys",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<LLMKey id={self.id} provider={self.provider} "
            f"hint={self.key_hint} active={self.is_active}>"
        )

    @classmethod
    def make_hint(cls, raw_key: str) -> str:
        """
        Extract the last 4 characters of a raw API key for display.

        Called when storing a new key — before encryption.
        The hint is stored in plain text (safe — cannot reconstruct key).

        Example:
            raw_key = "gsk_abc123xyz789"
            hint    = "...789"
        """
        if len(raw_key) <= 4:
            return "..." + raw_key
        return "..." + raw_key[-4:]