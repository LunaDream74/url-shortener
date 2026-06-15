# URL Shortener with Analytics — Docker + AWS Weekend Project

A step-by-step guide to building a production-style URL shortener with Python/FastAPI, Docker, and AWS. By the end you'll have a multi-container app with CI/CD deployed to the cloud.

**What you'll learn:** Docker fundamentals → multi-container orchestration → CI/CD pipelines → cloud deployment.

**Final architecture:**
```
Client → FastAPI app → PostgreSQL (storage)
                     → Redis (caching)
GitHub push → GitHub Actions → ECR → EC2
```

---

## Prerequisites

Install these before starting:

- **Python 3.11+**: `python --version`
- **Docker Desktop**: [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/) — install and make sure it's running
- **Git**: `git --version`
- **An AWS account**: [aws.amazon.com/free](https://aws.amazon.com/free/) (free tier is fine)
- **A GitHub account**

Create your project:
```bash
mkdir url-shortener && cd url-shortener
git init
```

---

## Phase 1: Build the FastAPI App

We'll start with a working API using an in-memory store. No Docker yet — just get the app running locally so you understand what you're containerizing.

### 1.1 — Project structure

Create this layout:
```
url-shortener/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── models.py
│   ├── schemas.py
│   ├── database.py
│   └── routes/
│       ├── __init__.py
│       └── urls.py
├── requirements.txt
└── .gitignore
```

```bash
mkdir -p app/routes
touch app/__init__.py app/routes/__init__.py
```

### 1.2 — requirements.txt

```txt
fastapi==0.111.0
uvicorn[standard]==0.30.1
sqlalchemy==2.0.31
psycopg2-binary==2.9.9
redis==5.0.7
python-dotenv==1.0.1
shortuuid==1.0.13
httpx==0.27.0
```

Install locally for now:
```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 1.3 — app/database.py

This sets up SQLAlchemy. Right now it points at SQLite so you can run locally without Postgres. We'll swap to Postgres in Phase 3.

```python
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./shortener.db")

# SQLite needs connect_args; Postgres doesn't
connect_args = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

**What's happening:** `create_engine` is SQLAlchemy's connection to your database. `SessionLocal` creates individual sessions for each request. `get_db` is a FastAPI dependency — it gives each request its own database session and cleans up after.

### 1.4 — app/models.py

The database table for stored URLs:

```python
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, DateTime, Text

from app.database import Base


class URL(Base):
    __tablename__ = "urls"

    id = Column(Integer, primary_key=True, index=True)
    short_code = Column(String(20), unique=True, index=True, nullable=False)
    original_url = Column(Text, nullable=False)
    clicks = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
```

**What's happening:** Each shortened URL gets a unique `short_code`, stores the `original_url`, and tracks `clicks`. The `index=True` on `short_code` is important — it makes lookups fast, which matters because every redirect hits this column.

### 1.5 — app/schemas.py

Pydantic models for request/response validation:

```python
from datetime import datetime
from pydantic import BaseModel, HttpUrl


class URLCreate(BaseModel):
    url: HttpUrl


class URLResponse(BaseModel):
    short_code: str
    original_url: str
    short_url: str
    clicks: int
    created_at: datetime

    model_config = {"from_attributes": True}


class URLStats(BaseModel):
    short_code: str
    original_url: str
    clicks: int
    created_at: datetime

    model_config = {"from_attributes": True}
```

**What's happening:** `HttpUrl` automatically validates that incoming URLs are well-formed. `model_config = {"from_attributes": True}` lets Pydantic read directly from SQLAlchemy model instances. These schemas separate your API contract from your database schema — a good practice even for small projects.

### 1.6 — app/routes/urls.py

The actual API endpoints:

```python
import os
import shortuuid
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import URL
from app.schemas import URLCreate, URLResponse, URLStats

router = APIRouter()

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")


@router.post("/shorten", response_model=URLResponse, status_code=201)
def create_short_url(payload: URLCreate, db: Session = Depends(get_db)):
    short_code = shortuuid.ShortUUID().random(length=8)

    db_url = URL(short_code=short_code, original_url=str(payload.url))
    db.add(db_url)
    db.commit()
    db.refresh(db_url)

    return URLResponse(
        short_code=db_url.short_code,
        original_url=db_url.original_url,
        short_url=f"{BASE_URL}/{db_url.short_code}",
        clicks=db_url.clicks,
        created_at=db_url.created_at,
    )


@router.get("/{short_code}")
def redirect_to_url(short_code: str, db: Session = Depends(get_db)):
    db_url = db.query(URL).filter(URL.short_code == short_code).first()
    if not db_url:
        raise HTTPException(status_code=404, detail="Short URL not found")

    db_url.clicks += 1
    db.commit()

    return RedirectResponse(url=db_url.original_url, status_code=307)


@router.get("/{short_code}/stats", response_model=URLStats)
def get_url_stats(short_code: str, db: Session = Depends(get_db)):
    db_url = db.query(URL).filter(URL.short_code == short_code).first()
    if not db_url:
        raise HTTPException(status_code=404, detail="Short URL not found")

    return db_url
```

**What's happening:**

- `POST /shorten` — takes a URL, generates a random 8-char code, stores it, returns the short URL.
- `GET /{short_code}` — looks up the code, increments the click counter, redirects with HTTP 307 (preserves the original HTTP method).
- `GET /{short_code}/stats` — returns click count and metadata without redirecting.

`Depends(get_db)` is FastAPI's dependency injection — it automatically creates a DB session for each request and closes it after.

### 1.7 — app/main.py

Ties everything together:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.database import engine, Base
from app.routes.urls import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)  # Create tables on startup
    yield


