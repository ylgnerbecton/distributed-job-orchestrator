from collections.abc import Callable
from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.clock import now as clock_now
from app.core.config import Settings
from app.domain.enums import JobEventType, JobStatus
from app.repositories.job_event_repository import JobEventRepository
from app.repositories.job_repository import JobRepository
from app.repositories.notification_outbox_repository import NotificationOutboxRepository
from app.services.notification_service import enqueue_terminal_notification

_EXPIRED_CODE = "EXPIRED"
_EXPIRED_MESSAGE = "job expired before it started running"


class ExpiryService:
    def __init__(self, session_factory: Callable[[], Session], settings: Settings) -> None:
        self._session_factory = session_factory
        self._settings = settings

    def expire_stale(self, batch_size: int) -> int:
        now = clock_now()
        cutoff = now - timedelta(seconds=self._settings.job_queue_max_age_seconds)
        expired = 0
        with self._session_factory() as session, session.begin():
            jobs = JobRepository(session)
            events = JobEventRepository(session)
            notifications = NotificationOutboxRepository(session)
            for job in jobs.find_expirable(cutoff, batch_size):
                if jobs.expire(job.id, now):
                    events.record(
                        job_id=job.id,
                        event_type=JobEventType.EXPIRED,
                        from_status=JobStatus(job.status),
                        to_status=JobStatus.EXPIRED,
                    )
                    enqueue_terminal_notification(
                        notifications,
                        job=job,
                        event_type=JobEventType.EXPIRED,
                        status=JobStatus.EXPIRED,
                        result=None,
                        error_code=_EXPIRED_CODE,
                        error_message=_EXPIRED_MESSAGE,
                        now=now,
                    )
                    expired += 1
        return expired
