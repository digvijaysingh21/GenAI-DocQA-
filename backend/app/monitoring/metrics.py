"""
GenAI DocQA Platform — Prometheus Metrics

Defines all 12 metrics tracked across the entire platform.

HOW PROMETHEUS WORKS:
    1. This file defines metric objects (Counter, Histogram, Gauge)
    2. Other files call .inc(), .observe(), .set() to update values
    3. Prometheus scrapes /metrics endpoint every 15 seconds
    4. Grafana reads from Prometheus and shows dashboards

THREE METRIC TYPES:
    Counter   → only goes UP (total queries, total errors)
    Histogram → tracks distribution (latency, file sizes)
    Gauge     → goes UP and DOWN (active sessions, RAGAS score)

LABELS:
    Labels add dimensions to metrics.
    QUERIES_TOTAL.labels(provider="groq", model="llama3").inc()
    QUERIES_TOTAL.labels(provider="openai", model="gpt4o").inc()
    Now you can filter: "show only Groq queries" in Grafana.

WHERE METRICS ARE UPDATED:
    These are DEFINED here, UPDATED in the files that do the work:
    - Query routes update QUERIES_TOTAL, QUERY_LATENCY_SECONDS
    - LLM router updates TOKENS_CONSUMED_TOTAL, COST_USD_TOTAL
    - Document processor updates DOCUMENTS_UPLOADED_TOTAL
    - Rate limiter updates RATE_LIMIT_HITS_TOTAL
    - RAGAS evaluator updates RAGAS_FAITHFULNESS, RAGAS_RELEVANCE

USAGE (in any other file):
    from app.monitoring.metrics import QUERIES_TOTAL, QUERY_LATENCY_SECONDS

    # Increment a counter
    QUERIES_TOTAL.labels(
        provider="groq",
        model="llama3",
        query_type="simple"
    ).inc()

    # Record a latency observation
    with QUERY_LATENCY_SECONDS.labels(provider="groq").time():
        result = await llm.generate(prompt)

    # Update a gauge
    ACTIVE_SESSIONS.inc()   # user connected
    ACTIVE_SESSIONS.dec()   # user disconnected
"""

import structlog
from prometheus_client import Counter, Gauge, Histogram

log = structlog.get_logger(__name__)


# ================================================================
# METRIC 1 — Total Queries
# Counter: only goes up. Never resets (except app restart).
# ================================================================

QUERIES_TOTAL = Counter(
    # Metric name — appears in Prometheus as-is
    name="genai_docqa_queries_total",

    # Description — appears in Prometheus UI
    documentation="Total number of queries processed by the platform",

    # Labels — dimensions you can filter by in Grafana
    # provider: which LLM provider handled this query
    # model: which specific model was used
    # query_type: simple/complex/multi_hop classification
    # status: success/failed/cached
    labelnames=["provider", "model", "query_type", "status"],
)

# HOW TO UPDATE (in chat routes, Phase 9):
# QUERIES_TOTAL.labels(
#     provider="groq",
#     model="llama-3.1-8b-instant",
#     query_type="simple",
#     status="success"
# ).inc()


# ================================================================
# METRIC 2 — End-to-End Query Latency
# Histogram: tracks distribution of values across buckets.
# ================================================================

QUERY_LATENCY_SECONDS = Histogram(
    name="genai_docqa_query_latency_seconds",
    documentation="End-to-end query latency from request to first token",
    labelnames=["provider", "model"],

    # Buckets define the distribution ranges
    # We track: 100ms, 250ms, 500ms, 1s, 2s, 5s, 10s, 30s
    # A query hitting the "10.0" bucket means it took 5-10 seconds
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)

# HOW TO UPDATE (in chat routes, Phase 9):
# with QUERY_LATENCY_SECONDS.labels(provider="groq", model="llama3").time():
#     response = await llm.generate(prompt)
# .time() is a context manager — measures time automatically


# ================================================================
# METRIC 3 — Retrieval Latency
# Histogram: tracks how long vector search + reranking takes.
# ================================================================

