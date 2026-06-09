import uuid
from datetime import datetime

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.ids import generate_uuid7
from app.db.models import JobAttempt
from app.domain.enums import JobStatus


class JobAttemptRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def start(self, *, job_id: uuid.UUID, attempt_number: int, worker_id: str, now: datetime) -> uuid.UUID:
        attempt_id = generate_uuid7()
        self._session.add(
            JobAttempt(
                id=attempt_id,
                job_id=job_id,
                attempt_number=attempt_number,
                worker_id=worker_id,
                status=JobStatus.RUNNING.value,
                started_at=now,
            )
        )
        return attempt_id

    def finish(
        self,
        *,
        attempt_id: uuid.UUID,
        status: JobStatus,
        now: datetime,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        stmt = (
            update(JobAttempt)
            .where(JobAttempt.id == attempt_id)
            .values(status=status.value, completed_at=now, error_code=error_code, error_message=error_message)
        )
        self._session.execute(stmt)
