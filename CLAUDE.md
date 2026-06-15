# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A URL shortener service with click analytics, built with FastAPI + PostgreSQL + Redis, containerized with Docker, and deployed to AWS EC2 via GitHub Actions CI/CD. The full implementation guide is in `url-shortener-weekend-guide.md`.

**Current status:** Directory scaffolding exists (`app/`, `tests/` with empty `__init__.py` files); application code has not yet been written.

## Development Commands

```bash
# Local dev (SQLite, no Docker)
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload

# Run tests
pytest tests/ -v
pytest tests/test_api.py::test_name -v   # single test

# Docker full stack (PostgreSQL + Redis + FastAPI)
docker compose up --build
docker compose up -d                     # detached
docker compose logs -f app               # follow logs
docker compose down -v                   # stop and wipe volumes
```

## Architecture

```
app/
├── main.py        # FastAPI app init, lifespan handler (creates DB tables), mounts routes
├── database.py    # SQLAlchemy engine + SessionLocal; DATABASE_URL env var switches SQLite↔Postgres
├── models.py      # ORM: URL table (short_code, original_url, clicks, created_at)
├── schemas.py     # Pydantic: ShortenRequest, URLResponse, StatsResponse
└── routes/
    └── urls.py    # Route handlers: POST /shorten, GET /{short_code}, GET /{short_code}/stats, GET /health
```

**Key design decisions from the guide:**
- **Dev vs prod DB:** `DATABASE_URL` env var; defaults to SQLite (`./urls.db`) locally, PostgreSQL in Docker/prod.
- **Caching:** Redis cache-aside pattern in the redirect handler (`GET /{short_code}`) — cache hit skips DB lookup. TTL-based invalidation, no cache on write.
- **Short code generation:** `shortuuid` library, stored in `URL.short_code` column (unique, indexed).
- **Click tracking:** incremented in the redirect handler before returning the 307 redirect.

## Docker / Deployment

- **Dockerfile:** Multi-stage build (builder + runtime), non-root user for security.
- **docker-compose.yml:** Three services — `db` (postgres:16-alpine), `redis` (redis:7-alpine), `app` (FastAPI). App depends on both with health checks.
- **CI/CD:** GitHub Actions workflow (`.github/workflows/deploy.yml`) — `test` job runs pytest, then `build-and-push` job pushes image to AWS ECR. Tags: commit SHA + `latest`.
- **Deployment target:** AWS EC2 t2.micro (Amazon Linux 2023). EC2 pulls from ECR and runs `docker compose up -d`.

## Key Dependencies

See `requirements.txt` (to be created). Pin versions from the guide:
- `fastapi==0.111.0`, `uvicorn==0.30.1`
- `sqlalchemy==2.0.31`, `psycopg2-binary==2.9.9`
- `redis==5.0.7`, `shortuuid==1.0.13`
- `httpx==0.27.0` (test client), `pytest==8.2.2`
- `python-dotenv==1.0.1`

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/shorten` | Create short URL; body: `{"url": "https://..."}` |
| GET | `/{short_code}` | Redirect (307) + increment click count |
| GET | `/{short_code}/stats` | Return click count and created_at |
| GET | `/health` | Liveness check |
