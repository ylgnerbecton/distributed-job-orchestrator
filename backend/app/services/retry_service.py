from collections.abc import Callable

from sqlalchemy.orm import Session

from app.core.clock import now as clock_now
from app.domain.enums import JobEventType, JobPriority, JobStatus
from app.queue.redis_queue import JobQueue
from app.repositories.job_event_repository import JobEventRepository
from app.repositories.job_repository import JobRepository


class RetryService:
    def __init__(self, session_factory: Callable[[], Session], queue: JobQueue) -> None:
        self._session_factory = session_factory
        self._queue = queue

    def promote_due(self, batch_size: int) -> int:
        now = clock_now()
        promoted: list[tuple[str, JobPriority]] = []
        with self._session_factory() as session, session.begin():
            jobs = JobRepository(session)
            events = JobEventRepository(session)
            for job in jobs.find_due_retries(now, batch_size):
                if jobs.move_retry_to_queued(job.id, now):
                    events.record(
                        job_id=job.id,
                        event_type=JobEventType.QUEUED,
                        from_status=JobStatus.RETRYING,
                        to_status=JobStatus.QUEUED,
                        detail={"attempt": job.attempts},
                    )
                    promoted.append((str(job.id), JobPriority(job.priority)))
        for job_id, priority in promoted:
            self._queue.publish(job_id, priority)
        return len(promoted)
