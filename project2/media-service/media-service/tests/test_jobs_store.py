import fakeredis
import pytest

from app.jobs import InvalidTransition, SyncJobStore
from app.schemas import JobStatus


@pytest.fixture
def store(settings):
    return SyncJobStore(fakeredis.FakeRedis(decode_responses=True), settings)


def _make(store):
    from app.jobs import KEY, _new_job

    j = _new_job("uploads/a/b.jpg", "image", {})
    store.r.hset(KEY.format(j["job_id"]), mapping=j)
    return j["job_id"]


def test_happy_path(store):
    jid = _make(store)
    store.set_status(jid, JobStatus.PROCESSING)
    done = store.set_status(jid, JobStatus.COMPLETED, result_urls=["https://x/y"])
    assert done["status"] == "completed" and '"https://x/y"' in done["result_urls"]


def test_completed_is_terminal(store):
    jid = _make(store)
    store.set_status(jid, JobStatus.PROCESSING)
    store.set_status(jid, JobStatus.COMPLETED)
    with pytest.raises(InvalidTransition):
        store.set_status(jid, JobStatus.PROCESSING)


def test_failed_can_be_retried_and_error_cleared(store):
    jid = _make(store)
    store.set_status(jid, JobStatus.FAILED, error="boom")
    assert store.get(jid)["error"] == "boom"
    assert store.set_status(jid, JobStatus.PENDING)["error"] == ""


def test_redelivery_allows_processing_twice(store):
    jid = _make(store)
    store.set_status(jid, JobStatus.PROCESSING)
    store.set_status(jid, JobStatus.PROCESSING)
