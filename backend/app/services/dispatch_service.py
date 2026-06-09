from collections.abc import Callable
from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.clock import now as clock_now
from app.core.config import Settings
from app.domain.enums import JobEventType, JobPriority, JobStatus
from app.queue.redis_queue import JobQueue
from app.repositories.dispatch_outbox_repository import DispatchOutboxRepository
from app.repositories.job_event_repository import JobEventRepository
from app.repositories.job_repository import JobRepository


class DispatchService:
    def __init__(self, session_factory: Callable[[], Session], queue: JobQueue, settings: Settings) -> None:
        self._session_factory = session_factory
        self._queue = queue
        self._settings = settings

    def dispatch_pending(self, batch_size: int) -> int:
        now = clock_now()
        published: list[tuple[str, JobPriority]] = []
        with self._session_factory() as session, session.begin():
            outbox = DispatchOutboxRepository(session)
            jobs = JobRepository(session)
            events = JobEventRepository(session)
            for row in outbox.claim_pending(batch_size):
                job = jobs.get(row.job_id)
                outbox.mark_published(row.id, now)
                if job is None:
                    continue
                jobs.mark_queued(row.job_id, now)
                events.record(
                    job_id=row.job_id,
                    event_type=JobEventType.QUEUED,
                    from_status=JobStatus.PENDING,
                    to_status=JobStatus.QUEUED,
                )
                published.append((str(row.job_id), JobPriority(job.priority)))
        for job_id, priority in published:
            self._queue.publish(job_id, priority)
        return len(published)

    def redeliver_stuck(self, batch_size: int) -> int:
        cutoff = clock_now() - timedelta(seconds=self._settings.queue_stuck_seconds)
        republished: list[tuple[str, JobPriority]] = []
        with self._session_factory() as session, session.begin():
            jobs = JobRepository(session)
            for job in jobs.find_stuck_queued(cutoff, batch_size):
                jobs.mark_redispatched(job.id, clock_now())
                republished.append((str(job.id), JobPriority(job.priority)))
        for job_id, priority in republished:
            self._queue.publish(job_id, priority)
        return len(republished)
