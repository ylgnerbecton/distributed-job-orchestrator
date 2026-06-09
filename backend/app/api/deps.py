from collections.abc import AsyncIterator

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import session_factory
from app.queue.redis_queue import JobQueue
from app.services.job_cancellation_service import JobCancellationService
from app.services.job_read_service import JobReadService
from app.services.job_submission_service import JobSubmissionService

_DEFAULT_USER_ID = "demo-user"


async def get_db() -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


def get_queue(request: Request) -> JobQueue:
    return request.app.state.queue


def current_user_id(x_user_id: str | None = Header(default=None)) -> str:
    return x_user_id or _DEFAULT_USER_ID


def get_submission_service(
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> JobSubmissionService:
    return JobSubmissionService(session, settings)


def get_read_service(session: AsyncSession = Depends(get_db)) -> JobReadService:
    return JobReadService(session)


def get_cancellation_service(session: AsyncSession = Depends(get_db)) -> JobCancellationService:
    return JobCancellationService(session)