app = FastAPI(
    title="URL Shortener",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)


@app.get("/health")
def health_check():
    return {"status": "healthy"}
```

**What's happening:** The `lifespan` context manager runs `create_all` on startup — this creates your database tables if they don't exist. The `/health` endpoint is crucial for Docker and AWS — it's how they know your app is alive.

### 1.8 — .gitignore

```gitignore
venv/
__pycache__/
*.pyc
.env
*.db
```

### 1.9 — Test it locally

```bash
uvicorn app.main:app --reload
```

Open `http://localhost:8000/docs` — FastAPI auto-generates interactive API docs. Try:

1. `POST /shorten` with `{"url": "https://github.com"}` — you'll get back a short code
2. Visit the short URL in your browser — it should redirect to GitHub
3. `GET /{short_code}/stats` — should show 1 click
4. `GET /health` — should return `{"status": "healthy"}`

**Checkpoint:** If all four work, your app is solid. Commit it:
```bash
git add .
git commit -m "feat: URL shortener API with FastAPI"
```

---

## Phase 2: Your First Dockerfile

Now you'll containerize the app. The goal: anyone with Docker can run your app with one command, regardless of their OS or Python version.

### 2.1 — What is Docker, in 30 seconds

A Docker **image** is a snapshot of an OS + your app + all its dependencies. A **container** is a running instance of that image. A **Dockerfile** is the recipe that builds the image.

Think of it like: Dockerfile (recipe) → Image (frozen meal) → Container (meal being eaten).

### 2.2 — Dockerfile

Create this at the project root:

```dockerfile
# --- Stage 1: Build dependencies ---
FROM python:3.11-slim AS builder

WORKDIR /app

# Install dependencies into a virtual env so we can copy just that folder
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- Stage 2: Runtime image ---
FROM python:3.11-slim

WORKDIR /app

# Copy only the virtual env from the builder — no pip cache, no build tools
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY ./app ./app

# Non-root user (security best practice)
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Line-by-line explanation:**

| Line | What it does | Why it matters |
|------|-------------|----------------|
| `FROM python:3.11-slim AS builder` | Uses a minimal Python base image for the build stage | `slim` is ~150MB vs ~900MB for the full image |
| `WORKDIR /app` | Sets the working directory inside the container | Like `cd /app` |
| `COPY requirements.txt .` | Copies just requirements first | Docker caches this layer — if requirements don't change, deps aren't reinstalled |
| `FROM python:3.11-slim` | Starts a fresh image for runtime | The builder stage's pip cache and build tools are thrown away |
| `COPY --from=builder` | Copies only the virtual env from stage 1 | Final image has no build artifacts — smaller and more secure |
| `RUN useradd ...` / `USER appuser` | Runs the app as non-root | If someone exploits your app, they don't get root access |
| `--host 0.0.0.0` | Listens on all interfaces | Required inside Docker — `localhost` won't work |

This is a **multi-stage build** — one of the techniques that shows you know what you're doing. The final image is small and has no unnecessary tools an attacker could exploit.

### 2.3 — .dockerignore

```
venv/
__pycache__/
*.pyc
.env
*.db
.git/
```

This prevents sending unnecessary files into the Docker build context — faster builds.

### 2.4 — Build and run

```bash
docker build -t url-shortener .
docker run -p 8000:8000 url-shortener
```

`-t url-shortener` gives your image a name. `-p 8000:8000` maps port 8000 on your machine to port 8000 in the container.

Test it: `http://localhost:8000/docs` should work exactly like before.

