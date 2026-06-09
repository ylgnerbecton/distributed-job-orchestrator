import uuid
from datetime import timedelta

from helpers import get_job, make_job
from sqlalchemy import func, select

from app.core.clock import now as clock_now
from app.db.models import DispatchOutbox
from app.domain.enums import JobStatus


def test_dispatch_pending_queues_and_publishes(client, session_factory, dispatch_service, queue) -> None:
    job_id = uuid.UUID(client.post("/jobs", json={"type": "report"}).get_json()["job_id"])
    assert dispatch_service.dispatch_pending(10) == 1
    job = get_job(session_factory, job_id)
    assert job.status == JobStatus.QUEUED.value
    assert job.queued_at is not None
    assert queue.depth() == 1


def test_dispatch_marks_outbox_published(client, dispatch_service, session) -> None:
    client.post("/jobs", json={"type": "report"})
    dispatch_service.dispatch_pending(10)
    pending = session.execute(
        select(func.count()).select_from(DispatchOutbox).where(DispatchOutbox.status == "pending")
    ).scalar_one()
    assert pending == 0


def test_redeliver_stuck_republishes_queued_jobs(session_factory, dispatch_service, queue) -> None:
    make_job(session_factory, status=JobStatus.QUEUED.value, queued_at=clock_now() - timedelta(seconds=120))
    assert dispatch_service.redeliver_stuck(10) == 1
    assert queue.depth() == 1


def test_expiry_marks_old_queued_job_expired(session_factory, expiry_service) -> None:
    old = clock_now() - timedelta(seconds=100000)
    job_id = make_job(session_factory, status=JobStatus.QUEUED.value, created_at=old, queued_at=old)
    assert expiry_service.expire_stale(10) == 1
    assert get_job(session_factory, job_id).status == JobStatus.EXPIRED.value
