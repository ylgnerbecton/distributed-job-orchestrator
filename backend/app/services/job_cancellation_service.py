import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.clock import now as clock_now
from app.domain.enums import TERMINAL_STATUSES, JobEventType, JobStatus
from app.repositories.job_event_repository import JobEventRepository
from app.repositories.job_repository import JobRepository
from app.repositories.notification_outbox_repository import NotificationOutboxRepository
from app.services.notification_service import enqueue_terminal_notification


@dataclass(frozen=True)
class CancelOutcome:
    found: bool
    status: JobStatus | None
    conflict: bool = False


class JobCancellationService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def cancel(self, job_id: uuid.UUID, user_id: str, reason: str | None) -> CancelOutcome:
        now = clock_now()
        with self._session.begin():
            jobs = JobRepository(self._session)
            events = JobEventRepository(self._session)
            job = jobs.lock_for_user(job_id, user_id)
            if job is None:
                return CancelOutcome(found=False, status=None)
            status = JobStatus(job.status)
            if status in TERMINAL_STATUSES:
                return CancelOutcome(found=True, status=status, conflict=True)
            if status == JobStatus.CANCELLING:
                return CancelOutcome(found=True, status=JobStatus.CANCELLING)
            if status == JobStatus.RUNNING:
                jobs.request_running_cancellation(job_id, reason, now)
                events.record(
                    job_id=job_id,
                    event_type=JobEventType.CANCEL_REQUESTED,
                    from_status=status,
                    to_status=JobStatus.CANCELLING,
                    detail={"reason": reason},
                )
                return CancelOutcome(found=True, status=JobStatus.CANCELLING)
            jobs.cancel_inactive(job_id, reason, now)
            events.record(
                job_id=job_id,
                event_type=JobEventType.CANCELLED,
                from_status=status,
                to_status=JobStatus.CANCELLED,
                detail={"reason": reason},
            )
            enqueue_terminal_notification(
                NotificationOutboxRepository(self._session),
                job=job,
                event_type=JobEventType.CANCELLED,
                status=JobStatus.CANCELLED,
                result=None,
                error_code=None,
                error_message=None,
                now=now,
            )
            return CancelOutcome(found=True, status=JobStatus.CANCELLED)
