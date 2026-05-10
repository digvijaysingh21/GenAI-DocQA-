"""
app/core/security.py — Three security concerns in one place:

1. JWT tokens    — create and verify access + refresh tokens
2. bcrypt        — hash and verify passwords
3. AES-256-GCM   — encrypt and decrypt LLM API keys (BYOK pattern)

Import this from routes, dependencies, and services.
Never import models here — that would create circular imports.
"""

from __future__ import annotations

import base64
import os
from datetime import datetime, timedelta, timezone
from typing import Literal

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

# ─────────────────────────────────────────────────────────────
# PASSWORD HASHING  (bcrypt)
# ─────────────────────────────────────────────────────────────

# CryptContext handles everything: hashing, verifying, upgrading schemes.
# schemes=["bcrypt"] → use bcrypt algorithm
# deprecated="auto"  → if we ever add a stronger algorithm later,
#                       old bcrypt hashes are auto-marked deprecated
#                       and re-hashed on next login
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """
    Hash a plain text password using bcrypt cost=12.

    bcrypt automatically:
    - Generates a random salt per password
    - Runs 2^12 = 4096 iterations (slow on purpose — defeats brute force)
    - Returns a self-contained string with algorithm + salt + hash

    Example output: "$2b$12$EixZaYVK1fsbw1ZfbX3OXe..."
    The salt is embedded — we do not store it separately.
    """
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain password against its bcrypt hash.

    Uses constant-time comparison internally — immune to timing attacks.
    A timing attack is where an attacker measures response time to guess
    which characters are correct. Constant-time comparison always takes
    the same amount of time regardless of how many characters match.

    Returns True if correct, False if wrong.
    Never raises — always returns bool.
    """
    return pwd_context.verify(plain_password, hashed_password)


# ─────────────────────────────────────────────────────────────
# JWT TOKENS
# ─────────────────────────────────────────────────────────────

# Algorithm for signing JWTs.
# HS256 = HMAC + SHA-256. Symmetric — same key signs and verifies.
# Good enough for our use case (we are both the issuer and verifier).
ALGORITHM = "HS256"

# Token type values — stored in JWT payload as "type" claim.
# Prevents using a refresh token as an access token and vice versa.
TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"


def create_access_token(user_id: str) -> str:
    """
    Create a short-lived access token (15 minutes by default).

    The JWT payload contains:
    - sub  : subject — the user_id (standard JWT claim)
    - type : "access" — prevents refresh tokens being used as access tokens
    - exp  : expiry timestamp — jose validates this automatically
    - iat  : issued-at timestamp — useful for audit logs

    The token is SIGNED with SECRET_KEY.
    Anyone with the token can read the payload (it is base64, not encrypted).
    But nobody can FORGE a valid signature without SECRET_KEY.
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    payload = {
        "sub": user_id,
        "type": TOKEN_TYPE_ACCESS,
        "exp": expire,
        "iat": now,
    }

    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    """
    Create a long-lived refresh token (7 days by default).

    Refresh tokens are ONLY used to obtain new access tokens.
    They should be stored securely by the client (httpOnly cookie ideally).

    On every refresh:
    - Old refresh token is blacklisted in Redis
    - New refresh token is issued
    This is called token rotation — a stolen refresh token becomes
    useless after the legitimate user refreshes once.
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    payload = {
        "sub": user_id,
        "type": TOKEN_TYPE_REFRESH,
        "exp": expire,
        "iat": now,
    }

    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def verify_token(
    token: str,
    expected_type: Literal["access", "refresh"] = TOKEN_TYPE_ACCESS,
) -> str:
    """
    Verify a JWT token and return the user_id (sub claim).

    Raises ValueError with a clear message if:
    - Token signature is invalid (tampered or wrong SECRET_KEY)
    - Token has expired
    - Token type does not match expected_type
      (prevents using refresh token where access token is required)
    - Token is missing required claims

    Never returns None — always returns user_id string or raises.
    The caller (get_current_user in dependencies.py) catches ValueError
    and converts it to HTTP 401.
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise ValueError(f"Invalid token: {exc}") from exc

    user_id: str | None = payload.get("sub")
    token_type: str | None = payload.get("type")

    if not user_id:
        raise ValueError("Token missing 'sub' claim")

    if token_type != expected_type:
        raise ValueError(
            f"Wrong token type: expected '{expected_type}', got '{token_type}'"
        )

    return user_id


