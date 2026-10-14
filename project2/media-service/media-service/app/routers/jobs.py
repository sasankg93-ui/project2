import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status

from ..config import Settings, get_settings
from ..deps import get_job_store, get_s3, require_api_key
from ..jobs import InvalidTransition, JobStore
from ..queueing import enqueue
from ..schemas import ALLOWED_CONTENT_TYPES, JobCreate, JobOut, JobStatus, MediaType
from ..storage import head_object

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/jobs", tags=["jobs"], dependencies=[Depends(require_api_key)])


def _to_out(job: dict) -> JobOut:
    return JobOut(
        job_id=job["job_id"],
        status=job["status"],
        media_type=job["media_type"],
        source_key=job["source_key"],
        created_at=job["created_at"],
        updated_at=job["updated_at"],
        result_urls=json.loads(job.get("result_urls") or "[]"),
        error=job.get("error") or None,
    )


async def _enqueue_or_fail(store: JobStore, job_id: str, media_type: str) -> None:
    try:
        await asyncio.to_thread(enqueue, job_id, media_type)
    except Exception:  # broker down, etc.
        log.exception("enqueue failed for %s", job_id)
        await store.set_status(job_id, JobStatus.FAILED, error="Queue unavailable")
        raise HTTPException(503, "Queue unavailable, please retry")


@router.post("", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
async def create_job(
    body: JobCreate,
    s: Settings = Depends(get_settings),
    s3=Depends(get_s3),
    store: JobStore = Depends(get_job_store),
):
    # Only accept keys we issued, so callers can't point a worker at arbitrary objects.
    if not body.source_key.startswith(s.s3_upload_prefix) or ".." in body.source_key:
        raise HTTPException(400, "Invalid source_key")

    head = await head_object(s3, s, body.source_key)
    if head is None:
        raise HTTPException(409, "Source object not uploaded yet")
    if head["ContentLength"] > s.max_upload_bytes:
        raise HTTPException(413, "File too large")
    detected = ALLOWED_CONTENT_TYPES.get(head.get("ContentType", ""))
    if detected is None or detected != body.media_type:
        raise HTTPException(422, "Uploaded object type does not match media_type")

    opts = body.image if body.media_type == MediaType.IMAGE else body.video
    job = await store.create(body.source_key, body.media_type.value, opts.model_dump() if opts else {})
    await _enqueue_or_fail(store, job["job_id"], body.media_type.value)
    return _to_out(job)


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: str, store: JobStore = Depends(get_job_store)):
    job = await store.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return _to_out(job)


@router.post("/{job_id}/retry", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
async def retry_job(job_id: str, store: JobStore = Depends(get_job_store)):
    """Re-queue a failed job (replaces a dead-letter queue: failures stay inspectable in Redis)."""
    if await store.get(job_id) is None:
        raise HTTPException(404, "Job not found")
    try:
        job = await store.set_status(job_id, JobStatus.PENDING)
    except InvalidTransition:
        raise HTTPException(409, "Only failed jobs can be retried")
    await _enqueue_or_fail(store, job_id, job["media_type"])
    return _to_out(job)
