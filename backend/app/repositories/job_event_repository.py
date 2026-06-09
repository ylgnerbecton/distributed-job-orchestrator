import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import JobEvent
from app.domain.enums import JobEventType, JobStatus


class JobEventRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def record(
        self,
        *,
        job_id: uuid.UUID,
        event_type: JobEventType,
        from_status: JobStatus | None = None,
        to_status: JobStatus | None = None,
        detail: dict | None = None,
    ) -> None:
        self._session.add(
            JobEvent(
                job_id=job_id,
                event_type=event_type.value,
                from_status=from_status.value if from_status is not None else None,
                to_status=to_status.value if to_status is not None else None,
                detail=detail or {},
            )
        )

    def list_for_job(self, job_id: uuid.UUID, limit: int) -> list[JobEvent]:
        stmt = (
            select(JobEvent)
            .where(JobEvent.job_id == job_id)
            .order_by(JobEvent.created_at.desc(), JobEvent.id.desc())
            .limit(limit)
        )
        return list(self._session.execute(stmt).scalars().all())
