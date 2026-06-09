from collections.abc import Callable

from sqlalchemy.orm import Session

from app.core.clock import now as clock_now
from app.domain.enums import JobEventType, JobPriority, JobStatus
from app.queue.redis_queue import JobQueue
from app.repositories.job_event_repository import JobEventRepository
from app.repositories.job_repository import JobRepository
from app.repositories.notification_outbox_repository import NotificationOutboxRepository
from app.services.notification_service import enqueue_terminal_notification

_LEASE_EXPIRED_CODE = "LEASE_EXPIRED"
_LEASE_EXPIRED_MESSAGE = "worker lease expired and retries were exhausted"


class LeaseService:
    def __init__(self, session_factory: Callable[[], Session], queue: JobQueue) -> None:
        self._session_factory = session_factory
        self._queue = queue

    def reap_expired(self, batch_size: int) -> int:
        now = clock_now()
        requeued: list[tuple[str, JobPriority]] = []
        dead_lettered: list[str] = []
        with self._session_factory() as session, session.begin():
            jobs = JobRepository(session)
            events = JobEventRepository(session)
            notifications = NotificationOutboxRepository(session)
            for job in jobs.find_expired_leases(now, batch_size):
                if job.attempts >= job.max_attempts:
                    if jobs.fail_expired_lease(job.id, _LEASE_EXPIRED_CODE, _LEASE_EXPIRED_MESSAGE, now, True):
                        events.record(
                            job_id=job.id,
                            event_type=JobEventType.FAILED,
                            from_status=JobStatus.RUNNING,
                            to_status=JobStatus.FAILED,
                            detail={"reason": "lease_expired"},
                        )
                        enqueue_terminal_notification(
                            notifications,
                            job=job,
                            event_type=JobEventType.FAILED,
                            status=JobStatus.FAILED,
                            result=None,
                            error_code=_LEASE_EXPIRED_CODE,
                            error_message=_LEASE_EXPIRED_MESSAGE,
                            now=now,
                        )
                        dead_lettered.append(str(job.id))
                elif jobs.requeue_expired_lease(job.id, now):
                    events.record(
                        job_id=job.id,
                        event_type=JobEventType.REQUEUED,
                        from_status=JobStatus.RUNNING,
                        to_status=JobStatus.QUEUED,
                        detail={"reason": "lease_expired"},
                    )
                    requeued.append((str(job.id), JobPriority(job.priority)))
        for job_id in dead_lettered:
            self._queue.dead_letter(job_id)
        for job_id, priority in requeued:
            self._queue.publish(job_id, priority)
        return len(requeued) + len(dead_lettered)