**Useful Docker commands to know:**
```bash
docker ps                  # List running containers
docker ps -a               # List all containers (including stopped)
docker images              # List images
docker stop <container_id> # Stop a container
docker logs <container_id> # View container output
docker exec -it <id> bash  # Shell into a running container
```

**Checkpoint:** Commit.
```bash
git add .
git commit -m "feat: add multi-stage Dockerfile"
```

---

## Phase 3: docker-compose — Multi-Container Setup

A real app doesn't run alone. You need a database and a cache. `docker-compose` lets you define and run multiple containers as a single unit.

### 3.1 — What docker-compose does

Instead of running three separate `docker run` commands with networking flags, you write one YAML file and run `docker compose up`. It handles networking, volumes, startup order, and environment variables.

### 3.2 — Update app/database.py for Postgres

Replace the DATABASE_URL default:

```python
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://shortener:shortener@localhost:5432/shortener",
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

We removed the SQLite connect_args since we're now targeting Postgres.

### 3.3 — Add Redis caching to redirects

Update `app/routes/urls.py`:

```python
import os
import redis
import shortuuid
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import URL
from app.schemas import URLCreate, URLResponse, URLStats

router = APIRouter()

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

cache = redis.from_url(REDIS_URL, decode_responses=True)


@router.post("/shorten", response_model=URLResponse, status_code=201)
def create_short_url(payload: URLCreate, db: Session = Depends(get_db)):
    short_code = shortuuid.ShortUUID().random(length=8)

    db_url = URL(short_code=short_code, original_url=str(payload.url))
    db.add(db_url)
    db.commit()
    db.refresh(db_url)

    # Cache the mapping so redirects don't hit the DB
    cache.set(f"url:{short_code}", db_url.original_url, ex=3600)

    return URLResponse(
        short_code=db_url.short_code,
        original_url=db_url.original_url,
        short_url=f"{BASE_URL}/{db_url.short_code}",
        clicks=db_url.clicks,
        created_at=db_url.created_at,
    )


@router.get("/{short_code}")
def redirect_to_url(short_code: str, db: Session = Depends(get_db)):
    # Try cache first
    cached_url = cache.get(f"url:{short_code}")

    if cached_url:
        # Still increment clicks in DB (fire-and-forget is fine here)
        db_url = db.query(URL).filter(URL.short_code == short_code).first()
        if db_url:
            db_url.clicks += 1
            db.commit()
        return RedirectResponse(url=cached_url, status_code=307)

    # Cache miss — query DB
    db_url = db.query(URL).filter(URL.short_code == short_code).first()
    if not db_url:
        raise HTTPException(status_code=404, detail="Short URL not found")

    db_url.clicks += 1
    db.commit()

    # Populate cache for next time
    cache.set(f"url:{short_code}", db_url.original_url, ex=3600)

    return RedirectResponse(url=db_url.original_url, status_code=307)


@router.get("/{short_code}/stats", response_model=URLStats)
def get_url_stats(short_code: str, db: Session = Depends(get_db)):
    db_url = db.query(URL).filter(URL.short_code == short_code).first()
    if not db_url:
        raise HTTPException(status_code=404, detail="Short URL not found")

    return db_url
