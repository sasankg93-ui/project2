import json
import uuid
from datetime import datetime, timezone

import redis.asyncio as aioredis

from .config import Settings
from .schemas import JobStatus

KEY = "job:{}"

# Allowed transitions; workers (Week 2+) must go through set_status.
TRANSITIONS = {
    JobStatus.PENDING: {JobStatus.PROCESSING, JobStatus.FAILED},
    # PROCESSING -> PENDING allows a retry to be re-queued
    JobStatus.PROCESSING: {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.PENDING},
    JobStatus.COMPLETED: set(),
    JobStatus.FAILED: {JobStatus.PENDING},
}


class InvalidTransition(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    def __init__(self, r: aioredis.Redis, s: Settings):
        self.r = r
        self.ttl = s.job_ttl_seconds

    async def create(self, source_key: str, media_type: str, options: dict) -> dict:
        job_id = uuid.uuid4().hex
        now = _now()
        job = {
            "job_id": job_id,
            "status": JobStatus.PENDING.value,
            "media_type": media_type,
            "source_key": source_key,
            "options": json.dumps(options),
            "created_at": now,
            "updated_at": now,
            "result_urls": "[]",
            "error": "",
        }
        pipe = self.r.pipeline()
        pipe.hset(KEY.format(job_id), mapping=job)
        pipe.expire(KEY.format(job_id), self.ttl)
        await pipe.execute()
        return job

    async def get(self, job_id: str) -> dict | None:
        data = await self.r.hgetall(KEY.format(job_id))
        return data or None

    async def set_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        result_urls: list[str] | None = None,
        error: str | None = None,
    ) -> dict:
        key = KEY.format(job_id)
        # WATCH guards against two workers racing on the same job.
        async with self.r.pipeline() as pipe:
            await pipe.watch(key)
            current = await pipe.hget(key, "status")
            if current is None:
                raise KeyError(job_id)
            if JobStatus(status) not in TRANSITIONS[JobStatus(current)]:
                raise InvalidTransition(f"{current} -> {status.value}")
            updates = {"status": status.value, "updated_at": _now()}
            if result_urls is not None:
                updates["result_urls"] = json.dumps(result_urls)
            if error is not None:
                updates["error"] = error
            pipe.multi()
            pipe.hset(key, mapping=updates)
            await pipe.execute()
        return await self.get(job_id)
