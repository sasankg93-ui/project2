# Distributed Media Processing Service

FastAPI intake API + Celery workers (RabbitMQ broker, Redis job state) that download uploads from S3,
process images (Pillow) and video (FFmpeg), and publish optimized assets for CloudFront.

## Architecture
    client ──presign──> API ──PUT──> S3 (uploads/)
    client ──POST /v1/jobs──> API ──> Redis (job hash: pending)
                                 └──> RabbitMQ  (queue: images | video)
    Celery worker: download -> validate -> process -> upload processed/<job_id>/* -> Redis (completed)
    client <──GET /v1/jobs/{id}── API (status + result URLs)

## Layout
    app/main.py            FastAPI app, /health, /metrics
    app/routers/           uploads.py (presign), jobs.py (create / get / retry)
    app/jobs.py            Redis job store (async for API, sync for workers) + state machine
    app/celery_app.py      Celery config (queues, acks_late, limits, publisher confirms)
    app/tasks.py           process_image / process_video, retry policy
    app/processing/        images.py (Pillow), videos.py (FFmpeg), errors.py
    app/metrics.py         API metrics: queue depth, job transitions, HTTP latency
    app/worker_metrics.py  Worker CPU/memory exporter
    deploy/                prometheus.yml, alerts.yml
    loadtest/locustfile.py Locust end-to-end load test
    tests/                 pytest suite

## Quick start (Docker)
    cp .env.example .env     # set S3_BUCKET, APP_API_KEY, AWS creds
    docker compose up --build
    # scale out:  docker compose up -d --scale worker-images=3 --scale worker-video=2
Docs: http://localhost:8000/docs · RabbitMQ UI: http://localhost:15672 · Prometheus: http://localhost:9090

Compose does not publish Redis or RabbitMQ AMQP ports. Put `/metrics` behind your network boundary
(it is unauthenticated, like most Prometheus targets).

## API (all `/v1` routes need `X-API-Key`)
| Method | Path | Purpose |
|---|---|---|
| POST | /v1/uploads/presign | `{filename, content_type, size_bytes}` -> `source_key`, presigned PUT URL |
| POST | /v1/jobs | `{source_key, media_type, image?{width,height,quality,watermark}, video?{max_height,thumbnail,watermark}}` -> 202 |
| GET | /v1/jobs/{id} | status, `result_urls`, `error` |
| POST | /v1/jobs/{id}/retry | re-queue a failed job |

Client flow: presign -> `PUT` file with the returned `Content-Type` header -> create job -> poll.

Outputs: images -> `image.webp` + `thumb.webp`; video -> `video.mp4` (H.264/AAC, faststart) + `thumb.jpg`.

## Job states
`pending -> processing -> completed | failed`; `failed -> pending` via retry. Transitions are enforced
atomically in Redis (WATCH/MULTI), so duplicate deliveries and racing workers are safe.

## Failure handling
- Transient (S3 5xx/throttling, connection/timeouts, Redis connection): retried up to 5 times with
  exponential backoff + jitter (5s, 10s, 20s, ... capped at 300s).
- Permanent (corrupt/unsupported media, too long, decompression bomb): fail immediately, no retry.
- Worker crash/OOM: `acks_late` + `reject_on_worker_lost` redeliver the message; completed jobs are skipped.
- Output keys are deterministic (`processed/<job_id>/...`), so retries overwrite rather than duplicate.
- Failed jobs stay inspectable in Redis (7-day TTL) and can be replayed with `/retry`.

## Tests
    pip install -r requirements-dev.txt
    pytest
Video tests need `ffmpeg` on PATH.

## Load test
    API_KEY=... locust -f loadtest/locustfile.py --host http://localhost:8000
It reports an "E2E" row (upload-to-completed latency) alongside request latencies.