```

**Why Redis?** Without caching, every redirect hits Postgres. With thousands of redirects per second, that's expensive. Redis stores the `short_code → URL` mapping in memory with a 1-hour TTL (`ex=3600`). Cache hit = ~0.1ms. DB query = ~2-5ms. That 20-50x speedup is why every production URL shortener uses a cache.

### 3.4 — docker-compose.yml

Create at the project root:

```yaml
services:
  app:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://shortener:shortener@db:5432/shortener
      - REDIS_URL=redis://cache:6379/0
      - BASE_URL=http://localhost:8000
    depends_on:
      db:
        condition: service_healthy
      cache:
        condition: service_started
    restart: unless-stopped

  db:
    image: postgres:16-alpine
    environment:
      - POSTGRES_USER=shortener
      - POSTGRES_PASSWORD=shortener
      - POSTGRES_DB=shortener
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U shortener"]
      interval: 5s
      timeout: 5s
      retries: 5

  cache:
    image: redis:7-alpine
    volumes:
      - redis_data:/var/lib/redis/data

volumes:
  postgres_data:
  redis_data:
```

**Key concepts:**

| Concept | What it does |
|---------|-------------|
| `depends_on` + `condition: service_healthy` | App waits for Postgres to be *actually ready*, not just started. Without this, your app would crash trying to connect to a DB that's still initializing. |
| `volumes: postgres_data:...` | Data persists even if you destroy and recreate the container. Without volumes, you lose everything on `docker compose down`. |
| `@db` and `@cache` in URLs | Docker Compose creates a network where services find each other by name. `db` resolves to the Postgres container's IP. |
| `postgres:16-alpine` | Alpine images are tiny (~80MB vs ~400MB). Less to download, less attack surface. |
| `restart: unless-stopped` | Container restarts if it crashes. |

### 3.5 — Run the full stack

```bash
docker compose up --build
```

`--build` rebuilds your app image. You'll see logs from all three services interleaved. Test everything again at `http://localhost:8000/docs`.

Useful commands:
```bash
docker compose up -d        # Run in background (detached)
docker compose logs -f app   # Follow logs for just the app
docker compose down          # Stop and remove containers
docker compose down -v       # Also delete volumes (wipes data)
docker compose ps            # Status of all services
```

**Checkpoint:**
```bash
git add .
git commit -m "feat: docker-compose with Postgres + Redis"
```

---

## Phase 4: CI/CD with GitHub Actions

Every push to `main` will automatically build your Docker image, run tests, and push to AWS ECR (Elastic Container Registry). This is the pipeline that makes interviewers pay attention.

### 4.1 — Add a basic test

Create `tests/test_api.py`:

```python
from fastapi.testclient import TestClient

# Override DB to use SQLite for tests (no Postgres needed in CI)
import os
os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


def test_shorten_and_stats():
    r = client.post("/shorten", json={"url": "https://example.com"})
    assert r.status_code == 201
    data = r.json()
    assert "short_code" in data

    # Check stats
    r = client.get(f"/{data['short_code']}/stats")
    assert r.status_code == 200
    assert r.json()["clicks"] == 0


def test_redirect():
    r = client.post("/shorten", json={"url": "https://example.com"})
    short_code = r.json()["short_code"]

    r = client.get(f"/{short_code}", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "https://example.com"


def test_not_found():
    r = client.get("/nonexistent")
    assert r.status_code == 404
```

Add `pytest` to your `requirements.txt`:
```
pytest==8.2.2
```

**Note:** These tests use SQLite and will skip Redis operations if Redis isn't available. For a weekend project, this is fine. In production you'd use testcontainers or mock Redis.

### 4.2 — AWS setup (one-time)

You need three things from AWS. Do this in the AWS Console:

**a) Create an ECR repository:**
1. Go to AWS Console → ECR → Create repository
2. Name it `url-shortener`
3. Keep "Private" selected
4. Note your repository URI (looks like `123456789.dkr.ecr.us-east-1.amazonaws.com/url-shortener`)

