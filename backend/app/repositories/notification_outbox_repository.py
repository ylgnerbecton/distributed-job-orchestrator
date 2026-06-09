import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import generate_uuid7
from app.db.models import NotificationOutbox
from app.domain.enums import NotificationChannel, NotificationStatus


class NotificationOutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue(
        self,
        *,
        job_id: uuid.UUID,
        user_id: str,
        channel: NotificationChannel,
        destination: str,
        event_type: str,
        payload: dict,
        dedupe_key: str,
        now: datetime,
    ) -> bool:
        stmt = (
            pg_insert(NotificationOutbox)
            .values(
                id=generate_uuid7(),
                job_id=job_id,
                user_id=user_id,
                channel=channel.value,
                destination=destination,
                event_type=event_type,
                payload=payload,
                status=NotificationStatus.PENDING.value,
                next_attempt_at=now,
                dedupe_key=dedupe_key,
            )
            .on_conflict_do_nothing(index_elements=["dedupe_key"])
            .returning(NotificationOutbox.id)
        )
        return (await self._session.execute(stmt)).first() is not None

    async def claim_due(self, now: datetime, limit: int) -> list[NotificationOutbox]:
        stmt = (
            select(NotificationOutbox)
            .where(
                NotificationOutbox.status == NotificationStatus.PENDING.value,
                NotificationOutbox.next_attempt_at <= now,
            )
            .order_by(NotificationOutbox.next_attempt_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def mark_sent(self, notification_id: uuid.UUID, now: datetime) -> None:
        stmt = (
            update(NotificationOutbox)
            .where(NotificationOutbox.id == notification_id)
            .values(
                status=NotificationStatus.SENT.value,
                sent_at=now,
                attempts=NotificationOutbox.attempts + 1,
                last_error=None,
            )
        )
        await self._session.execute(stmt)

    async def reschedule(self, notification_id: uuid.UUID, next_attempt_at: datetime, last_error: str) -> None:
        stmt = (
            update(NotificationOutbox)
            .where(NotificationOutbox.id == notification_id)
            .values(attempts=NotificationOutbox.attempts + 1, next_attempt_at=next_attempt_at, last_error=last_error)
        )
        await self._session.execute(stmt)

    async def mark_failed(self, notification_id: uuid.UUID, last_error: str) -> None:
        stmt = (
            update(NotificationOutbox)
            .where(NotificationOutbox.id == notification_id)
            .values(
                status=NotificationStatus.FAILED.value, attempts=NotificationOutbox.attempts + 1, last_error=last_error
            )
        )
        await self._session.execute(stmt)
