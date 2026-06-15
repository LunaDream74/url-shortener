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
    cached_url = cache.get(f"url:{short_code}")

    if cached_url:
        db_url = db.query(URL).filter(URL.short_code == short_code).first()
        if db_url:
            db_url.clicks += 1
            db.commit()
        return RedirectResponse(url=cached_url, status_code=307)

    db_url = db.query(URL).filter(URL.short_code == short_code).first()
    if not db_url:
        raise HTTPException(status_code=404, detail="Short URL not found")

    db_url.clicks += 1
    db.commit()

    cache.set(f"url:{short_code}", db_url.original_url, ex=3600)

    return RedirectResponse(url=db_url.original_url, status_code=307)


@router.get("/{short_code}/stats", response_model=URLStats)
def get_url_stats(short_code: str, db: Session = Depends(get_db)):
    db_url = db.query(URL).filter(URL.short_code == short_code).first()
    if not db_url:
        raise HTTPException(status_code=404, detail="Short URL not found")

    return db_url
