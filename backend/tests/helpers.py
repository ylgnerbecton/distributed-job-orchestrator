import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.ids import generate_uuid7
from app.db.models import Job
from app.domain.enums import JobPriority, JobStatus, JobType


async def make_job(session_factory: async_sessionmaker[AsyncSession], **overrides: Any) -> uuid.UUID:
    now = datetime.now(timezone.utc)
    values: dict[str, Any] = {
        "id": generate_uuid7(),
        "user_id": "demo-user",
        "type": JobType.FLAKY.value,
        "status": JobStatus.QUEUED.value,
        "priority": JobPriority.NORMAL.value,
        "payload": {"fail_times": 0},
        "progress": 0,
        "attempts": 0,
        "max_attempts": 5,
        "created_at": now,
        "queued_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    job = Job(**values)
    async with session_factory() as session, session.begin():
        session.add(job)
    return job.id


async def get_job(session_factory: async_sessionmaker[AsyncSession], job_id: uuid.UUID) -> Job:
    async with session_factory() as session, session.begin():
        return await session.get(Job, job_id)


async def set_job_columns(session_factory: async_sessionmaker[AsyncSession], job_id: uuid.UUID, **values: Any) -> None:
    async with session_factory() as session, session.begin():
        await session.execute(update(Job).where(Job.id == job_id).values(**values))


def past(seconds: int = 120) -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=seconds)
