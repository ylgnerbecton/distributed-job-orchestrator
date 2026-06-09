import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.clock import now as clock_now
from app.core.config import Settings
from app.core.logging import get_logger
from app.domain.backoff import compute_backoff_seconds
from app.domain.enums import JobEventType, JobStatus, JobType
from app.domain.errors import JobCancelledError, NonRetryableError, RetryableError
from app.domain.job_catalog import ExecutionContext, get_handler
from app.queue.redis_queue import JobQueue
from app.repositories.job_attempt_repository import JobAttemptRepository
from app.repositories.job_event_repository import JobEventRepository
from app.repositories.job_repository import JobRepository
from app.repositories.notification_outbox_repository import NotificationOutboxRepository
from app.services.notification_service import enqueue_terminal_notification

_logger = get_logger()


@dataclass(frozen=True)
class _JobSnapshot:
    type: str
    payload: dict
    max_attempts: int


class _Heartbeat:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        job_id: uuid.UUID,
        worker_id: str,
        lease_seconds: int,
        interval_seconds: int,
    ) -> None:
        self._session_factory = session_factory
        self._job_id = job_id
        self._worker_id = worker_id
        self._lease_seconds = lease_seconds
        self._interval_seconds = interval_seconds
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> "_Heartbeat":
        self._thread.start()
        return self

    def _run(self) -> None:
        while not self._stop_event.wait(self._interval_seconds):
            with self._session_factory() as session, session.begin():
                JobRepository(session).heartbeat(self._job_id, self._worker_id, self._lease_seconds, clock_now())

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=self._interval_seconds + 1)


