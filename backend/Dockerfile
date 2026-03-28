# ============================================================
# GenAI DocQA Platform — Backend Dockerfile
# ============================================================
# Multi-stage build:
#   Stage 1 (builder) : installs all dependencies (~800MB)
#   Stage 2 (production): copies only results (~300MB)
#
# Why multi-stage?
#   Build tools (gcc, make, compilers) are needed to INSTALL
#   some Python packages but serve zero purpose in production.
#   Leaving them in the final image adds size + security risk.
#
# Final image is ~300MB instead of ~800MB
# ============================================================


# ============================================================
# STAGE 1 — Builder
# Install all Python dependencies here
# This stage is large but temporary — never deployed
# ============================================================
FROM python:3.12-slim AS builder

# Set working directory for this stage
WORKDIR /build

# Install system build dependencies
# These are needed to COMPILE some Python packages (e.g. cryptography, asyncpg)
# --no-install-recommends: only install exactly what we asked for (smaller image)
# We clean up apt cache after to reduce layer size
RUN apt-get update && apt-get install -y --no-install-recommends \
    # C compiler — needed for cryptography, asyncpg native extensions
    gcc \
    # Python development headers — needed for building Python C extensions
    python3-dev \
    # PostgreSQL development headers — needed for asyncpg
    libpq-dev \
    # Cleanup — removes apt cache to reduce image size
    && rm -rf /var/lib/apt/lists/*

# Copy ONLY requirements.txt first — before copying any app code
# WHY? Docker layer caching.
# If requirements.txt hasn't changed → this layer is cached
# → pip install is SKIPPED on rebuild (saves 3-5 minutes)
# If you copy all code first, any code change invalidates the cache
COPY requirements.txt .

# Install all Python packages into a specific directory
# --no-cache-dir: don't cache downloads (saves ~200MB)
# --prefix=/install: install to /install instead of system Python
# This makes it easy to copy just the packages to Stage 2
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ============================================================
# STAGE 2 — Production
# Fresh clean image — no build tools, no cache, no junk
# Only copy what we actually need to run the app
# ============================================================
FROM python:3.12-slim AS production

# ── Environment variables ─────────────────────────────────────

# Disable Python output buffering
# Without this: logs sit in buffer and never appear in Docker
# With this: logs appear instantly — critical for debugging
ENV PYTHONUNBUFFERED=1

# Don't write .pyc bytecode files to disk
# In a container these are pointless — container is ephemeral
ENV PYTHONDONTWRITEBYTECODE=1

# Add our installed packages to Python's path
ENV PYTHONPATH=/usr/local/lib/python3.12/site-packages

# Set working directory for production app
WORKDIR /app

# ── System dependencies for RUNTIME (not build time) ─────────

# These are needed to RUN the app (not just install it)
RUN apt-get update && apt-get install -y --no-install-recommends \
    # PostgreSQL client library — asyncpg needs this at runtime
    libpq5 \
    # Tesseract OCR engine — needed for scanned PDF processing
    tesseract-ocr \
    # English language data for Tesseract
    tesseract-ocr-eng \
    # curl — for health checks in docker-compose
    curl \
    && rm -rf /var/lib/apt/lists/*

# ── Copy installed packages from Stage 1 ─────────────────────

# Copy ONLY the installed Python packages from builder stage
# NOT the build tools, NOT the compiler, NOT the cache
# This is the entire point of multi-stage builds
COPY --from=builder /install /usr/local

# ── Security: Non-root user ───────────────────────────────────

# Create a non-root user to run the application
# WHY? If the app is compromised, attacker gets appuser permissions
# NOT root permissions — limits blast radius significantly
# -r = system user (no login shell, no home directory by default)
# -g = create a group with the same name
RUN groupadd -r appgroup && useradd -r -g appgroup appuser

# Create the uploads directory and set correct ownership
# The app saves uploaded files here (in local storage mode)
RUN mkdir -p /app/uploads && chown -R appuser:appgroup /app

# ── Copy application code ─────────────────────────────────────

# Copy the entire app directory
# This happens AFTER pip install so code changes don't invalidate
# the pip install cache layer (important for fast rebuilds)
COPY --chown=appuser:appgroup ./app /app/app
COPY --chown=appuser:appgroup ./alembic /app/alembic
COPY --chown=appuser:appgroup ./alembic.ini /app/alembic.ini

# ── Switch to non-root user ───────────────────────────────────

# All subsequent commands run as appuser, not root
USER appuser

# ── Expose port ───────────────────────────────────────────────

# Tell Docker this container listens on port 8000
# This is documentation — doesn't actually publish the port
# Port publishing happens in docker-compose.yml
EXPOSE 8000

# ── Health check ─────────────────────────────────────────────

# Docker uses this to know if the container is healthy
# Every 30 seconds: hit /api/v1/health
# If it fails 3 times in a row: container marked as unhealthy
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

# ── Start command ─────────────────────────────────────────────

# How to run the application
# uvicorn     : the ASGI server
# app.main:app: the FastAPI app object inside app/main.py
# --host 0.0.0.0 : listen on all network interfaces (not just localhost)
#                  required so Docker can forward traffic to the container
# --port 8000 : listen on port 8000
# --workers 1 : single worker (use multiple in production with gunicorn)
# --loop uvloop: faster event loop (installed via uvicorn[standard])
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--loop", "uvloop"]