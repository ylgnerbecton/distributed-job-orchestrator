import uuid

from sqlalchemy.orm import Session

from app.core.pagination import CursorPosition, decode_cursor, encode_cursor
from app.db.models import Job, JobEvent
from app.domain.enums import JobStatus, JobType
from app.repositories.job_event_repository import JobEventRepository
from app.repositories.job_repository import JobRepository


class JobReadService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, job_id: uuid.UUID, user_id: str) -> Job | None:
        return JobRepository(self._session).get_for_user(job_id, user_id)

    def list_jobs(
        self,
        *,
        user_id: str,
        status: JobStatus | None,
        job_type: JobType | None,
        cursor: str | None,
        limit: int,
    ) -> dict:
        position = decode_cursor(cursor) if cursor else None
        rows = JobRepository(self._session).list_for_user(
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
        return {"items": page, "next_cursor": next_cursor, "has_more": has_more}

    def summary(self, user_id: str) -> dict:
        counts = JobRepository(self._session).status_counts(user_id)
        return {"counts": counts, "total": sum(counts.values())}

    def events(self, job_id: uuid.UUID, user_id: str, limit: int) -> list[JobEvent] | None:
        jobs = JobRepository(self._session)
        if jobs.get_for_user(job_id, user_id) is None:
            return None
        return JobEventRepository(self._session).list_for_job(job_id, limit)