class JobExecutionService:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        queue: JobQueue,
        settings: Settings,
        worker_id: str,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._session_factory = session_factory
        self._queue = queue
        self._settings = settings
        self._worker_id = worker_id
        self._sleeper = sleeper

    def execute(self, job_id: uuid.UUID) -> bool:
        claim = self._claim(job_id)
        if claim is None:
            return False
        attempt_number, attempt_id, snapshot = claim
        heartbeat = _Heartbeat(
            self._session_factory,
            job_id,
            self._worker_id,
            self._settings.worker_lease_seconds,
            self._settings.worker_heartbeat_seconds,
        ).start()
        context = ExecutionContext(
            job_id=str(job_id),
            attempt=attempt_number,
            settings=self._settings,
            check_cancelled=lambda: self._check_cancelled(job_id),
            report_progress=lambda progress: self._report_progress(job_id, progress),
            sleeper=self._sleeper,
        )
        handler = get_handler(JobType(snapshot.type))
        try:
            result = handler(snapshot.payload, context)
        except JobCancelledError:
            self._finalize_cancelled(job_id, attempt_id)
        except NonRetryableError as error:
            self._finalize_failed(job_id, attempt_id, error.code, error.message, dead_lettered=False)
        except RetryableError as error:
            self._handle_retryable(job_id, attempt_id, attempt_number, snapshot.max_attempts, error.code, error.message)
        except Exception as error:
            self._handle_retryable(
                job_id, attempt_id, attempt_number, snapshot.max_attempts, "UNEXPECTED_ERROR", str(error)
            )
        else:
            self._finalize_succeeded(job_id, attempt_id, result)
        finally:
            heartbeat.stop()
        return True

    def _claim(self, job_id: uuid.UUID) -> tuple[int, uuid.UUID, _JobSnapshot] | None:
        now = clock_now()
        with self._session_factory() as session, session.begin():
            jobs = JobRepository(session)
            job = jobs.get(job_id)
            if job is None:
                return None
            attempt_number = jobs.claim_for_execution(job_id, self._worker_id, self._settings.worker_lease_seconds, now)
            if attempt_number is None:
                return None
            attempt_id = JobAttemptRepository(session).start(
                job_id=job_id, attempt_number=attempt_number, worker_id=self._worker_id, now=now
            )
            JobEventRepository(session).record(
                job_id=job_id,
                event_type=JobEventType.STARTED,
                to_status=JobStatus.RUNNING,
                detail={"attempt": attempt_number, "worker_id": self._worker_id},
            )
            return (
                attempt_number,
                attempt_id,
                _JobSnapshot(type=job.type, payload=dict(job.payload), max_attempts=job.max_attempts),
            )

    def _check_cancelled(self, job_id: uuid.UUID) -> None:
        if self._cancellation_requested(job_id):
            raise JobCancelledError

    def _cancellation_requested(self, job_id: uuid.UUID) -> bool:
        with self._session_factory() as session, session.begin():
            job = JobRepository(session).get(job_id)
            return job is not None and job.cancellation_requested_at is not None

    def _report_progress(self, job_id: uuid.UUID, progress: int) -> None:
        with self._session_factory() as session, session.begin():
            JobRepository(session).update_progress(
                job_id, self._worker_id, progress, self._settings.worker_lease_seconds, clock_now()
            )

    def _handle_retryable(
        self,
        job_id: uuid.UUID,
        attempt_id: uuid.UUID,
        attempt_number: int,
        max_attempts: int,
        code: str,
        message: str,
    ) -> None:
        if self._cancellation_requested(job_id):
            self._finalize_cancelled(job_id, attempt_id)
            return
        if attempt_number >= max_attempts:
            if self._finalize_failed(job_id, attempt_id, code, message, dead_lettered=True):
                self._queue.dead_letter(str(job_id))
            return
        backoff = compute_backoff_seconds(attempt_number, self._settings)
        self._schedule_retry(job_id, attempt_id, code, message, clock_now() + timedelta(seconds=backoff))

    def _finalize_succeeded(self, job_id: uuid.UUID, attempt_id: uuid.UUID, result: dict) -> None:
        now = clock_now()
        with self._session_factory() as session, session.begin():
            jobs = JobRepository(session)
            attempts = JobAttemptRepository(session)
            job = jobs.get(job_id)
            if job is None or not jobs.mark_succeeded(job_id, self._worker_id, result, now):
                self._mark_superseded(attempts, attempt_id, "succeeded", now)
                return
            attempts.finish(attempt_id=attempt_id, status=JobStatus.SUCCEEDED, now=now)
            JobEventRepository(session).record(
                job_id=job_id, event_type=JobEventType.SUCCEEDED, to_status=JobStatus.SUCCEEDED
            )
            enqueue_terminal_notification(
                NotificationOutboxRepository(session),
                job=job,
                event_type=JobEventType.SUCCEEDED,
                status=JobStatus.SUCCEEDED,
                result=result,
                error_code=None,
                error_message=None,
                now=now,
            )

    def _finalize_failed(
        self, job_id: uuid.UUID, attempt_id: uuid.UUID, code: str, message: str, dead_lettered: bool
    ) -> bool:
        now = clock_now()
        with self._session_factory() as session, session.begin():
            jobs = JobRepository(session)
            attempts = JobAttemptRepository(session)
            job = jobs.get(job_id)
            if job is None or not jobs.mark_failed(job_id, self._worker_id, code, message, now, dead_lettered):
                self._mark_superseded(attempts, attempt_id, "failed", now)
                return False
            attempts.finish(
                attempt_id=attempt_id, status=JobStatus.FAILED, now=now, error_code=code, error_message=message
            )
            JobEventRepository(session).record(
                job_id=job_id,
                event_type=JobEventType.FAILED,
                to_status=JobStatus.FAILED,
                detail={"error_code": code, "dead_lettered": dead_lettered},
            )
            enqueue_terminal_notification(
                NotificationOutboxRepository(session),
                job=job,
                event_type=JobEventType.FAILED,
                status=JobStatus.FAILED,
                result=None,
                error_code=code,
                error_message=message,
                now=now,
            )
            return True

    def _schedule_retry(
        self, job_id: uuid.UUID, attempt_id: uuid.UUID, code: str, message: str, next_attempt_at
    ) -> None:
        now = clock_now()
        with self._session_factory() as session, session.begin():
            jobs = JobRepository(session)
            attempts = JobAttemptRepository(session)
            if not jobs.schedule_retry(job_id, self._worker_id, code, message, next_attempt_at, now):
                self._mark_superseded(attempts, attempt_id, "retry", now)
                return
            attempts.finish(
                attempt_id=attempt_id, status=JobStatus.FAILED, now=now, error_code=code, error_message=message
            )
            JobEventRepository(session).record(
                job_id=job_id,
                event_type=JobEventType.RETRY_SCHEDULED,
                from_status=JobStatus.RUNNING,
                to_status=JobStatus.RETRYING,
                detail={"error_code": code, "next_attempt_at": next_attempt_at.isoformat()},
            )

    def _finalize_cancelled(self, job_id: uuid.UUID, attempt_id: uuid.UUID) -> None:
        now = clock_now()
        with self._session_factory() as session, session.begin():
            jobs = JobRepository(session)
            attempts = JobAttemptRepository(session)
            job = jobs.get(job_id)
            if job is None or not jobs.finalize_cancelled_by_worker(job_id, self._worker_id, now):
                self._mark_superseded(attempts, attempt_id, "cancelled", now)
                return
            attempts.finish(attempt_id=attempt_id, status=JobStatus.CANCELLED, now=now)
            JobEventRepository(session).record(
                job_id=job_id, event_type=JobEventType.CANCELLED, to_status=JobStatus.CANCELLED
            )
            enqueue_terminal_notification(
                NotificationOutboxRepository(session),
                job=job,
                event_type=JobEventType.CANCELLED,
                status=JobStatus.CANCELLED,
                result=None,
                error_code=None,
                error_message=None,
                now=now,
            )

    def _mark_superseded(self, attempts: JobAttemptRepository, attempt_id: uuid.UUID, outcome: str, now) -> None:
        attempts.finish(
            attempt_id=attempt_id,
            status=JobStatus.FAILED,
            now=now,
            error_code="SUPERSEDED",
            error_message="attempt superseded before finalize",
        )
        _logger.warning("execution.finalize_skipped", attempt=str(attempt_id), outcome=outcome)
