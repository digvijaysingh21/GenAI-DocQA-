# GenAI DocQA Platform

> **Production-grade Agentic RAG + MCP Document Intelligence System**
> Upload documents. Ask complex questions. Get sourced, streamed answers powered by a 10-node LangGraph agent.

![Python](https://img.shields.io/badge/Python-3.12-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)
![LangGraph](https://img.shields.io/badge/LangGraph-0.2-orange)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16+pgvector-blue)
![Redis](https://img.shields.io/badge/Redis-7-red)
![Docker](https://img.shields.io/badge/Docker-Compose-blue)
![Phase](https://img.shields.io/badge/Phase-1%20of%2013-yellow)
![CI](https://img.shields.io/badge/CI-GitHub%20Actions-green)

---

## What Is This?

The GenAI DocQA Platform is a **production-grade Agentic RAG (Retrieval-Augmented Generation)
Document Intelligence System** built from scratch as an AI Engineer portfolio project.

Users upload documents in any format (PDF, DOCX, CSV, PPTX, TXT), ask complex natural language
questions, and receive **high-quality, sourced, token-streamed answers** powered by multiple LLM
providers through intelligent agentic workflows.

Every architectural decision has a reason. Every component is
production-thinking: cost control, fallback chains, safety guardrails, continuous evaluation,
and full observability.

---

## What This Looks Like in the Real World

| This System Resembles     | What It Does Here                                                 |
| ------------------------- | ----------------------------------------------------------------- |
| **Mini Perplexity AI**    | Web search fallback, streaming answers with source citations      |
| **Notion AI / Glean**     | Document Q&A, multi-collection scoping, auto-tagging              |
| **OpenAI API Platform**   | Multi-LLM routing, BYOK encrypted key management, fallback chains |
| **Production RAG System** | Hybrid search, CRAG, parent-child chunks, query decomposition     |
| **MLOps Platform**        | LangSmith tracing, Prometheus, Grafana, RAGAS eval gate in CI/CD  |
| **MCP-Enabled Platform**  | External tools callable by the agent via Model Context Protocol   |

---

## Tech Stack

### Backend

| Technology  | Version | Purpose                           |
| ----------- | ------- | --------------------------------- |
| Python      | 3.12    | Core language                     |
| FastAPI     | 0.115   | Async REST API + WebSocket + SSE  |
| SQLAlchemy  | 2.0     | Async ORM — `create_async_engine` |
| Alembic     | 1.14    | Database migrations               |
| Pydantic v2 | 2.10    | Data validation + typed settings  |
| Uvicorn     | 0.34    | ASGI server                       |

### AI / LLM

| Technology                  | Purpose                                            |
| --------------------------- | -------------------------------------------------- |
| LangGraph                   | 10-node agentic workflow (ReAct + CRAG)            |
| LangChain                   | Document loaders, text splitters, prompt templates |
| Groq                        | Default free LLM (LLaMA 3, 14,400 req/day free)    |
| OpenAI / Anthropic / Gemini | Premium LLM providers (optional BYOK)              |
| Sentence-Transformers       | Local free embeddings (all-MiniLM-L6-v2)           |
| Cohere                      | Reranking API (free tier: 1000 calls/month)        |
| LangSmith                   | Agent tracing and observability                    |
| RAGAS                       | RAG evaluation framework                           |

### Database & Storage

| Technology    | Purpose                                               |
| ------------- | ----------------------------------------------------- |
| PostgreSQL 16 | Primary database                                      |
| pgvector      | Vector similarity search (HNSW index)                 |
| Redis 7       | Rate limiting, query cache, embedding cache, sessions |
| Cloudflare R2 | Object storage for uploaded files (production)        |

### Infrastructure

| Technology       | Purpose                                     |
| ---------------- | ------------------------------------------- |
| Docker + Compose | Multi-service local development             |
| GitHub Actions   | CI (lint + type check + test) + CD (deploy) |
| Prometheus       | Metrics collection                          |
| Grafana          | Metrics dashboards                          |
| Nginx            | Reverse proxy (production)                  |

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        CLIENT                               │
│              React + Vite + Tailwind                        │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP / WebSocket / SSE
┌──────────────────────────▼──────────────────────────────────┐
│                      NGINX (prod)                           │
│              Reverse proxy + SSL termination                │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                   FASTAPI BACKEND                           │
│                                                             │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │  Auth Layer │  │  Rate Limit  │  │  Cost Guard      │   │
│  │  JWT + bcrypt│  │  Redis       │  │  Budget Check    │   │
│  └─────────────┘  └──────────────┘  └──────────────────┘   │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              LANGGRAPH AGENT (10 nodes)              │   │
│  │                                                      │   │
│  │  classify → decompose → rewrite → retrieve → grade  │   │
│  │       → generate → critique → cite → stream         │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │  Hybrid      │  │  LLM Router  │  │  Safety Layer    │   │
│  │  Search      │  │  7 providers │  │  PII + Injection │   │
│  │  BM25+Vector │  │  + fallback  │  │  Detection       │   │
│  └──────────────┘  └──────────────┘  └──────────────────┘   │
└────────┬─────────────────┬────────────────────┬─────────────┘
         │                 │                    │
┌────────▼──────┐  ┌───────▼───────┐  ┌────────▼──────────┐
│  PostgreSQL   │  │    Redis      │  │  Cloudflare R2    │
│  + pgvector   │  │  Cache+Queue  │  │  File Storage     │
│  HNSW index   │  │               │  │                   │
└───────────────┘  └───────────────┘  └───────────────────┘
```

---

## Key Features

### Document Intelligence

- Upload PDF, DOCX, CSV, PPTX, TXT (up to 50MB)
- Scanned PDF OCR via Tesseract
- Table extraction from PDFs
- 5 chunking strategies: recursive, semantic, token-aware, sliding window, parent-child
- SHA256 deduplication — never index same content twice
- Real-time WebSocket upload progress

### RAG Engine

- Hybrid search: dense vector (pgvector) + BM25 keyword search
- RRF fusion (vector weight 0.6, BM25 weight 0.4)
- Three-tier reranking: Cohere → cross-encoder → RRF passthrough
- Parent-child chunking: retrieve child (128 tokens) → return parent context (512 tokens)
- Query rewriting + decomposition for complex multi-part questions
- Corrective RAG (CRAG): grade retrieval quality → fallback to web search if poor

### Multi-LLM Support

- 7 providers: Groq, OpenAI, Anthropic, Gemini, Mistral, Cohere, Ollama
- Smart routing: simple queries → cheap model, complex → premium model
- Automatic fallback chain on provider failure
- BYOK: users store their own encrypted API keys (AES-256-GCM)

### Production Features

- JWT auth: 15-min access token + 7-day refresh with rotation
- Redis sliding window rate limiting per endpoint
- Prompt injection detection (12 regex patterns + LLM classifier)
- PII masking on all LLM outputs (Microsoft Presidio)
- Full LangSmith tracing — every agent run is observable
- 12 Prometheus metrics → Grafana dashboards
- RAGAS evaluation: faithfulness, relevance, context recall (target > 0.85)
- Budget enforcement: daily + monthly spend limits per user

---

## Project Status — 13 Phases

| Phase  | Name                      | Status         | What Gets Built                               |
| ------ | ------------------------- | -------------- | --------------------------------------------- |
| **01** | Project Scaffold          | 🔨 In Progress | FastAPI app, Docker, DB, config, health check |
| **02** | Auth & Security           | ⬜ Next        | JWT, bcrypt, AES encryption, rate limiting    |
| **03** | Document Ingestion        | ⬜             | Parsers, chunking, WebSocket progress         |
| **04** | Embeddings & Vector Store | ⬜             | pgvector, BM25, hybrid search, reranking      |
| **05** | LLM Router                | ⬜             | 7 providers, fallback chain, cost tracking    |
| **06** | RAG Pipeline              | ⬜             | Prompt engineering, query rewriting, CRAG     |
| **07** | LangGraph Agent           | ⬜             | 10-node agent, self-correction loops          |
| **08** | MCP Integration           | ⬜             | Model Context Protocol tool calling           |
| **09** | Streaming & Sessions      | ⬜             | SSE streaming, conversation memory            |
| **10** | Safety & Evaluation       | ⬜             | PII, injection defense, RAGAS CI gate         |
| **11** | React Frontend            | ⬜             | Upload UI, chat interface, streaming          |
| **12** | Advanced UI               | ⬜             | Dashboards, settings, answer comparison       |
| **13** | Production Deploy         | ⬜             | Nginx, Railway/Fly.io, final polish           |

---

## Getting Started

### Prerequisites

- Docker + Docker Compose
- Python 3.12+
- Git

### 1. Clone the repository

```bash
git clone https://github.com/digvijaysingh21/genai-docqa.git
cd genai-docqa
```

### 2. Set up environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in:

```bash
# Generate secrets
openssl rand -hex 32   # paste as SECRET_KEY
openssl rand -hex 32   # paste as ENCRYPTION_KEY

# Get free Groq key at https://console.groq.com
GROQ_API_KEY=your-key-here
```

### 3. Start the services

```bash
cd infrastructure
docker compose up
```

This starts:

- PostgreSQL 16 with pgvector extension
- Redis 7
- FastAPI backend

### 4. Run database migrations

```bash
docker compose exec backend alembic upgrade head
```

### 5. Verify everything works

```bash
# Health check
curl http://localhost:8000/api/v1/health

# Readiness check (checks DB + Redis)
curl http://localhost:8000/api/v1/ready

# Interactive API docs
open http://localhost:8000/docs
```

Expected response:

```json
{ "status": "ok", "version": "1.0.0" }
```

---

## API Endpoints (Phase 1)

| Method | Endpoint         | Description                             |
| ------ | ---------------- | --------------------------------------- |
| `GET`  | `/api/v1/health` | Liveness check — is the process alive?  |
| `GET`  | `/api/v1/ready`  | Readiness check — DB + Redis connected? |
| `GET`  | `/metrics`       | Prometheus metrics scrape endpoint      |
| `GET`  | `/docs`          | Interactive Swagger UI                  |
| `GET`  | `/redoc`         | ReDoc API documentation                 |

More endpoints added each phase.

---

## Project Structure

```
genai-platform/
├── .env.example                 # Environment variables template
├── .gitignore                   # Git ignore rules
├── README.md                    # This file
│
├── .github/
│   └── workflows/
│       ├── ci.yml               # CI: lint + type check + test
│       └── deploy.yml           # CD: build + deploy on main merge
│
├── backend/
│   ├── requirements.txt         # All Python dependencies (pinned)
│   ├── pyproject.toml           # ruff + mypy + pytest config
│   ├── Dockerfile               # Multi-stage production build
│   ├── alembic.ini              # Alembic migration config
│   │
│   ├── alembic/
│   │   ├── env.py               # Async migration runner
│   │   └── versions/            # Migration files (auto-generated)
│   │
│   └── app/
│       ├── main.py              # FastAPI app, lifespan, middleware
│       ├── config.py            # Pydantic Settings — typed env vars
│       ├── dependencies.py      # FastAPI Depends() — DB, Redis, auth
│       │
│       ├── db/
│       │   ├── database.py      # Async engine + session factory
│       │   └── init_db.py       # pgvector extension + seed admin
│       │
│       ├── monitoring/
│       │   ├── logger.py        # Structured JSON logging (structlog)
│       │   └── metrics.py       # 12 Prometheus metrics defined
│       │
│       └── api/v1/
│           └── health.py        # /health + /ready endpoints
│
└── infrastructure/
    └── docker-compose.yml       # PostgreSQL + Redis + Backend
```

---

## Environment Variables

See [`.env.example`](.env.example) for the complete list with descriptions.

Key variables:

| Variable         | Required | Description                                       |
| ---------------- | -------- | ------------------------------------------------- |
| `DATABASE_URL`   | ✅       | PostgreSQL connection (must use `asyncpg` driver) |
| `REDIS_URL`      | ✅       | Redis connection                                  |
| `SECRET_KEY`     | ✅       | JWT signing key (min 32 chars)                    |
| `ENCRYPTION_KEY` | ✅       | AES-256-GCM key for LLM API key storage           |
| `GROQ_API_KEY`   | ✅       | Default LLM provider (free at console.groq.com)   |
| `ENVIRONMENT`    | ✅       | `development` or `production`                     |

---

## Free Resources Used

| Service                                    | What For      | Free Tier           |
| ------------------------------------------ | ------------- | ------------------- |
| [Groq](https://console.groq.com)           | Default LLM   | 14,400 req/day      |
| [LangSmith](https://smith.langchain.com)   | Agent tracing | 5,000 traces/month  |
| [Cohere](https://cohere.com)               | Reranking     | 1,000 calls/month   |
| [Cloudflare R2](https://cloudflare.com/r2) | File storage  | 10GB + 1M req/month |
| GitHub Actions                             | CI/CD         | 2,000 min/month     |

**Total cost to run this project: $0**

---

## Author

**Digvijay Singh Rajput**
Full-Stack & AI Engineer | Building in public

- GitHub: [@digvijaysingh21](https://github.com/digvijaysingh21)
- LinkedIn: [Digvijay Singh Rajput](https://linkedin.com/in/digvijay-singh-rajput)

---

## License

MIT License — see [LICENSE](LICENSE) for details.
