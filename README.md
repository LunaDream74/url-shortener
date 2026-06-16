# URL Shortener

A URL shortener service with click analytics built with FastAPI, PostgreSQL, and Redis. Containerized with Docker and deployed to AWS EC2 via GitHub Actions.

**Live demo:** http://18.142.136.63:8000/docs

## Performance

Benchmarked against the live deployment (200 sequential requests, single client, measured from outside AWS — network RTT included):

| Metric | Value |
|--------|-------|
| p50 latency | 62 ms |
| p95 latency | 160 ms |
| p99 latency | 387 ms |
| Throughput | 12.4 req/s (single client) |

> Numbers reflect internet round-trip to `ap-southeast-1`. Server-side latency is significantly lower.

## Features

- Shorten any URL to an 8-character code
- 307 redirects with click tracking on every visit
- Per-URL stats (click count, creation time)
- Redis cache-aside for fast redirects
- Docker Compose stack for local development
- CI/CD pipeline that pushes to AWS ECR on every merge to main

## Quick Start

### Docker (recommended)

```bash
docker compose up --build
```

### Local (no Docker)

Requires PostgreSQL and Redis running locally.

```bash
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## API

### Shorten a URL

```bash
curl -X POST http://18.142.136.63:8000/shorten \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'
```

```json
{
  "short_code": "aB3xYz9q",
  "original_url": "https://example.com/",
  "short_url": "http://18.142.136.63:8000/aB3xYz9q",
  "clicks": 0,
  "created_at": "2026-06-16T00:00:00"
}
```

### Redirect

```
GET /{short_code}
```

Returns a `307 Temporary Redirect` to the original URL and increments the click counter.

### Stats

```bash
curl http://18.142.136.63:8000/aB3xYz9q/stats
```

```json
{
  "short_code": "aB3xYz9q",
  "original_url": "https://example.com/",
  "clicks": 5,
  "created_at": "2026-06-16T00:00:00"
}
```

### Health check

```
GET /health  →  {"status": "healthy"}
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql://shortener:shortener@localhost:5432/shortener` | SQLAlchemy connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL |
| `BASE_URL` | `http://18.142.136.63:8000` | Prefix used in `short_url` responses |

In Docker Compose these are set automatically. For production, override them via your environment or a `.env` file.

## Running Tests

Tests use SQLite (in-memory) and require Redis on `localhost:6379`.

```bash
pytest tests/ -v
```

## Deployment

The GitHub Actions workflow (`.github/workflows/deploy.yml`) runs on every push to `main`:

1. **test** — runs pytest with a live Redis service container
2. **build-and-push** — builds the Docker image and pushes to AWS ECR (tagged with commit SHA and `latest`)

### Required GitHub Secrets

| Secret | Description |
|--------|-------------|
| `AWS_ACCESS_KEY_ID` | IAM user access key |
| `AWS_SECRET_ACCESS_KEY` | IAM user secret key |
| `AWS_REGION` | ECR region (e.g. `us-east-1`) |
| `ECR_REPOSITORY` | ECR repository name |

## Project Structure

```
app/
├── main.py          # App init, lifespan, health endpoint
├── database.py      # SQLAlchemy engine and session
├── models.py        # URL ORM model
├── schemas.py       # Pydantic request/response models
└── routes/
    └── urls.py      # /shorten, /{short_code}, /{short_code}/stats
tests/
└── test_api.py      # Integration tests
Dockerfile           # Multi-stage build, non-root user
docker-compose.yml   # PostgreSQL + Redis + FastAPI
```

## Tech Stack

- **API:** FastAPI 0.111, Uvicorn 0.30
- **Database:** PostgreSQL 16 (SQLAlchemy 2.0)
- **Cache:** Redis 7
- **Containerization:** Docker (multi-stage), Docker Compose
- **CI/CD:** GitHub Actions → AWS ECR
