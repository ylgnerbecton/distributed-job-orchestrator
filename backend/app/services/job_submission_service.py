import json

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import now as clock_now
from app.core.config import Settings
from app.db.models import Job
from app.domain.enums import JobEventType, JobPriority, JobStatus, JobType
from app.domain.errors import PayloadTooLargeError, TooManyActiveJobsError
from app.domain.job_catalog import normalize_payload
from app.repositories.dispatch_outbox_repository import DispatchOutboxRepository
from app.repositories.job_event_repository import JobEventRepository
from app.repositories.job_repository import JobRepository


class JobSubmissionService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    async def submit(
        self,
        *,
        user_id: str,
        job_type: JobType,
        payload: dict,
        priority: JobPriority,
        max_attempts: int | None,
        idempotency_key: str | None,
    ) -> Job:
        if len(json.dumps(payload).encode()) > self._settings.job_max_payload_bytes:
            raise PayloadTooLargeError("payload exceeds the maximum allowed size")
        normalized = normalize_payload(job_type, payload, self._settings)
        if isinstance(payload, dict) and "notify_webhook" in payload:
            normalized["notify_webhook"] = str(payload["notify_webhook"])
        attempts_limit = max_attempts if max_attempts is not None else self._settings.job_default_max_attempts

        if idempotency_key is not None:
            existing = await self._find_existing(user_id, idempotency_key)
            if existing is not None:
                return existing
        try:
            return await self._create(user_id, job_type, normalized, priority, attempts_limit, idempotency_key)
        except IntegrityError:
            if idempotency_key is not None:
                existing = await self._find_existing(user_id, idempotency_key)
                if existing is not None:
                    return existing
            raise

    async def _find_existing(self, user_id: str, idempotency_key: str) -> Job | None:
        async with self._session.begin():
            return await JobRepository(self._session).get_by_idempotency_key(user_id, idempotency_key)

    async def _create(
        self,
        user_id: str,
        job_type: JobType,
        payload: dict,
        priority: JobPriority,
        max_attempts: int,
        idempotency_key: str | None,
    ) -> Job:
        now = clock_now()
        async with self._session.begin():
            jobs = JobRepository(self._session)
            active = await jobs.count_active_for_user(user_id)
            if active >= self._settings.max_in_flight_jobs_per_user:
                raise TooManyActiveJobsError(self._settings.max_in_flight_jobs_per_user)
            job = Job(
                user_id=user_id,
                type=job_type.value,
                status=JobStatus.PENDING.value,
                priority=priority.value,
                payload=payload,
                progress=0,
                attempts=0,
                max_attempts=max_attempts,
                idempotency_key=idempotency_key,
                created_at=now,
                updated_at=now,
            )
            jobs.add(job)
            await self._session.flush()
            JobEventRepository(self._session).record(
                job_id=job.id,
                event_type=JobEventType.SUBMITTED,
                to_status=JobStatus.PENDING,
                detail={"type": job_type.value, "priority": priority.value},
            )
            DispatchOutboxRepository(self._session).add(job.id)
            return job
