import json
import logging
import os
import random
import tempfile
from functools import lru_cache
from pathlib import Path

import redis
from botocore.exceptions import BotoCoreError, ClientError
from celery.exceptions import SoftTimeLimitExceeded

from .celery_app import celery_app
from .config import get_settings
from .jobs import InvalidTransition, SyncJobStore
from .processing.errors import ProcessingError
from .schemas import JobStatus
from .storage import download, make_s3_client, result_url, upload

log = logging.getLogger(__name__)
s = get_settings()

MAX_RETRIES = 5
_THROTTLE_CODES = {"SlowDown", "RequestTimeout", "Throttling", "ThrottlingException", "RequestLimitExceeded"}


@lru_cache
def _s3():
    # Created lazily so each forked worker child builds its own client.
    return make_s3_client(s)


@lru_cache
def _store() -> SyncJobStore:
    return SyncJobStore(redis.Redis.from_url(s.redis_url, decode_responses=True), s)


def is_transient(exc: BaseException) -> bool:
    """Network-ish failures worth retrying. Bad input and auth errors are not."""
    if isinstance(exc, ClientError):
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
        code = exc.response.get("Error", {}).get("Code", "")
        return status >= 500 or code in _THROTTLE_CODES
    return isinstance(
        exc,
        (BotoCoreError, redis.exceptions.ConnectionError, redis.exceptions.TimeoutError,
         ConnectionError, TimeoutError),
    )


def _run_job(task, job_id: str, kind: str) -> None:
    store = _store()
    job = store.get(job_id)
    if job is None:
        log.warning("job %s not found (expired?); dropping", job_id)
        return
    if job["status"] == JobStatus.COMPLETED.value:
        return  # duplicate delivery

    attempt = task.request.retries + 1
    try:
        store.set_status(job_id, JobStatus.PROCESSING)
        urls = _process(job_id, job, kind)
        store.set_status(job_id, JobStatus.COMPLETED, result_urls=urls)
        log.info("job %s completed (attempt %d)", job_id, attempt)
    except InvalidTransition:
        log.warning("job %s: unexpected state, skipping", job_id)
    except ProcessingError as e:
        log.info("job %s rejected: %s", job_id, e)
        store.set_status(job_id, JobStatus.FAILED, error=str(e))
    except SoftTimeLimitExceeded:
        store.set_status(job_id, JobStatus.FAILED, error="Processing timed out")
    except Exception as e:  # noqa: BLE001
        if is_transient(e) and task.request.retries < MAX_RETRIES:
            delay = min(2 ** task.request.retries * 5, 300) + random.uniform(0, 5)
            log.warning("job %s transient error (%s); retry %d in %.0fs", job_id, e, attempt, delay)
            raise task.retry(exc=e, countdown=delay)
        log.exception("job %s failed", job_id)
        msg = "Temporary infrastructure error; retries exhausted" if is_transient(e) else "Internal processing error"
        store.set_status(job_id, JobStatus.FAILED, error=msg)


def _process(job_id: str, job: dict, kind: str) -> list[str]:
    from .processing import images, videos

    options = json.loads(job.get("options") or "{}")
    fn = images.process_image if kind == "image" else videos.process_video

    Path(s.work_dir).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=s.work_dir, prefix=f"{job_id}-") as tmp:
        tmp_dir = Path(tmp)
        src = tmp_dir / "source"
        out_dir = tmp_dir / "out"
        out_dir.mkdir()

        download(_s3(), s, job["source_key"], src)
        outputs = fn(src, out_dir, options, s)

        urls = []
        for path, content_type in outputs:
            # Deterministic keys: a retry overwrites instead of duplicating.
            key = f"{s.s3_output_prefix}{job_id}/{path.name}"
            upload(_s3(), s, key, path, content_type)
            urls.append(result_url(_s3(), s, key))
        return urls


@celery_app.task(bind=True, name="app.tasks.process_image", max_retries=MAX_RETRIES,
                 soft_time_limit=120, time_limit=150)
def process_image(self, job_id: str) -> None:
    _run_job(self, job_id, "image")


# Hard limit stays below RabbitMQ's default 30 min consumer_timeout (acks are late).
@celery_app.task(bind=True, name="app.tasks.process_video", max_retries=MAX_RETRIES,
                 soft_time_limit=1380, time_limit=1500)
def process_video(self, job_id: str) -> None:
    _run_job(self, job_id, "video")
