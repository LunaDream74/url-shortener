# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A URL shortener service with click analytics, built with FastAPI + PostgreSQL + Redis, containerized with Docker, and deployed to AWS ECR via GitHub Actions CI/CD. The full implementation guide is in `url-shortener-weekend-guide.md`.

**Current status:** Fully implemented — application code, tests, Docker setup, and CI/CD pipeline are all in place.

## Development Commands

```bash
# Local dev (requires PostgreSQL + Redis running locally, or use Docker)
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload

# Run tests (uses SQLite + real Redis on localhost:6379)
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
├── database.py    # SQLAlchemy engine + SessionLocal; DATABASE_URL env var controls DB target
├── models.py      # ORM: URL table (short_code, original_url, clicks, created_at)
├── schemas.py     # Pydantic: URLCreate, URLResponse, URLStats
└── routes/
    └── urls.py    # Route handlers: POST /shorten, GET /{short_code}, GET /{short_code}/stats
tests/
└── test_api.py    # Integration tests using SQLite + Redis
```

**Key design decisions:**
- **DB URL:** `DATABASE_URL` env var; defaults to `postgresql://shortener:shortener@localhost:5432/shortener`. Tests override it to SQLite via `os.environ` before import.
- **Caching:** Redis cache-aside in the redirect handler — on cache hit, the original URL is served from Redis but the click increment still hits the DB. On cache miss, the DB is queried and the result is cached (TTL 1 hour).
- **Short code generation:** `shortuuid` library (8-char random code), stored in `URL.short_code` (unique, indexed).
- **Click tracking:** incremented atomically in the redirect handler before returning the 307 redirect.
- **Health check:** `GET /health` lives in `main.py`, not in the router.

## Docker / Deployment

- **Dockerfile:** Multi-stage build (builder + runtime), non-root `appuser` for security.
- **docker-compose.yml:** Three services — `db` (postgres:16-alpine), `cache` (redis:7-alpine), `app` (FastAPI). App waits for `db` healthcheck and `cache` start.
- **CI/CD:** GitHub Actions (`.github/workflows/deploy.yml`) — `test` job runs pytest with a live Redis service, then `build-and-push` job (main branch only) pushes image to AWS ECR with commit SHA + `latest` tags.
- **Required GitHub secrets:** `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `ECR_REPOSITORY`.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql://shortener:shortener@localhost:5432/shortener` | SQLAlchemy DB connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL |
| `BASE_URL` | `http://localhost:8000` | Used to build `short_url` in responses |

## Key Dependencies

All pinned in `requirements.txt`:
- `fastapi==0.111.0`, `uvicorn[standard]==0.30.1`
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