# ─────────────────────────────────────────────────────────────
# AES-256-GCM ENCRYPTION  (for LLM API keys — BYOK pattern)
# ─────────────────────────────────────────────────────────────

# GCM = Galois/Counter Mode
# Provides BOTH encryption AND authentication (integrity check).
# If anyone modifies the ciphertext, decryption raises an exception.
# This is called Authenticated Encryption with Associated Data (AEAD).

# Nonce size: 12 bytes is the GCM standard recommendation.
# A nonce (Number used ONCE) ensures same key + same plaintext
# produces different ciphertext every time. Never reuse a nonce.
GCM_NONCE_SIZE = 12


def _get_aes_key() -> bytes:
    """
    Derive a 32-byte AES key from the ENCRYPTION_KEY setting.

    ENCRYPTION_KEY in .env is a 64-char hex string (openssl rand -hex 32).
    We decode it to 32 raw bytes for AES-256 (256 bits = 32 bytes).
    """
    try:
        return bytes.fromhex(settings.ENCRYPTION_KEY)
    except ValueError as exc:
        raise ValueError(
            "ENCRYPTION_KEY must be a valid hex string. "
            "Generate with: openssl rand -hex 32"
        ) from exc


def encrypt_api_key(raw_key: str) -> str:
    """
    Encrypt a raw LLM API key for storage in the database.

    Process:
    1. Generate a random 12-byte nonce (different every call)
    2. Encrypt with AES-256-GCM using ENCRYPTION_KEY + nonce
    3. Prepend nonce to ciphertext: nonce || ciphertext
    4. Base64-encode for safe DB storage (TEXT column)

    The nonce is NOT secret — it is stored alongside the ciphertext.
    Security comes from the ENCRYPTION_KEY, not the nonce.
    Without ENCRYPTION_KEY, the nonce is useless.

    Returns: base64-encoded string safe to store in any TEXT column.
    """
    aes_key = _get_aes_key()
    aesgcm = AESGCM(aes_key)

    # os.urandom is cryptographically secure on all platforms
    nonce = os.urandom(GCM_NONCE_SIZE)

    # encrypt returns: ciphertext + 16-byte GCM authentication tag
    ciphertext = aesgcm.encrypt(nonce, raw_key.encode("utf-8"), associated_data=None)

    # Store nonce + ciphertext together — we need nonce to decrypt
    return base64.b64encode(nonce + ciphertext).decode("utf-8")


def decrypt_api_key(encrypted_key: str) -> str:
    """
    Decrypt a stored LLM API key for use in an actual API call.

    Process (reverse of encrypt):
    1. Base64-decode
    2. Split: first 12 bytes = nonce, rest = ciphertext + auth tag
    3. Decrypt with AES-256-GCM using ENCRYPTION_KEY + nonce
    4. GCM automatically verifies integrity — raises if tampered

    Raises:
        ValueError: if decryption fails (wrong key, tampered data, etc.)

    The raw key should be used immediately and NOT stored in any variable
    longer than necessary. del raw_key after use in production callers.
    """
    aes_key = _get_aes_key()
    aesgcm = AESGCM(aes_key)

    try:
        data = base64.b64decode(encrypted_key.encode("utf-8"))
    except Exception as exc:
        raise ValueError("Encrypted key is not valid base64") from exc

    if len(data) < GCM_NONCE_SIZE:
        raise ValueError("Encrypted key too short — data may be corrupted")

    nonce = data[:GCM_NONCE_SIZE]
    ciphertext = data[GCM_NONCE_SIZE:]

    try:
        # AESGCM.decrypt raises InvalidTag if ciphertext was tampered with
        plaintext = aesgcm.decrypt(nonce, ciphertext, associated_data=None)
    except Exception as exc:
        raise ValueError(
            "Decryption failed — wrong ENCRYPTION_KEY or corrupted data"
        ) from exc

    return plaintext.decode("utf-8")