import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import CursorPosition, decode_cursor, encode_cursor
from app.domain.enums import JobStatus, JobType
from app.repositories.job_event_repository import JobEventRepository
from app.repositories.job_repository import JobRepository
from app.schemas.jobs import JobEvent, JobRead, JobSummary, JobSummaryCounts
from app.schemas.pagination import PaginatedResponse


class JobReadService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, job_id: uuid.UUID, user_id: str) -> JobRead | None:
        job = await JobRepository(self._session).get_for_user(job_id, user_id)
        return JobRead.model_validate(job) if job is not None else None

    async def list_jobs(
        self,
        *,
        user_id: str,
        status: JobStatus | None,
        job_type: JobType | None,
        cursor: str | None,
        limit: int,
    ) -> PaginatedResponse[JobSummary]:
        position = decode_cursor(cursor) if cursor else None
        rows = await JobRepository(self._session).list_for_user(
            user_id=user_id,
            status=status,
            job_type=job_type,
            cursor=position,
            limit=limit + 1,
        )
        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor = None
        if has_more and page:
            last = page[-1]
            next_cursor = encode_cursor(CursorPosition(created_at=last.created_at, job_id=last.id))
        items = [JobSummary.model_validate(row) for row in page]
        return PaginatedResponse[JobSummary](items=items, next_cursor=next_cursor, has_more=has_more)

    async def summary(self, user_id: str) -> JobSummaryCounts:
        counts = await JobRepository(self._session).status_counts(user_id)
        return JobSummaryCounts(counts=counts, total=sum(counts.values()))

    async def events(self, job_id: uuid.UUID, user_id: str, limit: int) -> list[JobEvent] | None:
        jobs = JobRepository(self._session)
        if await jobs.get_for_user(job_id, user_id) is None:
            return None
        rows = await JobEventRepository(self._session).list_for_job(job_id, limit)
        return [JobEvent.model_validate(row) for row in rows]