**b) Create an IAM user for CI/CD:**
1. IAM → Users → Create user → Name: `github-actions`
2. Attach policy: `AmazonEC2ContainerRegistryPowerUser`
3. Create access key → select "Third-party service"
4. Save the Access Key ID and Secret Access Key

**c) Add secrets to GitHub:**
1. Your repo → Settings → Secrets and variables → Actions
2. Add these repository secrets:
   - `AWS_ACCESS_KEY_ID`
   - `AWS_SECRET_ACCESS_KEY`
   - `AWS_REGION` (e.g., `us-east-1`)
   - `ECR_REPOSITORY` (just the name: `url-shortener`)
   - `AWS_ACCOUNT_ID` (your 12-digit account ID)

### 4.3 — GitHub Actions workflow

Create `.github/workflows/deploy.yml`:

```yaml
name: Build & Push to ECR

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

env:
  AWS_REGION: ${{ secrets.AWS_REGION }}

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install -r requirements.txt pytest

      - name: Run tests
        run: pytest tests/ -v

  build-and-push:
    needs: test
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'

    steps:
      - uses: actions/checkout@v4

      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: ${{ secrets.AWS_REGION }}

      - name: Login to ECR
        id: login-ecr
        uses: aws-actions/amazon-ecr-login@v2

      - name: Build, tag, and push image
        env:
          ECR_REGISTRY: ${{ steps.login-ecr.outputs.registry }}
          ECR_REPOSITORY: ${{ secrets.ECR_REPOSITORY }}
          IMAGE_TAG: ${{ github.sha }}
        run: |
          docker build -t $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG .
          docker build -t $ECR_REGISTRY/$ECR_REPOSITORY:latest .
          docker push $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG
          docker push $ECR_REGISTRY/$ECR_REPOSITORY:latest
```

**What this does:**

1. **On every push/PR:** runs your tests
2. **On push to main (only):** builds the Docker image and pushes it to ECR with two tags — the commit SHA (for rollbacks) and `latest` (for convenience)

The `needs: test` ensures the image only gets pushed if tests pass. The `if: github.ref == 'refs/heads/main'` prevents pushes from PRs.

**Checkpoint:**
```bash
mkdir -p .github/workflows tests
# (create the files above)
git add .
git commit -m "feat: CI/CD pipeline with GitHub Actions + ECR"
git remote add origin https://github.com/YOUR_USERNAME/url-shortener.git
git push -u origin main
```

---

## Phase 5: Deploy to AWS EC2

### 5.1 — Launch an EC2 instance

1. AWS Console → EC2 → Launch Instance
2. Settings:
   - **Name:** `url-shortener`
   - **AMI:** Amazon Linux 2023 (free tier eligible)
   - **Instance type:** `t2.micro` (free tier)
   - **Key pair:** Create a new one, download the `.pem` file
   - **Security group:** Allow inbound:
     - SSH (port 22) from your IP
     - HTTP (port 80) from anywhere
     - Custom TCP (port 8000) from anywhere
3. Launch the instance

### 5.2 — Set up the server

SSH in:
```bash
ssh -i your-key.pem ec2-user@<your-ec2-public-ip>
```

Install Docker and Docker Compose:
```bash
# Install Docker
sudo dnf update -y
sudo dnf install -y docker
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker ec2-user

# Install Docker Compose plugin
sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -SL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64" \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# Log out and back in for group changes to take effect
exit
```

SSH back in, verify:
```bash
ssh -i your-key.pem ec2-user@<your-ec2-public-ip>
docker --version
docker compose version
```

### 5.3 — Authenticate with ECR

```bash
aws configure
# Enter your AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, region

# Login to ECR
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin \
  123456789.dkr.ecr.us-east-1.amazonaws.com
```

Replace `123456789` with your actual AWS account ID and `us-east-1` with your region.

### 5.4 — Create production docker-compose

On the EC2 instance, create `~/url-shortener/docker-compose.yml`:

