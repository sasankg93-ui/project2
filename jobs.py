import json

from fastapi import APIRouter, Depends, HTTPException, status

from ..config import Settings, get_settings
from ..deps import get_job_store, get_s3, require_api_key
from ..jobs import JobStore
from ..schemas import ALLOWED_CONTENT_TYPES, JobCreate, JobOut, MediaType
from ..storage import head_object

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


@router.post("", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
async def create_job(
    body: JobCreate,
    s: Settings = Depends(get_settings),
    s3=Depends(get_s3),
    store: JobStore = Depends(get_job_store),
):
    # Only accept keys we issued, so callers can't point the worker at arbitrary objects.
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
    options = opts.model_dump() if opts else {}
    job = await store.create(body.source_key, body.media_type.value, options)
    # Week 2: enqueue the Celery task here with job["job_id"].
    return _to_out(job)


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: str, store: JobStore = Depends(get_job_store)):
    job = await store.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return _to_out(job)
