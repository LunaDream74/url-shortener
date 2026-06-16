import os
os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


def test_shorten_and_stats():
    with TestClient(app) as c:
        r = c.post("/shorten", json={"url": "https://example.com"})
        assert r.status_code == 201
        data = r.json()
        assert "short_code" in data

        r = c.get(f"/{data['short_code']}/stats")
        assert r.status_code == 200
        assert r.json()["clicks"] == 0


def test_redirect():
    with TestClient(app) as c:
        r = c.post("/shorten", json={"url": "https://example.com"})
        short_code = r.json()["short_code"]

        r = c.get(f"/{short_code}", follow_redirects=False)
        assert r.status_code == 307
        assert r.headers["location"] == "https://example.com/"


def test_not_found():
    r = client.get("/nonexistent")
    assert r.status_code == 404
