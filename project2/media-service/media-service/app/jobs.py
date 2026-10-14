import json
import uuid
from datetime import datetime, timezone

import redis
import redis.asyncio as aioredis
from redis.exceptions import WatchError

from .config import Settings
from .schemas import JobStatus

KEY = "job:{}"
STATS_KEY = "stats:job_status"  # cumulative transition counters, exported to Prometheus

# PROCESSING -> PROCESSING covers redelivery after a worker crash or a Celery retry.
TRANSITIONS = {
    JobStatus.PENDING: {JobStatus.PROCESSING, JobStatus.FAILED},
    JobStatus.PROCESSING: {
        JobStatus.PROCESSING,
        JobStatus.COMPLETED,
        JobStatus.FAILED,
        JobStatus.PENDING,
    },
    JobStatus.COMPLETED: set(),
    JobStatus.FAILED: {JobStatus.PENDING},  # manual retry
}


class InvalidTransition(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_job(source_key: str, media_type: str, options: dict) -> dict:
    now = _now()
    return {
        "job_id": uuid.uuid4().hex,
        "status": JobStatus.PENDING.value,
        "media_type": media_type,
        "source_key": source_key,
        "options": json.dumps(options),
        "created_at": now,
        "updated_at": now,
        "result_urls": "[]",
        "error": "",
    }


def _updates(current: str, status: JobStatus, result_urls, error) -> dict:
    if status not in TRANSITIONS[JobStatus(current)]:
        raise InvalidTransition(f"{current} -> {status.value}")
    u = {"status": status.value, "updated_at": _now()}
    if result_urls is not None:
        u["result_urls"] = json.dumps(result_urls)
    if error is not None:
        u["error"] = error
    elif status != JobStatus.FAILED:
        u["error"] = ""
    return u


class JobStore:
    """Async store used by the FastAPI process."""

    def __init__(self, r: aioredis.Redis, s: Settings):
        self.r = r
        self.ttl = s.job_ttl_seconds

    async def create(self, source_key: str, media_type: str, options: dict) -> dict:
        job = _new_job(source_key, media_type, options)
        key = KEY.format(job["job_id"])
        pipe = self.r.pipeline()
        pipe.hset(key, mapping=job)
        pipe.expire(key, self.ttl)
        pipe.hincrby(STATS_KEY, JobStatus.PENDING.value, 1)
        await pipe.execute()
        return job

    async def get(self, job_id: str) -> dict | None:
        return (await self.r.hgetall(KEY.format(job_id))) or None

    async def set_status(self, job_id, status: JobStatus, *, result_urls=None, error=None) -> dict:
        key = KEY.format(job_id)
        for _ in range(5):
            async with self.r.pipeline() as pipe:
                try:
                    await pipe.watch(key)
                    current = await pipe.hget(key, "status")
                    if current is None:
                        raise KeyError(job_id)
                    updates = _updates(current, status, result_urls, error)
                    pipe.multi()
                    pipe.hset(key, mapping=updates)
                    pipe.hincrby(STATS_KEY, status.value, 1)
                    await pipe.execute()
                    return await self.get(job_id)
                except WatchError:
                    continue
        raise RuntimeError("Could not update job (contention)")


class SyncJobStore:
    """Sync twin of JobStore for Celery workers. Same schema and transition rules."""

    def __init__(self, r: redis.Redis, s: Settings):
        self.r = r
        self.ttl = s.job_ttl_seconds

    def get(self, job_id: str) -> dict | None:
        return self.r.hgetall(KEY.format(job_id)) or None

    def set_status(self, job_id, status: JobStatus, *, result_urls=None, error=None) -> dict:
        key = KEY.format(job_id)
        for _ in range(5):
            with self.r.pipeline() as pipe:
                try:
                    pipe.watch(key)
                    current = pipe.hget(key, "status")
                    if current is None:
                        raise KeyError(job_id)
                    updates = _updates(current, status, result_urls, error)
                    pipe.multi()
                    pipe.hset(key, mapping=updates)
                    pipe.hincrby(STATS_KEY, status.value, 1)
                    pipe.execute()
                    return self.get(job_id)
                except WatchError:
                    continue
        raise RuntimeError("Could not update job (contention)")
