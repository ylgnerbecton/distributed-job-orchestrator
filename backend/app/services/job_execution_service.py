import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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


class JobExecutionService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        queue: JobQueue,
        settings: Settings,
        worker_id: str,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._session_factory = session_factory
        self._queue = queue
        self._settings = settings
        self._worker_id = worker_id
        self._sleep = sleep

    async def execute(self, job_id: uuid.UUID) -> bool:
        claim = await self._claim(job_id)
        if claim is None:
            return False
        attempt_number, attempt_id, snapshot = claim
        stop_heartbeat = asyncio.Event()
        heartbeat_task = asyncio.create_task(self._heartbeat_loop(job_id, stop_heartbeat))
        context = ExecutionContext(
            job_id=str(job_id),
            attempt=attempt_number,
            settings=self._settings,
            check_cancelled=lambda: self._check_cancelled(job_id),
            report_progress=lambda progress: self._report_progress(job_id, progress),
            sleep=self._sleep,
        )
        handler = get_handler(JobType(snapshot.type))
        try:
            result = await handler(snapshot.payload, context)
        except JobCancelledError:
            await self._finalize_cancelled(job_id, attempt_id)
        except NonRetryableError as error:
            await self._finalize_failed(job_id, attempt_id, error.code, error.message, dead_lettered=False)
        except RetryableError as error:
            await self._handle_retryable(
                job_id, attempt_id, attempt_number, snapshot.max_attempts, error.code, error.message
            )
        except Exception as error:
            await self._handle_retryable(
                job_id, attempt_id, attempt_number, snapshot.max_attempts, "UNEXPECTED_ERROR", str(error)
            )
        else:
            await self._finalize_succeeded(job_id, attempt_id, result)
        finally:
            stop_heartbeat.set()
            await heartbeat_task
        return True

    async def _heartbeat_loop(self, job_id: uuid.UUID, stop_event: asyncio.Event) -> None:
        interval = self._settings.worker_heartbeat_seconds
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                async with self._session_factory() as session, session.begin():
                    await JobRepository(session).heartbeat(
                        job_id, self._worker_id, self._settings.worker_lease_seconds, clock_now()
                    )

    async def _claim(self, job_id: uuid.UUID) -> tuple[int, uuid.UUID, _JobSnapshot] | None:
        now = clock_now()
        async with self._session_factory() as session, session.begin():
            jobs = JobRepository(session)
            job = await jobs.get(job_id)
            if job is None:
                return None
            attempt_number = await jobs.claim_for_execution(
                job_id, self._worker_id, self._settings.worker_lease_seconds, now
            )
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

    async def _check_cancelled(self, job_id: uuid.UUID) -> None:
        if await self._cancellation_requested(job_id):
            raise JobCancelledError

    async def _cancellation_requested(self, job_id: uuid.UUID) -> bool:
        async with self._session_factory() as session, session.begin():
            job = await JobRepository(session).get(job_id)
            return job is not None and job.cancellation_requested_at is not None

    async def _report_progress(self, job_id: uuid.UUID, progress: int) -> None:
        async with self._session_factory() as session, session.begin():
            await JobRepository(session).update_progress(
                job_id, self._worker_id, progress, self._settings.worker_lease_seconds, clock_now()
            )

    async def _handle_retryable(
        self, job_id: uuid.UUID, attempt_id: uuid.UUID, attempt_number: int, max_attempts: int, code: str, message: str
    ) -> None:
        if await self._cancellation_requested(job_id):
            await self._finalize_cancelled(job_id, attempt_id)
            return
        if attempt_number >= max_attempts:
            if await self._finalize_failed(job_id, attempt_id, code, message, dead_lettered=True):
                await self._queue.dead_letter(str(job_id))
            return
        backoff = compute_backoff_seconds(attempt_number, self._settings)
        await self._schedule_retry(job_id, attempt_id, code, message, clock_now() + timedelta(seconds=backoff))

    async def _finalize_succeeded(self, job_id: uuid.UUID, attempt_id: uuid.UUID, result: dict) -> None:
        now = clock_now()
        async with self._session_factory() as session, session.begin():
            jobs = JobRepository(session)
            attempts = JobAttemptRepository(session)
            job = await jobs.get(job_id)
            if job is None or not await jobs.mark_succeeded(job_id, self._worker_id, result, now):
                await self._mark_superseded(attempts, attempt_id, "succeeded", now)
                return
            await attempts.finish(attempt_id=attempt_id, status=JobStatus.SUCCEEDED, now=now)
            JobEventRepository(session).record(
                job_id=job_id, event_type=JobEventType.SUCCEEDED, to_status=JobStatus.SUCCEEDED
            )
            await enqueue_terminal_notification(
                NotificationOutboxRepository(session),
                job=job,
                event_type=JobEventType.SUCCEEDED,
                status=JobStatus.SUCCEEDED,
                result=result,
                error_code=None,
                error_message=None,
                now=now,
            )

    async def _finalize_failed(
        self, job_id: uuid.UUID, attempt_id: uuid.UUID, code: str, message: str, dead_lettered: bool
    ) -> bool:
        now = clock_now()
        async with self._session_factory() as session, session.begin():
            jobs = JobRepository(session)
            attempts = JobAttemptRepository(session)
            job = await jobs.get(job_id)
            if job is None or not await jobs.mark_failed(job_id, self._worker_id, code, message, now, dead_lettered):
                await self._mark_superseded(attempts, attempt_id, "failed", now)
                return False
            await attempts.finish(
                attempt_id=attempt_id, status=JobStatus.FAILED, now=now, error_code=code, error_message=message
            )
            JobEventRepository(session).record(
                job_id=job_id,
                event_type=JobEventType.FAILED,
                to_status=JobStatus.FAILED,
                detail={"error_code": code, "dead_lettered": dead_lettered},
            )
            await enqueue_terminal_notification(
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

    async def _schedule_retry(
        self, job_id: uuid.UUID, attempt_id: uuid.UUID, code: str, message: str, next_attempt_at: datetime
    ) -> None:
        now = clock_now()
        async with self._session_factory() as session, session.begin():
            jobs = JobRepository(session)
            attempts = JobAttemptRepository(session)
            if not await jobs.schedule_retry(job_id, self._worker_id, code, message, next_attempt_at, now):
                await self._mark_superseded(attempts, attempt_id, "retry", now)
                return
            await attempts.finish(
                attempt_id=attempt_id, status=JobStatus.FAILED, now=now, error_code=code, error_message=message
            )
            JobEventRepository(session).record(
                job_id=job_id,
                event_type=JobEventType.RETRY_SCHEDULED,
                from_status=JobStatus.RUNNING,
                to_status=JobStatus.RETRYING,
                detail={"error_code": code, "next_attempt_at": next_attempt_at.isoformat()},
            )

    async def _finalize_cancelled(self, job_id: uuid.UUID, attempt_id: uuid.UUID) -> None:
        now = clock_now()
        async with self._session_factory() as session, session.begin():
            jobs = JobRepository(session)
            attempts = JobAttemptRepository(session)
            job = await jobs.get(job_id)
            if job is None or not await jobs.finalize_cancelled_by_worker(job_id, self._worker_id, now):
                await self._mark_superseded(attempts, attempt_id, "cancelled", now)
                return
            await attempts.finish(attempt_id=attempt_id, status=JobStatus.CANCELLED, now=now)
            JobEventRepository(session).record(
                job_id=job_id, event_type=JobEventType.CANCELLED, to_status=JobStatus.CANCELLED
            )
            await enqueue_terminal_notification(
                NotificationOutboxRepository(session),
                job=job,
                event_type=JobEventType.CANCELLED,
                status=JobStatus.CANCELLED,
                result=None,
                error_code=None,
                error_message=None,
                now=now,
            )

    async def _mark_superseded(
        self, attempts: JobAttemptRepository, attempt_id: uuid.UUID, outcome: str, now: datetime
    ) -> None:
        await attempts.finish(
            attempt_id=attempt_id,
            status=JobStatus.FAILED,
            now=now,
            error_code="SUPERSEDED",
            error_message="attempt superseded before finalize",
        )
        _logger.warning("execution.finalize_skipped", attempt=str(attempt_id), outcome=outcome)
