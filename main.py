from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI

from .config import get_settings
from .jobs import JobStore
from .routers import jobs, uploads
from .storage import make_s3_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    app.state.s3 = make_s3_client(s)
    redis_client = aioredis.from_url(s.redis_url, decode_responses=True)
    app.state.redis = redis_client
    app.state.jobs = JobStore(redis_client, s)
    yield
    await redis_client.aclose()


app = FastAPI(title="Media Processing Service", version="0.1.0", lifespan=lifespan)
app.include_router(uploads.router)
app.include_router(jobs.router)


@app.get("/health", tags=["meta"])
async def health():
    await app.state.redis.ping()
    return {"status": "ok"}