RETRIEVAL_LATENCY_SECONDS = Histogram(
    name="genai_docqa_retrieval_latency_seconds",
    documentation="Vector search + BM25 + reranking latency",
    labelnames=["search_type"],

    # Retrieval should be fast — buckets are smaller than query latency
    # search_type: vector/bm25/hybrid
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
)

# HOW TO UPDATE (in hybrid_search.py, Phase 4):
# with RETRIEVAL_LATENCY_SECONDS.labels(search_type="hybrid").time():
#     chunks = await hybrid_search.search(query_vector, query_text)


# ================================================================
# METRIC 4 — Token Consumption
# Counter: total tokens sent to and received from LLMs.
# Used for cost tracking and budget enforcement.
# ================================================================

TOKENS_CONSUMED_TOTAL = Counter(
    name="genai_docqa_tokens_consumed_total",
    documentation="Total tokens consumed (input + output) across all LLM calls",
    labelnames=["provider", "model", "token_type"],
    # token_type: input (prompt tokens) or output (completion tokens)
    # Input tokens are cheaper than output tokens for most providers
)

# HOW TO UPDATE (in LLM router, Phase 5):
# TOKENS_CONSUMED_TOTAL.labels(
#     provider="groq",
#     model="llama-3.1-8b-instant",
#     token_type="input"
# ).inc(prompt_tokens)
#
# TOKENS_CONSUMED_TOTAL.labels(
#     provider="groq",
#     model="llama-3.1-8b-instant",
#     token_type="output"
# ).inc(completion_tokens)


# ================================================================
# METRIC 5 — LLM Cost in USD
# Counter: tracks real money spent on LLM API calls.
# Feeds into budget enforcement and cost dashboards.
# ================================================================

COST_USD_TOTAL = Counter(
    name="genai_docqa_cost_usd_total",
    documentation="Total LLM API cost in USD",
    labelnames=["provider", "model"],
)

# HOW TO UPDATE (in LLM router, Phase 5):
# cost = (input_tokens * input_price + output_tokens * output_price)
# COST_USD_TOTAL.labels(provider="groq", model="llama3").inc(cost)


# ================================================================
# METRIC 6 — Documents Uploaded
# Counter: tracks how many files have been uploaded and indexed.
# ================================================================

DOCUMENTS_UPLOADED_TOTAL = Counter(
    name="genai_docqa_documents_uploaded_total",
    documentation="Total documents uploaded and indexed",
    labelnames=["file_type", "status"],
    # file_type: pdf/docx/csv/pptx/txt/url
    # status: success/failed
)

# HOW TO UPDATE (in document_processor.py, Phase 3):
# DOCUMENTS_UPLOADED_TOTAL.labels(
#     file_type="pdf",
#     status="success"
# ).inc()


# ================================================================
# METRIC 7 — Chunks Created
# Counter: total vector chunks indexed into pgvector.
# ================================================================

CHUNKS_CREATED_TOTAL = Counter(
    name="genai_docqa_chunks_created_total",
    documentation="Total document chunks created and indexed in vector store",
    labelnames=["chunk_type", "chunking_strategy"],
    # chunk_type: parent/child
    # chunking_strategy: recursive/semantic/token_aware/sliding_window/parent_child
)

# HOW TO UPDATE (in document_processor.py, Phase 3):
# CHUNKS_CREATED_TOTAL.labels(
#     chunk_type="child",
#     chunking_strategy="parent_child"
# ).inc(len(child_chunks))


# ================================================================
# METRIC 8 — Active Sessions
# Gauge: current number of active chat sessions.
# Goes up when session starts, down when session ends.
# ================================================================

ACTIVE_SESSIONS = Gauge(
    name="genai_docqa_active_sessions",
    documentation="Number of currently active chat sessions",
)

# HOW TO UPDATE (in session manager, Phase 9):
# ACTIVE_SESSIONS.inc()   # session started
# ACTIVE_SESSIONS.dec()   # session ended


# ================================================================
# METRIC 9 — RAGAS Faithfulness Score
# Gauge: latest faithfulness score from RAGAS evaluation.
# Target: > 0.85. Below 0.70 → alert + CI/CD blocks deploy.
# ================================================================

