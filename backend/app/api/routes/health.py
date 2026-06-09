from fastapi import APIRouter, Depends
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_queue
from app.queue.redis_queue import JobQueue
from app.schemas.common import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(
    session: AsyncSession = Depends(get_db),
    queue: JobQueue = Depends(get_queue),
) -> HealthResponse:
    database = "ok"
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        database = "down"
    queue_status = "ok"
    try:
        if not await queue.ping():
            queue_status = "down"
    except RedisError:
        queue_status = "down"
    return HealthResponse(status="ok", database=database, queue=queue_status)
