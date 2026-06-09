import hashlib
import hmac
import json
from datetime import datetime, timedelta

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import now as clock_now
from app.core.config import Settings
from app.core.logging import get_logger
from app.db.models import Job, NotificationOutbox
from app.domain.backoff import compute_backoff_seconds
from app.domain.enums import JobEventType, JobStatus, NotificationChannel
from app.repositories.notification_outbox_repository import NotificationOutboxRepository

_logger = get_logger()


async def enqueue_terminal_notification(
    notifications: NotificationOutboxRepository,
    *,
    job: Job,
    event_type: JobEventType,
    status: JobStatus,
    result: dict | None,
    error_code: str | None,
    error_message: str | None,
    now: datetime,
) -> None:
    webhook = job.payload.get("notify_webhook") if isinstance(job.payload, dict) else None
    if webhook:
        channel = NotificationChannel.WEBHOOK
        destination = str(webhook)
    else:
        channel = NotificationChannel.LOG
        destination = job.user_id
    payload = {
        "job_id": str(job.id),
        "type": job.type,
        "status": status.value,
        "event": event_type.value,
        "result": result,
        "error_code": error_code,
        "error_message": error_message,
    }
    await notifications.enqueue(
        job_id=job.id,
        user_id=job.user_id,
        channel=channel,
        destination=destination,
        event_type=event_type.value,
        payload=payload,
        dedupe_key=f"{job.id}:{event_type.value}",
        now=now,
    )


class NotificationDeliveryService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self._session_factory = session_factory
        self._settings = settings

    async def dispatch_due(self, batch_size: int) -> int:
        async with self._session_factory() as session, session.begin():
            repository = NotificationOutboxRepository(session)
            due = await repository.claim_due(clock_now(), batch_size)
            for notification in due:
                await self._attempt(repository, notification)
            return len(due)

    async def _attempt(self, repository: NotificationOutboxRepository, notification: NotificationOutbox) -> None:
        try:
            await self._deliver(notification)
        except httpx.HTTPError as error:
            await self._on_failure(repository, notification, str(error))
            return
        await repository.mark_sent(notification.id, clock_now())

    async def _deliver(self, notification: NotificationOutbox) -> None:
        if notification.channel == NotificationChannel.WEBHOOK.value:
            await self._deliver_webhook(notification)
            return
        _logger.info(
            "notification.delivered",
            channel=notification.channel,
            destination=notification.destination,
            event_type=notification.event_type,
            job_id=str(notification.job_id),
        )

    async def _deliver_webhook(self, notification: NotificationOutbox) -> None:
        body = json.dumps(notification.payload, default=str).encode()
        signature = hmac.new(self._settings.notification_signing_secret.encode(), body, hashlib.sha256).hexdigest()
        async with httpx.AsyncClient(timeout=self._settings.notification_webhook_timeout_seconds) as client:
            response = await client.post(
                notification.destination,
                content=body,
                headers={"Content-Type": "application/json", "X-Signature-SHA256": signature},
            )
            response.raise_for_status()

    async def _on_failure(
        self, repository: NotificationOutboxRepository, notification: NotificationOutbox, message: str
    ) -> None:
        attempts = notification.attempts + 1
        if attempts >= self._settings.notification_max_attempts:
            await repository.mark_failed(notification.id, message)
            _logger.warning("notification.exhausted", job_id=str(notification.job_id), error=message)
            return
        backoff = compute_backoff_seconds(attempts, self._settings)
        await repository.reschedule(notification.id, clock_now() + timedelta(seconds=backoff), message)
