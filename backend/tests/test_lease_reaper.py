from datetime import timedelta

from helpers import get_job, make_job
from sqlalchemy import func, select

from app.core.clock import now as clock_now
from app.db.models import NotificationOutbox
from app.domain.enums import JobStatus


async def test_expired_lease_with_attempts_remaining_is_requeued(session_factory, lease_service, queue) -> None:
    job_id = await make_job(
        session_factory,
        status=JobStatus.RUNNING.value,
        attempts=1,
        max_attempts=5,
        locked_by="dead-worker",
        lock_expires_at=clock_now() - timedelta(seconds=30),
    )
    assert await lease_service.reap_expired(10) == 1
    job = await get_job(session_factory, job_id)
    assert job.status == JobStatus.QUEUED.value
    assert job.locked_by is None
    assert await queue.depth() == 1


async def test_expired_lease_exhausted_is_failed_and_dead_lettered(
    session_factory, lease_service, queue, session
) -> None:
    job_id = await make_job(
        session_factory,
        status=JobStatus.RUNNING.value,
        attempts=3,
        max_attempts=3,
        locked_by="dead-worker",
        lock_expires_at=clock_now() - timedelta(seconds=30),
    )
    await lease_service.reap_expired(10)
    job = await get_job(session_factory, job_id)
    assert job.status == JobStatus.FAILED.value
    assert job.dead_lettered_at is not None
    assert await queue.dead_letter_depth() == 1
    notifications = (
        await session.execute(
            select(func.count()).select_from(NotificationOutbox).where(NotificationOutbox.job_id == job_id)
        )
    ).scalar_one()
    assert notifications == 1


async def test_healthy_lease_is_not_reaped(session_factory, lease_service) -> None:
    job_id = await make_job(
        session_factory,
        status=JobStatus.RUNNING.value,
        attempts=1,
        max_attempts=5,
        locked_by="alive-worker",
        lock_expires_at=clock_now() + timedelta(seconds=60),
    )
    assert await lease_service.reap_expired(10) == 0
    assert (await get_job(session_factory, job_id)).status == JobStatus.RUNNING.value
