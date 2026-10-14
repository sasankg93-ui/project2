# Deployment Guide

## 1. AWS setup
**Bucket** (block public access ON). Browser uploads need CORS:

    [{"AllowedOrigins":["https://your-app.com"],"AllowedMethods":["PUT"],
      "AllowedHeaders":["Content-Type"],"MaxAgeSeconds":3000}]

**Lifecycle rule:** expire `uploads/` after 1-7 days (sources are no longer needed once processed).

**IAM policy** for the API and workers (use an instance/task role, not static keys, in production):

    s3:PutObject, s3:GetObject on arn:aws:s3:::BUCKET/uploads/*
    s3:PutObject, s3:GetObject on arn:aws:s3:::BUCKET/processed/*
    s3:ListBucket on arn:aws:s3:::BUCKET   (so a missing key returns 404 rather than 403)

**CloudFront:** origin = the bucket via Origin Access Control, path pattern `processed/*` only
(never expose `uploads/`). Set `CDN_DOMAIN` to the distribution domain. Objects are uploaded with
`Cache-Control: immutable`; keys contain the job id, so no invalidations are ever needed.

## 2. Configuration
Copy `.env.example` to `.env`. Required: `S3_BUCKET`, `APP_API_KEY` (long random string),
`RABBITMQ_USER/PASSWORD`. Change the default RabbitMQ credentials before any shared deployment.

## 3. Run
    docker compose up -d --build
    curl localhost:8000/health

## 4. Scaling
- API is stateless: add replicas behind a load balancer.
- Workers are separate pools per queue. Image workers are cheap and parallel (`-c 4`); video workers
  are CPU/RAM heavy (`-c 1` with `FFMPEG_THREADS=4`). Size each so `concurrency x ffmpeg threads`
  does not exceed the node's cores.
- **Autoscaling on traffic spikes:** scale worker replicas on `media_queue_messages{queue=...}`
  (queue depth) or messages-per-worker. Options: KEDA's RabbitMQ scaler on Kubernetes, or an ECS
  service auto-scaling policy fed by a CloudWatch metric. Compose only scales manually
  (`--scale`); the metrics and alerts here are what the autoscaler consumes.
- Do not set Celery `--autoscale` as a substitute: it only adjusts processes inside one node.

## 5. Monitoring
Prometheus scrapes three targets (`deploy/prometheus.yml`):

| Metric | Source | Use |
|---|---|---|
| `media_queue_messages{queue}` | API /metrics (RabbitMQ passive declare) | backlog, autoscaling signal |
| `media_job_transitions_total{status}` | API /metrics (Redis counters) | throughput, failure rate |
| `media_http_request_seconds` | API | API latency |
| `media_worker_cpu_percent`, `media_worker_memory_bytes`, `media_worker_processes` | each worker | CPU/RAM of Celery + FFmpeg tree (100 = one core) |
| `rabbitmq_*` | RabbitMQ prometheus plugin (port 15692) | broker health |

Alerts in `deploy/alerts.yml`: queue backlog, saturated workers, failure spikes.
`media_job_transitions_total` counts transitions, so a retried or redelivered job is counted again.

## 6. Memory and performance tuning
- `worker_max_tasks_per_child=50` and `worker_max_memory_per_child` (~1 GB) recycle leaky children.
- Pillow: JPEG `draft()` decodes at reduced size; the `max_image_pixels` setting rejects decompression bombs; only one decoded image is held at a time.
- FFmpeg streams from disk (never loaded into Python memory); `-threads` is capped by `FFMPEG_THREADS`;
  preset `veryfast` trades ~10% size for much lower CPU. Use `medium` if CDN egress matters more.
- Containers have `mem_limit`s so an OOM kills one worker, not the host; the message is redelivered.
- `worker_prefetch_multiplier=1` keeps long jobs from hoarding messages.
- Temp files live in `WORK_DIR` per job and are deleted on completion; mount it on fast local disk.

## 7. Operational notes
- RabbitMQ's default `consumer_timeout` is 30 minutes and tasks ack late. The video hard limit is
  1500s to stay below it; if you raise it, raise `consumer_timeout` in `rabbitmq.conf` too.
- Redis holds job state with a 7-day TTL and AOF enabled; losing Redis loses job status, not media.
- Watermark text comes from config only; never pass user input into FFmpeg `drawtext`.
- Webhook callbacks were left out on purpose (they need SSRF protection); clients poll.
- Load test before launch (`loadtest/locustfile.py`), then tune worker counts from the E2E latency
  and the CPU gauge. Watch for `media_queue_messages` growing without bound at your target rate.
