import uuid
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DispatchOutbox
from app.domain.enums import OutboxStatus


class DispatchOutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, job_id: uuid.UUID) -> None:
        self._session.add(DispatchOutbox(job_id=job_id, status=OutboxStatus.PENDING.value))

    async def claim_pending(self, limit: int) -> list[DispatchOutbox]:
        stmt = (
            select(DispatchOutbox)
            .where(DispatchOutbox.status == OutboxStatus.PENDING.value)
            .order_by(DispatchOutbox.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def mark_published(self, outbox_id: uuid.UUID, now: datetime) -> None:
        stmt = (
            update(DispatchOutbox)
            .where(DispatchOutbox.id == outbox_id)
            .values(status=OutboxStatus.PUBLISHED.value, published_at=now, attempts=DispatchOutbox.attempts + 1)
        )
        await self._session.execute(stmt)

    async def count_pending(self) -> int:
        stmt = (
            select(func.count()).select_from(DispatchOutbox).where(DispatchOutbox.status == OutboxStatus.PENDING.value)
        )
        return int((await self._session.execute(stmt)).scalar_one())
