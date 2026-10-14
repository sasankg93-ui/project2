import os

from celery import Celery
from celery.signals import worker_ready
from kombu import Queue

from .config import get_settings

s = get_settings()

celery_app = Celery("media", broker=s.rabbitmq_url, include=["app.tasks"])

IMAGE_QUEUE = "images"
VIDEO_QUEUE = "video"
QUEUES = (IMAGE_QUEUE, VIDEO_QUEUE)

celery_app.conf.update(
    # Separate queues so slow video transcodes never block quick image jobs,
    # and each pool can be scaled and sized independently.
    task_queues=(Queue(IMAGE_QUEUE, durable=True), Queue(VIDEO_QUEUE, durable=True)),
    task_default_queue=IMAGE_QUEUE,
    task_routes={
        "app.tasks.process_image": {"queue": IMAGE_QUEUE},
        "app.tasks.process_video": {"queue": VIDEO_QUEUE},
    },
    # Reliability: ack only after the task finishes; redeliver if the worker dies.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # fair dispatch for long tasks
    broker_connection_retry_on_startup=True,
    broker_transport_options={"confirm_publish": True},  # publisher confirms
    # State lives in Redis (our own job hash), so we don't need Celery results.
    task_ignore_result=True,
    task_serializer="json",
    accept_content=["json"],
    # Memory hygiene for Pillow/FFmpeg: recycle children regularly.
    worker_max_tasks_per_child=50,
    worker_max_memory_per_child=1_000_000,  # KiB (~1 GB)
    timezone="UTC",
)


@worker_ready.connect
def _start_metrics(**_):
    port = int(os.getenv("WORKER_METRICS_PORT", s.worker_metrics_port))
    if port:
        from .worker_metrics import start_exporter

        start_exporter(port)
