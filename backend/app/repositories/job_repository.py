import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import CursorPosition
from app.db.models import Job
from app.domain.enums import TERMINAL_STATUSES, JobStatus, JobType

_TERMINAL = [status.value for status in TERMINAL_STATUSES]
_CLAIMABLE = [JobStatus.QUEUED.value, JobStatus.RETRYING.value]
_FINALIZABLE = [JobStatus.RUNNING.value, JobStatus.CANCELLING.value]
_INACTIVE_CANCELLABLE = [JobStatus.PENDING.value, JobStatus.QUEUED.value, JobStatus.RETRYING.value]
_EXPIRABLE = [JobStatus.PENDING.value, JobStatus.QUEUED.value]


class JobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, job: Job) -> None:
        self._session.add(job)

    async def get(self, job_id: uuid.UUID) -> Job | None:
        return await self._session.get(Job, job_id)

    async def get_for_user(self, job_id: uuid.UUID, user_id: str) -> Job | None:
        stmt = select(Job).where(Job.id == job_id, Job.user_id == user_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def lock_for_user(self, job_id: uuid.UUID, user_id: str) -> Job | None:
        stmt = select(Job).where(Job.id == job_id, Job.user_id == user_id).with_for_update()
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_idempotency_key(self, user_id: str, idempotency_key: str) -> Job | None:
        stmt = select(Job).where(Job.user_id == user_id, Job.idempotency_key == idempotency_key)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_user(
        self,
        *,
        user_id: str,
        status: JobStatus | None,
        job_type: JobType | None,
        cursor: CursorPosition | None,
        limit: int,
    ) -> list[Job]:
        stmt = select(Job).where(Job.user_id == user_id)
        if status is not None:
            stmt = stmt.where(Job.status == status.value)
        if job_type is not None:
            stmt = stmt.where(Job.type == job_type.value)
        if cursor is not None:
            stmt = stmt.where(tuple_(Job.created_at, Job.id) < tuple_(cursor.created_at, cursor.job_id))
        stmt = stmt.order_by(Job.created_at.desc(), Job.id.desc()).limit(limit)
        return list((await self._session.execute(stmt)).scalars().all())

    async def status_counts(self, user_id: str) -> dict[str, int]:
        stmt = select(Job.status, func.count()).where(Job.user_id == user_id).group_by(Job.status)
        return {row[0]: int(row[1]) for row in (await self._session.execute(stmt)).all()}

    async def count_active_for_user(self, user_id: str) -> int:
        stmt = select(func.count()).select_from(Job).where(Job.user_id == user_id, Job.status.notin_(_TERMINAL))
        return int((await self._session.execute(stmt)).scalar_one())

    async def find_due_retries(self, now: datetime, limit: int) -> list[Job]:
        stmt = (
            select(Job)
            .where(Job.status == JobStatus.RETRYING.value, Job.next_attempt_at <= now)
            .order_by(Job.next_attempt_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def find_expired_leases(self, now: datetime, limit: int) -> list[Job]:
        stmt = (
            select(Job)
            .where(Job.status == JobStatus.RUNNING.value, Job.lock_expires_at < now)
            .order_by(Job.lock_expires_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def find_stuck_queued(self, cutoff: datetime, limit: int) -> list[Job]:
        stmt = (
            select(Job)
            .where(
                Job.status == JobStatus.QUEUED.value,
                or_(Job.last_dispatched_at.is_(None), Job.last_dispatched_at < cutoff),
            )
            .order_by(Job.last_dispatched_at.asc().nulls_first())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def mark_redispatched(self, job_id: uuid.UUID, now: datetime) -> None:
        stmt = (
            update(Job)
            .where(Job.id == job_id, Job.status == JobStatus.QUEUED.value)
            .values(last_dispatched_at=now, updated_at=now)
        )
        await self._session.execute(stmt)

    async def find_expirable(self, cutoff: datetime, limit: int) -> list[Job]:
        stmt = (
            select(Job)
            .where(Job.status.in_(_EXPIRABLE), Job.created_at < cutoff)
            .order_by(Job.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def claim_for_execution(
        self, job_id: uuid.UUID, worker_id: str, lease_seconds: int, now: datetime
    ) -> int | None:
        stmt = (
            update(Job)
            .where(Job.id == job_id, Job.status.in_(_CLAIMABLE), Job.cancellation_requested_at.is_(None))
            .values(
                status=JobStatus.RUNNING.value,
                attempts=Job.attempts + 1,
                locked_by=worker_id,
                lock_expires_at=now + timedelta(seconds=lease_seconds),
                heartbeat_at=now,
                started_at=func.coalesce(Job.started_at, now),
                next_attempt_at=None,
                updated_at=now,
            )
            .returning(Job.attempts)
        )
        row = (await self._session.execute(stmt)).first()
        return int(row[0]) if row is not None else None

    async def heartbeat(self, job_id: uuid.UUID, worker_id: str, lease_seconds: int, now: datetime) -> bool:
        stmt = (
            update(Job)
            .where(Job.id == job_id, Job.locked_by == worker_id, Job.status == JobStatus.RUNNING.value)
            .values(heartbeat_at=now, lock_expires_at=now + timedelta(seconds=lease_seconds), updated_at=now)
        )
        return (await self._session.execute(stmt)).rowcount > 0

    async def update_progress(
        self, job_id: uuid.UUID, worker_id: str, progress: int, lease_seconds: int, now: datetime
    ) -> bool:
        stmt = (
            update(Job)
            .where(Job.id == job_id, Job.locked_by == worker_id, Job.status.in_(_FINALIZABLE))
            .values(
                progress=progress,
                heartbeat_at=now,
                lock_expires_at=now + timedelta(seconds=lease_seconds),
                updated_at=now,
            )
        )
        return (await self._session.execute(stmt)).rowcount > 0

    async def mark_succeeded(self, job_id: uuid.UUID, worker_id: str, result: dict, now: datetime) -> bool:
        stmt = (
            update(Job)
            .where(Job.id == job_id, Job.locked_by == worker_id, Job.status.in_(_FINALIZABLE))
            .values(
                status=JobStatus.SUCCEEDED.value,
                result=result,
                progress=100,
                completed_at=now,
                locked_by=None,
                lock_expires_at=None,
                error_code=None,
                error_message=None,
                updated_at=now,
            )
        )
        return (await self._session.execute(stmt)).rowcount > 0

    async def mark_failed(
        self, job_id: uuid.UUID, worker_id: str, error_code: str, error_message: str, now: datetime, dead_lettered: bool
    ) -> bool:
        stmt = (
            update(Job)
            .where(Job.id == job_id, Job.locked_by == worker_id, Job.status.in_(_FINALIZABLE))
            .values(
                status=JobStatus.FAILED.value,
                error_code=error_code,
                error_message=error_message,
                completed_at=now,
                locked_by=None,
                lock_expires_at=None,
                dead_lettered_at=now if dead_lettered else None,
                updated_at=now,
            )
        )
        return (await self._session.execute(stmt)).rowcount > 0

    async def schedule_retry(
        self,
        job_id: uuid.UUID,
        worker_id: str,
        error_code: str,
        error_message: str,
        next_attempt_at: datetime,
        now: datetime,
    ) -> bool:
        stmt = (
            update(Job)
            .where(Job.id == job_id, Job.locked_by == worker_id, Job.status == JobStatus.RUNNING.value)
            .values(
                status=JobStatus.RETRYING.value,
                error_code=error_code,
                error_message=error_message,
                next_attempt_at=next_attempt_at,
                locked_by=None,
                lock_expires_at=None,
                updated_at=now,
            )
        )
        return (await self._session.execute(stmt)).rowcount > 0

    async def finalize_cancelled_by_worker(self, job_id: uuid.UUID, worker_id: str, now: datetime) -> bool:
        stmt = (
            update(Job)
            .where(Job.id == job_id, Job.locked_by == worker_id, Job.status.in_(_FINALIZABLE))
            .values(
                status=JobStatus.CANCELLED.value,
                completed_at=now,
                locked_by=None,
                lock_expires_at=None,
                updated_at=now,
            )
        )
        return (await self._session.execute(stmt)).rowcount > 0

    async def cancel_inactive(self, job_id: uuid.UUID, reason: str | None, now: datetime) -> bool:
        stmt = (
            update(Job)
            .where(Job.id == job_id, Job.status.in_(_INACTIVE_CANCELLABLE))
            .values(
                status=JobStatus.CANCELLED.value,
                cancellation_requested_at=now,
                cancel_reason=reason,
                completed_at=now,
                next_attempt_at=None,
                updated_at=now,
            )
        )
        return (await self._session.execute(stmt)).rowcount > 0

    async def request_running_cancellation(self, job_id: uuid.UUID, reason: str | None, now: datetime) -> bool:
        stmt = (
            update(Job)
            .where(Job.id == job_id, Job.status == JobStatus.RUNNING.value)
            .values(
                status=JobStatus.CANCELLING.value, cancellation_requested_at=now, cancel_reason=reason, updated_at=now
            )
        )
        return (await self._session.execute(stmt)).rowcount > 0

    async def mark_queued(self, job_id: uuid.UUID, now: datetime) -> bool:
        stmt = (
            update(Job)
            .where(Job.id == job_id, Job.status == JobStatus.PENDING.value)
            .values(status=JobStatus.QUEUED.value, queued_at=now, last_dispatched_at=now, updated_at=now)
        )
        return (await self._session.execute(stmt)).rowcount > 0

    async def requeue_expired_lease(self, job_id: uuid.UUID, now: datetime) -> bool:
        stmt = (
            update(Job)
            .where(Job.id == job_id, Job.status == JobStatus.RUNNING.value)
            .values(
                status=JobStatus.QUEUED.value,
                queued_at=now,
                last_dispatched_at=now,
                locked_by=None,
                lock_expires_at=None,
                updated_at=now,
            )
        )
        return (await self._session.execute(stmt)).rowcount > 0

    async def fail_expired_lease(
        self, job_id: uuid.UUID, error_code: str, error_message: str, now: datetime, dead_lettered: bool
    ) -> bool:
        stmt = (
            update(Job)
            .where(Job.id == job_id, Job.status == JobStatus.RUNNING.value)
            .values(
                status=JobStatus.FAILED.value,
                error_code=error_code,
                error_message=error_message,
                completed_at=now,
                locked_by=None,
                lock_expires_at=None,
                dead_lettered_at=now if dead_lettered else None,
                updated_at=now,
            )
        )
        return (await self._session.execute(stmt)).rowcount > 0

    async def move_retry_to_queued(self, job_id: uuid.UUID, now: datetime) -> bool:
        stmt = (
            update(Job)
            .where(Job.id == job_id, Job.status == JobStatus.RETRYING.value)
            .values(
                status=JobStatus.QUEUED.value,
                queued_at=now,
                last_dispatched_at=now,
                next_attempt_at=None,
                updated_at=now,
            )
        )
        return (await self._session.execute(stmt)).rowcount > 0

    async def expire(self, job_id: uuid.UUID, now: datetime) -> bool:
        stmt = (
            update(Job)
            .where(Job.id == job_id, Job.status.in_(_EXPIRABLE))
            .values(status=JobStatus.EXPIRED.value, completed_at=now, updated_at=now)
        )
        return (await self._session.execute(stmt)).rowcount > 0
