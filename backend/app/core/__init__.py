"""
app/core — Cross-cutting security and infrastructure utilities.

This package is imported by routes, dependencies, and middleware.
It has NO imports from app.api, app.models, or app.schemas
to avoid circular imports.

Contents:
    security.py     — JWT token creation/verification, bcrypt password
                      hashing, AES-256-GCM encryption for LLM API keys
    rate_limiter.py — Redis sliding window rate limiting middleware
"""