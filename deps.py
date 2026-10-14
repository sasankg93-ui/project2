import hmac

import redis.asyncio as aioredis
from fastapi import Depends, Header, HTTPException, Request, status

from .config import Settings, get_settings
from .jobs import JobStore


def require_api_key(
    x_api_key: str = Header(default=""), s: Settings = Depends(get_settings)
) -> None:
    if not hmac.compare_digest(x_api_key, s.app_api_key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")


def get_s3(request: Request):
    return request.app.state.s3


def get_job_store(request: Request) -> JobStore:
    return request.app.state.jobs
