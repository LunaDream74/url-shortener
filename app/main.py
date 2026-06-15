from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.database import engine, Base
from app.routes.urls import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="URL Shortener",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
def health_check():
    return {"status": "healthy"}


app.include_router(router)
