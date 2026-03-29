"""
GenAI DocQA Platform — Structured JSON Logging

Sets up structlog for structured JSON logging across the entire app.

WHY STRUCTURED LOGGING?
    Plain text logs:
        "INFO: User abc123 uploaded report.pdf, size 2.4MB"
        Hard to search, filter, or analyze programmatically.

    Structured JSON logs:
        {"event": "file_uploaded", "user_id": "abc123",
         "filename": "report.pdf", "size_mb": 2.4,
         "trace_id": "xyz789", "timestamp": "2025-03-14T10:30:00Z"}
        Machine readable. Every field searchable. Feeds into log aggregators.

WHY structlog?
    Built-in logging → plain strings
    structlog → JSON objects with automatic context binding

USAGE:
    import structlog
    log = structlog.get_logger(__name__)

    # Simple event
    log.info("user_registered", email="user@example.com")

    # With multiple fields
    log.info("query_completed",
             chunks_found=7,
             latency_ms=145,
             provider="groq")

    # Error with exception info
    log.error("llm_failed",
              provider="groq",
              error=str(e),
              exc_info=True)   # includes full traceback

    # Bind context for all subsequent logs in this scope
    log = log.bind(user_id="abc123", session_id="xyz")
    log.info("action_taken")  # automatically includes user_id, session_id

OUTPUT EXAMPLE:
    Development (pretty colored output):
        2025-03-14 10:30:00 [info     ] file_uploaded   user_id=abc123 filename=report.pdf

    Production (JSON for log aggregators):
        {"event":"file_uploaded","user_id":"abc123","filename":"report.pdf",
         "level":"info","timestamp":"2025-03-14T10:30:00.123Z"}
"""

import logging
import sys

import structlog
from structlog.types import EventDict, Processor

from app.config import settings


def add_app_context(
    logger: logging.Logger,
    method: str,
    event_dict: EventDict,
) -> EventDict:
    """
    Add application-level context to every log line.

    This processor runs on EVERY log call automatically.
    Adds: app version, environment.

    Processors are functions that take an event dict and return
    a modified event dict. They run in a pipeline, each one
    adding or modifying fields before the final output.
    """
    event_dict["app_version"] = settings.APP_VERSION
    event_dict["environment"] = settings.ENVIRONMENT
    return event_dict


def drop_color_message_key(
    logger: logging.Logger,
    method: str,
    event_dict: EventDict,
) -> EventDict:
    """
    Remove the 'color_message' key added by uvicorn.

    Uvicorn adds a 'color_message' field with ANSI color codes
    for terminal display. This is noise in structured JSON logs.
    We drop it here.
    """
    event_dict.pop("color_message", None)
    return event_dict


def setup_logging() -> None:
    """
    Configure structlog for the entire application.

    Called ONCE at startup in main.py lifespan — before anything else.
    All subsequent log.info() / log.error() calls use this config.

    TWO MODES:
        Development (DEBUG=True):
            Pretty colored console output
            Human-readable timestamps
            Easier to read while developing

        Production (DEBUG=False):
            JSON output — one JSON object per line
            Machine-readable timestamps (ISO 8601)
            Feeds into log aggregators (Datadog, CloudWatch, etc.)
    """

    # ── Shared processors ─────────────────────────────────────
    # These run on EVERY log line regardless of development/production
    # Each processor receives the event dict and returns a modified one
    shared_processors: list[Processor] = [
        # Add log level to every log line (info, warning, error, etc.)
        structlog.stdlib.add_log_level,

        # Add logger name (the __name__ passed to get_logger)
        # Helps identify which module produced the log
        structlog.stdlib.add_logger_name,

        # Add ISO 8601 timestamp to every log line
        structlog.processors.TimeStamper(fmt="iso"),

        # Support for log.bind() — binds context variables
        # These appear automatically in all subsequent log calls
        # Used for: trace_id, user_id, request_id
        structlog.contextvars.merge_contextvars,

        # Add stack info for exceptions (exc_info=True in log calls)
        structlog.processors.StackInfoRenderer(),

        # Remove uvicorn color codes (noise in JSON logs)
        drop_color_message_key,

        # Add app-level context (version, environment)
        add_app_context,
    ]

    if settings.DEBUG:
        # ── Development: pretty colored console output ────────
        # Easy to read in terminal during development
        # NOT for production — color codes are noise in log files
        processors: list[Processor] = shared_processors + [
            # Format exceptions in a readable way
            structlog.dev.ConsoleRenderer(
                colors=True,
                exception_formatter=structlog.dev.plain_traceback,
            ),
        ]
        log_format = "%(message)s"

    else:
        # ── Production: JSON output ───────────────────────────
        # Machine-readable — feeds into log aggregators
        # One JSON object per line — easy to parse and search
        processors = shared_processors + [
            # Format exceptions as JSON-serializable dict
            structlog.processors.dict_tracebacks,

            # Convert event dict to JSON string
            structlog.processors.JSONRenderer(),
        ]
        log_format = "%(message)s"

    # ── Configure structlog ───────────────────────────────────
    structlog.configure(
        processors=processors,

        # Use standard library logger as the backend
        # structlog wraps it — we get structlog's API + stdlib's routing
        wrapper_class=structlog.stdlib.BoundLogger,

        # Where to get the logger from (stdlib)
        logger_factory=structlog.stdlib.LoggerFactory(),

        # Cache the logger — don't recreate on every log call
        cache_logger_on_first_use=True,
    )

    # ── Configure Python's standard logging ──────────────────
    # Some libraries (SQLAlchemy, uvicorn, alembic) use stdlib logging
    # We route them through structlog so everything appears in one place

    logging.basicConfig(
        format=log_format,
        stream=sys.stdout,  # log to stdout (Docker captures this)
        level=logging.DEBUG if settings.DEBUG else logging.INFO,
    )

    # Set log levels for noisy third-party libraries
    # These produce too much output at DEBUG level
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.DEBUG else logging.WARNING
    )
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
    logging.getLogger("alembic").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    # Confirm logging is set up
    log = structlog.get_logger(__name__)
    log.info(
        "logging_configured",
        mode="development" if settings.DEBUG else "production",
        level="DEBUG" if settings.DEBUG else "INFO",
    )