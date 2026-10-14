import logging
import time
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI, Request, Response

from . import metrics
from .config import get_settings
from .jobs import JobStore
from .routers import jobs, uploads
from .storage import make_s3_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    app.state.s3 = make_s3_client(s)
    redis_client = aioredis.from_url(s.redis_url, decode_responses=True)
    app.state.redis = redis_client
    app.state.jobs = JobStore(redis_client, s)
    yield
    await redis_client.aclose()


app = FastAPI(title="Media Processing Service", version="1.0.0", lifespan=lifespan)
app.include_router(uploads.router)
app.include_router(jobs.router)


@app.middleware("http")
async def timing(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    route = request.scope.get("route")  # use the route template to keep label cardinality low
    metrics.observe_request(request.method, route.path if route else "unmatched",
                            response.status_code, started)
    return response


@app.get("/health", tags=["meta"])
async def health():
    await app.state.redis.ping()
    return {"status": "ok"}


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics():  # sync on purpose: queue-depth lookup blocks, so FastAPI uses a thread
    body, content_type = metrics.render()
    return Response(body, media_type=content_type)
