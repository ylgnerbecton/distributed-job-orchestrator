from helpers import make_job
from sqlalchemy import func, select

from app.core.clock import now as clock_now
from app.db.models import NotificationOutbox
from app.domain.enums import JobType, NotificationChannel, NotificationStatus
from app.repositories.notification_outbox_repository import NotificationOutboxRepository


async def test_log_notification_is_delivered_and_marked_sent(
    session_factory, execution_service, notification_service, session
) -> None:
    job_id = await make_job(session_factory, type=JobType.FLAKY.value, payload={"fail_times": 0})
    await execution_service.execute(job_id)
    assert await notification_service.dispatch_due(10) == 1
    status = (
        await session.execute(select(NotificationOutbox.status).where(NotificationOutbox.job_id == job_id))
    ).scalar_one()
    assert status == NotificationStatus.SENT.value


async def test_notification_dedupe_prevents_duplicates(session_factory, session) -> None:
    job_id = await make_job(session_factory)
    now = clock_now()
    async with session_factory() as work_session, work_session.begin():
        repository = NotificationOutboxRepository(work_session)
        first = await repository.enqueue(
            job_id=job_id,
            user_id="demo-user",
            channel=NotificationChannel.LOG,
            destination="demo-user",
            event_type="succeeded",
            payload={},
            dedupe_key=f"{job_id}:succeeded",
            now=now,
        )
        second = await repository.enqueue(
            job_id=job_id,
            user_id="demo-user",
            channel=NotificationChannel.LOG,
            destination="demo-user",
            event_type="succeeded",
            payload={},
            dedupe_key=f"{job_id}:succeeded",
            now=now,
        )
    assert first is True
    assert second is False
    count = (
        await session.execute(
            select(func.count()).select_from(NotificationOutbox).where(NotificationOutbox.job_id == job_id)
        )
    ).scalar_one()
    assert count == 1
