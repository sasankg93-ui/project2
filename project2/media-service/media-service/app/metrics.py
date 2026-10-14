import logging
import time

import redis
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Histogram, generate_latest
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily

from .celery_app import QUEUES, celery_app
from .config import get_settings
from .jobs import STATS_KEY

log = logging.getLogger(__name__)

registry = CollectorRegistry()
HTTP_LATENCY = Histogram(
    "media_http_request_seconds", "API request latency",
    ["method", "path", "status"], registry=registry,
)


class PipelineCollector:
    """Computed at scrape time: ready messages per RabbitMQ queue + cumulative job transitions."""

    def __init__(self):
        self._redis = None

    def _r(self):
        if self._redis is None:
            self._redis = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
        return self._redis

    def collect(self):
        depth = GaugeMetricFamily("media_queue_messages", "Messages waiting in queue", labels=["queue"])
        try:
            with celery_app.connection_for_read() as conn:
                for q in QUEUES:
                    try:
                        ch = conn.channel()
                        depth.add_metric([q], ch.queue_declare(queue=q, passive=True).message_count)
                    except Exception:  # queue not declared yet / broker hiccup
                        log.debug("queue depth unavailable for %s", q)
        except Exception:
            log.warning("could not reach broker for queue depth")
        yield depth

        jobs = CounterMetricFamily("media_job_transitions", "Job status transitions", labels=["status"])
        try:
            for status, n in self._r().hgetall(STATS_KEY).items():
                jobs.add_metric([status], float(n))
        except Exception:
            log.warning("could not read job stats from redis")
        yield jobs


registry.register(PipelineCollector())


def render() -> tuple[bytes, str]:
    return generate_latest(registry), CONTENT_TYPE_LATEST


def observe_request(method: str, path: str, status: int, started: float) -> None:
    HTTP_LATENCY.labels(method, path, str(status)).observe(time.perf_counter() - started)