```bash
mkdir ~/url-shortener && cd ~/url-shortener
cat > docker-compose.yml << 'EOF'
services:
  app:
    image: 123456789.dkr.ecr.us-east-1.amazonaws.com/url-shortener:latest
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://shortener:CHANGE_THIS_PASSWORD@db:5432/shortener
      - REDIS_URL=redis://cache:6379/0
      - BASE_URL=http://YOUR_EC2_PUBLIC_IP:8000
    depends_on:
      db:
        condition: service_healthy
      cache:
        condition: service_started
    restart: unless-stopped

  db:
    image: postgres:16-alpine
    environment:
      - POSTGRES_USER=shortener
      - POSTGRES_PASSWORD=CHANGE_THIS_PASSWORD
      - POSTGRES_DB=shortener
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U shortener"]
      interval: 5s
      timeout: 5s
      retries: 5

  cache:
    image: redis:7-alpine
    volumes:
      - redis_data:/var/lib/redis/data

volumes:
  postgres_data:
  redis_data:
EOF
```

**Change these values:**
- `123456789` → your AWS account ID
- `CHANGE_THIS_PASSWORD` → a real password (both places)
- `YOUR_EC2_PUBLIC_IP` → your instance's public IP

### 5.5 — Deploy

```bash
docker compose up -d
```

Test: `http://YOUR_EC2_PUBLIC_IP:8000/docs`

Your URL shortener is live on the internet.

### 5.6 — Deploy updates

After pushing to GitHub and the CI pipeline finishes:

```bash
# SSH into EC2
ssh -i your-key.pem ec2-user@<your-ec2-public-ip>
cd ~/url-shortener

# Re-authenticate with ECR (token expires every 12 hours)
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin \
  123456789.dkr.ecr.us-east-1.amazonaws.com

# Pull the latest image and restart
docker compose pull app
docker compose up -d
```

**Checkpoint:** Final commit.
```bash
git add .
git commit -m "docs: deployment instructions"
git push
```

---

## What You've Built

```
┌──────────────────────────────────────────────────────┐
│  GitHub                                              │
│  ┌─────────┐    ┌──────────────┐    ┌─────────────┐ │
│  │ git push │───▶│ GitHub       │───▶│ Push to ECR │ │
│  │ to main  │    │ Actions: test│    │             │ │
│  └─────────┘    └──────────────┘    └──────┬──────┘ │
└────────────────────────────────────────────┼────────┘
                                             │
┌────────────────────────────────────────────▼────────┐
│  AWS EC2 (t2.micro)                                 │
│  ┌──────────────────────────────────────────┐       │
│  │ docker-compose                           │       │
│  │  ┌─────────┐  ┌──────────┐  ┌─────────┐ │       │
│  │  │ FastAPI  │──│ Postgres │  │  Redis  │ │       │
│  │  │ :8000   │  │ :5432    │  │  :6379  │ │       │
│  │  └─────────┘  └──────────┘  └─────────┘ │       │
│  └──────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────┘
```

**Skills demonstrated on your CV:**
- Docker multi-stage builds
- Container orchestration with docker-compose
- CI/CD with GitHub Actions
- AWS ECR + EC2 deployment
- RESTful API design
- Database + caching layer (Postgres + Redis)
- Health checks and infrastructure best practices

---

## Bonus: Level-Up Ideas (if you have time)

1. **Add Nginx reverse proxy** — serve on port 80, add rate limiting. Add an `nginx` service to docker-compose.
2. **HTTPS with Let's Encrypt** — use `certbot` with Nginx for free SSL.
3. **Custom short codes** — let users pick `mysite.com/my-link` instead of random codes.
4. **Analytics dashboard** — track referrers, browser, country (via IP geolocation). Add a simple HTML frontend.
5. **Automated deploy** — extend the GitHub Actions workflow to SSH into EC2 and pull the new image automatically.
6. **Terraform** — define your EC2 + security group + ECR as infrastructure-as-code. Major CV bonus.

---

## Quick Reference

```bash
# Local development
docker compose up --build          # Start everything
docker compose down                # Stop everything
docker compose logs -f app         # Watch app logs

# Deploy to EC2
ssh -i key.pem ec2-user@IP
cd ~/url-shortener
docker compose pull app && docker compose up -d

# Debugging
docker compose exec app bash       # Shell into the app container
docker compose exec db psql -U shortener shortener  # SQL shell
docker compose exec cache redis-cli                  # Redis shell
```