RAGAS_FAITHFULNESS = Gauge(
    name="genai_docqa_ragas_faithfulness",
    documentation=(
        "Latest RAGAS faithfulness score (0-1). "
        "Measures if answer is grounded in retrieved context. "
        "Target: > 0.85. Alert threshold: < 0.70."
    ),
    labelnames=["provider", "model"],
)

# HOW TO UPDATE (in evaluation_service.py, Phase 10):
# RAGAS_FAITHFULNESS.labels(
#     provider="groq",
#     model="llama3"
# ).set(faithfulness_score)   # e.g. 0.87


# ================================================================
# METRIC 10 — RAGAS Answer Relevance Score
# Gauge: latest answer relevance score from RAGAS evaluation.
# Target: > 0.80.
# ================================================================

RAGAS_ANSWER_RELEVANCE = Gauge(
    name="genai_docqa_ragas_answer_relevance",
    documentation=(
        "Latest RAGAS answer relevance score (0-1). "
        "Measures if answer addresses what was asked. "
        "Target: > 0.80."
    ),
    labelnames=["provider", "model"],
)

# HOW TO UPDATE (in evaluation_service.py, Phase 10):
# RAGAS_ANSWER_RELEVANCE.labels(
#     provider="groq",
#     model="llama3"
# ).set(relevance_score)


# ================================================================
# METRIC 11 — LLM Provider Errors
# Counter: tracks failures per provider.
# High error rate on one provider → alert + switch to fallback.
# ================================================================

LLM_ERRORS_TOTAL = Counter(
    name="genai_docqa_llm_errors_total",
    documentation="Total LLM provider errors by type",
    labelnames=["provider", "model", "error_type"],
    # error_type: rate_limit/timeout/server_error/auth_error/context_length
)

# HOW TO UPDATE (in LLM router, Phase 5):
# LLM_ERRORS_TOTAL.labels(
#     provider="openai",
#     model="gpt-4o",
#     error_type="rate_limit"
# ).inc()


# ================================================================
# METRIC 12 — Rate Limit Hits
# Counter: tracks how often users hit rate limits.
# High rate = user is being blocked frequently → adjust limits.
# ================================================================

RATE_LIMIT_HITS_TOTAL = Counter(
    name="genai_docqa_rate_limit_hits_total",
    documentation="Total rate limit rejections by endpoint",
    labelnames=["endpoint", "user_tier"],
    # endpoint: /chat /upload /auth etc.
    # user_tier: free/pro/admin
)

# HOW TO UPDATE (in rate_limiter.py, Phase 2):
# RATE_LIMIT_HITS_TOTAL.labels(
#     endpoint="/api/v1/chat",
#     user_tier="free"
# ).inc()


# ================================================================
# SETUP FUNCTION
# Called once at startup from main.py
# ================================================================

def setup_prometheus() -> None:
    """
    Initialize Prometheus metrics.

    Called once at startup in main.py lifespan — after logging setup.

    WHY a setup function?
        Prometheus metrics are registered globally when defined.
        This function confirms they're all loaded and logs it.
        Also a good place to add any initialization logic in future.

    The /metrics endpoint is mounted in main.py:
        metrics_app = make_asgi_app()
        app.mount("/metrics", metrics_app)
    """
    log.info(
        "prometheus_metrics_initialized",
        metrics_count=12,
        metrics=[
            "genai_docqa_queries_total",
            "genai_docqa_query_latency_seconds",
            "genai_docqa_retrieval_latency_seconds",
            "genai_docqa_tokens_consumed_total",
            "genai_docqa_cost_usd_total",
            "genai_docqa_documents_uploaded_total",
            "genai_docqa_chunks_created_total",
            "genai_docqa_active_sessions",
            "genai_docqa_ragas_faithfulness",
            "genai_docqa_ragas_answer_relevance",
            "genai_docqa_llm_errors_total",
            "genai_docqa_rate_limit_hits_total",
        ],
        scrape_endpoint="/metrics",
        scrape_interval_seconds=15,
    )