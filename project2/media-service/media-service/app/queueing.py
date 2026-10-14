from .celery_app import IMAGE_QUEUE, VIDEO_QUEUE, celery_app

_TASKS = {
    "image": ("app.tasks.process_image", IMAGE_QUEUE),
    "video": ("app.tasks.process_video", VIDEO_QUEUE),
}


def enqueue(job_id: str, media_type: str) -> None:
    """Blocking publish (with broker confirm). Call via asyncio.to_thread from async code."""
    task, queue = _TASKS[media_type]
    celery_app.send_task(task, args=[job_id], queue=queue)
