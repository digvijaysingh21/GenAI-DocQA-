"""
GenAI DocQA Platform — Application Configuration

This is the SINGLE SOURCE OF TRUTH for all configuration.
Every environment variable the app needs is defined here.

WHY PYDANTIC SETTINGS instead of os.getenv() everywhere?
    1. All variables in one place — easy to see what the app needs
    2. Type validation — "15" becomes 15 (int) automatically
    3. Fail fast — missing variable = app refuses to start with clear error
    4. IDE autocomplete — settings.DATABASE_URL works, no typos
    5. Validators — custom rules (min length, URL format, etc.)

USAGE:
    from app.config import settings

    settings.DATABASE_URL       # the full connection string
    settings.SECRET_KEY         # JWT signing key
    settings.GROQ_API_KEY       # default LLM API key
    settings.DEBUG              # True or False
"""

from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables / .env file.

    BaseSettings automatically:
        - Reads from .env file
        - Reads from environment variables (env vars override .env)
        - Validates types
        - Raises clear errors for missing required variables
    """

    model_config = SettingsConfigDict(
        # Which file to read
        env_file=".env",

        # Also check parent directories for .env
        # Useful when running from backend/ subdirectory
        env_file_encoding="utf-8",

        # DATABASE_URL and database_url both work
        case_sensitive=False,

        # If .env has extra variables we haven't defined → ignore them
        # Without this: Pydantic raises error for unknown variables
        extra="ignore",
    )

    # ================================================================
    # APPLICATION
    # ================================================================

    # Environment: development, production, test
    # Controls: debug mode, logging level, CORS strictness
    ENVIRONMENT: Literal["development", "production", "test"] = "development"

    # Debug mode — NEVER True in production
    # Controls: detailed error messages, auto-reload
    DEBUG: bool = False

    # Application version — matches __init__.py
    APP_VERSION: str = "1.0.0"

    # Backend server settings
    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = 8000

    # Allowed origins for CORS
    # Frontend URL(s) that can call this backend
    # In production: replace with your actual frontend domain
    ALLOWED_ORIGINS: list[str] = [
        "http://localhost:3000",   # React dev server
        "http://localhost:5173",   # Vite dev server
    ]

    # ================================================================
    # DATABASE
    # ================================================================

    # PostgreSQL connection string
    # MUST use postgresql+asyncpg:// driver — not postgresql://
    # Using postgresql:// with async SQLAlchemy = confusing crash
    DATABASE_URL: str = Field(
        ...,  # ... means REQUIRED — no default — app won't start without it
        description="PostgreSQL connection string. Must use postgresql+asyncpg:// driver.",
    )

    # Database connection pool settings
    # Pool keeps connections open and reuses them (faster than reconnecting)
    DB_POOL_SIZE: int = 20          # max simultaneous connections
    DB_MAX_OVERFLOW: int = 10       # extra connections when pool is full
    DB_POOL_TIMEOUT: int = 30       # seconds to wait for a connection
    DB_POOL_RECYCLE: int = 3600     # recycle connections after 1 hour

    # ================================================================
    # REDIS
    # ================================================================

    # Redis connection string
    # /0 = database index 0 (Redis supports 0-15 databases)
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection string for caching and rate limiting.",
    )

    # ================================================================
    # SECURITY — MOST CRITICAL SECTION
    # ================================================================

    # JWT signing key — used to sign and verify login tokens
    # If stolen: attacker can forge login tokens for ANY user
    # MUST be at least 32 characters — validator enforces this
    SECRET_KEY: str = Field(
        ...,
        description="JWT signing key. Generate with: openssl rand -hex 32",
    )

    # AES-256-GCM encryption key — used to encrypt LLM API keys in DB
    # If stolen + DB stolen: attacker can decrypt all stored API keys
    # MUST be at least 32 characters — validator enforces this
    ENCRYPTION_KEY: str = Field(
        ...,
        description="AES-256-GCM key for encrypting LLM API keys. Generate with: openssl rand -hex 32",
    )

    # Access token lifetime — short lived to limit damage if stolen
    # 15 minutes is the production standard
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15

    # Refresh token lifetime — used silently to get new access tokens
    # 7 days is the production standard
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Algorithm for JWT signing
    # HS256 = HMAC with SHA-256 — fast, symmetric, good for single service
    JWT_ALGORITHM: str = "HS256"

    # ================================================================
    # RATE LIMITING
    # ================================================================

    # Requests per minute per user per endpoint (sliding window)
    RATE_LIMIT_PER_MINUTE: int = 60         # general endpoints
    RATE_LIMIT_UPLOAD_PER_MINUTE: int = 10  # upload is expensive
    RATE_LIMIT_AUTH_PER_MINUTE: int = 20    # prevent brute force

    # ================================================================
    # LLM PROVIDERS
    # ================================================================

    # Groq — DEFAULT provider (free tier: 14,400 req/day)
    # Get your free key at: https://console.groq.com
    GROQ_API_KEY: str = Field(
        ...,
        description="Groq API key. Free at console.groq.com. Default LLM provider.",
    )

    # Optional providers — empty string means "not configured"
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    GOOGLE_API_KEY: str = ""
    MISTRAL_API_KEY: str = ""
    COHERE_API_KEY: str = ""

    # Default LLM configuration
    DEFAULT_LLM_PROVIDER: str = "groq"
    DEFAULT_LLM_MODEL: str = "llama-3.1-8b-instant"

    # LLM generation defaults
    DEFAULT_TEMPERATURE: float = 0.1    # low = more deterministic/factual
    DEFAULT_MAX_TOKENS: int = 2048      # max tokens in LLM response

    # ================================================================
    # EMBEDDINGS
    # ================================================================

    # local = Sentence-Transformers (free, runs on CPU, no API key needed)
    # openai = text-embedding-3-small ($0.02/1M tokens)
    # cohere = embed-english-v3.0 (free: 1000 calls/month)
    EMBEDDING_PROVIDER: Literal["local", "openai", "cohere"] = "local"

    # Model name depends on provider:
    # local: "all-MiniLM-L6-v2" (384-dim, fast, good quality)
    # openai: "text-embedding-3-small" (1536-dim)
    # cohere: "embed-english-v3.0" (1024-dim)
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"

    # All embeddings stored as 1536-dim vectors in pgvector
    # Smaller models zero-padded to match this dimension
    EMBEDDING_DIMENSION: int = 1536

    # ================================================================
    # FILE STORAGE
    # ================================================================

    # local = store on server disk (development only)
    # r2    = Cloudflare R2 object storage (production — free: 10GB)
    STORAGE_BACKEND: Literal["local", "r2"] = "local"

    # Local storage directory (used when STORAGE_BACKEND=local)
    UPLOAD_DIR: str = "uploads"

    # Maximum file size per upload in MB
    MAX_FILE_SIZE_MB: int = 50

    # Cloudflare R2 settings (only needed when STORAGE_BACKEND=r2)
    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET_NAME: str = ""

    # ================================================================
    # OBSERVABILITY
    # ================================================================

    # LangSmith — traces every LangGraph agent run automatically
    # Get free key at: https://smith.langchain.com
    LANGCHAIN_TRACING_V2: bool = True
    LANGCHAIN_API_KEY: str = ""
    LANGCHAIN_PROJECT: str = "genai-docqa"

    # Prometheus metrics
    PROMETHEUS_ENABLED: bool = True

    # ================================================================
    # BUDGET CONTROL
    # ================================================================

    # Default budget limits per user per day/month (in USD)
    # Users can override these via the UI
    DEFAULT_DAILY_BUDGET_USD: float = 5.0
    DEFAULT_MONTHLY_BUDGET_USD: float = 50.0

    # ================================================================
    # ADMIN
    # ================================================================

    # Default admin user created on first startup
    # Change these immediately after first deployment
    ADMIN_EMAIL: str = "admin@docqa.local"
    ADMIN_PASSWORD: str = "admin123!"

    # ================================================================
    # VALIDATORS
    # Fail fast — catch bad config at startup, not in production
    # ================================================================

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        """
        SECRET_KEY must be at least 32 characters.

        WHY? JWT tokens are signed with this key. A short key is
        easier to brute-force. 32 chars minimum is the industry standard.
        Generate with: openssl rand -hex 32 (gives you 64 chars)
        """
        if len(v) < 32:
            raise ValueError(
                "SECRET_KEY must be at least 32 characters long. "
                "Generate one with: openssl rand -hex 32"
            )
        return v

    @field_validator("ENCRYPTION_KEY")
    @classmethod
    def validate_encryption_key(cls, v: str) -> str:
        """
        ENCRYPTION_KEY must be at least 32 characters.

        WHY? AES-256-GCM uses 256-bit (32 byte) keys.
        Shorter keys weaken the encryption significantly.
        """
        if len(v) < 32:
            raise ValueError(
                "ENCRYPTION_KEY must be at least 32 characters long. "
                "Generate one with: openssl rand -hex 32"
            )
        return v

    @field_validator("DATABASE_URL")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        """
        DATABASE_URL must use the asyncpg driver.

        WHY? We use async SQLAlchemy throughout. The asyncpg driver
        is what makes async work. Using postgresql:// (sync driver)
        causes a confusing MissingGreenlet error deep in SQLAlchemy.

        This validator catches the mistake immediately at startup
        with a clear, actionable error message.
        """
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "DATABASE_URL must use the asyncpg driver. "
                "Change: postgresql://... "
                "To:     postgresql+asyncpg://..."
            )
        return v

    @field_validator("ENVIRONMENT")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        """
        In production, DEBUG must be False.

        WHY? DEBUG=True exposes detailed error tracebacks to clients.
        In production this leaks internal implementation details
        and is a security risk.
        """
        return v

    # ================================================================
    # COMPUTED PROPERTIES
    # Derived values calculated from other settings
    # ================================================================

    @property
    def is_development(self) -> bool:
        """True when running in development environment."""
        return self.ENVIRONMENT == "development"

    @property
    def is_production(self) -> bool:
        """True when running in production environment."""
        return self.ENVIRONMENT == "production"

    @property
    def is_test(self) -> bool:
        """True when running tests."""
        return self.ENVIRONMENT == "test"

    @property
    def database_url_sync(self) -> str:
        """
        Synchronous database URL for tools that don't support async.

        Alembic needs a sync URL for some operations.
        Replaces asyncpg driver with psycopg2.
        """
        return self.DATABASE_URL.replace(
            "postgresql+asyncpg://",
            "postgresql+psycopg2://"
        )


# ================================================================
# SINGLETON — ONE INSTANCE FOR THE ENTIRE APP
# ================================================================

@lru_cache()
def get_settings() -> Settings:
    """
    Returns the Settings singleton.

    @lru_cache() means this function runs ONCE and caches the result.
    Every subsequent call returns the same cached object.

    WHY CACHE?
        Settings reads .env file from disk. We don't want to
        re-read the file on every request. One read at startup,
        then all subsequent calls get the cached instance.

    USAGE:
        from app.config import settings
        print(settings.DATABASE_URL)

    IN TESTS (to override settings):
        from app.config import get_settings
        get_settings.cache_clear()  # clear cache
        # set env vars, then call get_settings() again
    """
    return Settings()


# Module-level singleton
# Import this anywhere in the app:
#   from app.config import settings
settings = get_settings()