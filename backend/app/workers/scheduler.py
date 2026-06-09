import asyncio
import signal

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import session_factory
from app.queue.redis_queue import JobQueue, create_queue
from app.services.dispatch_service import DispatchService
from app.services.expiry_service import ExpiryService
from app.services.lease_service import LeaseService
from app.services.notification_service import NotificationDeliveryService
from app.services.retry_service import RetryService

_logger = get_logger()


class Scheduler:
    def __init__(
        self,
        *,
        dispatch: DispatchService,
        retry: RetryService,
        lease: LeaseService,
        expiry: ExpiryService,
        notifications: NotificationDeliveryService,
        queue: JobQueue,
        interval_seconds: float,
        batch_size: int,
    ) -> None:
        self._dispatch = dispatch
        self._retry = retry
        self._lease = lease
        self._expiry = expiry
        self._notifications = notifications
        self._queue = queue
        self._interval_seconds = interval_seconds
        self._batch_size = batch_size
        self._stop_event = asyncio.Event()

    def request_stop(self) -> None:
        self._stop_event.set()

    async def run(self) -> None:
        _logger.info("scheduler.started")
        while not self._stop_event.is_set():
            try:
                await self.tick()
            except Exception as error:
                _logger.error("scheduler.tick_failed", error=str(error))
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval_seconds)
            except asyncio.TimeoutError:
                continue
        await self._queue.close()
        _logger.info("scheduler.stopped")

    async def tick(self) -> None:
        await self._dispatch.dispatch_pending(self._batch_size)
        await self._retry.promote_due(self._batch_size)
        await self._lease.reap_expired(self._batch_size)
        await self._dispatch.redeliver_stuck(self._batch_size)
        await self._expiry.expire_stale(self._batch_size)
        await self._notifications.dispatch_due(self._batch_size)


def build_scheduler(settings: Settings) -> Scheduler:
    queue = create_queue()
    return Scheduler(
        dispatch=DispatchService(session_factory, queue, settings),
        retry=RetryService(session_factory, queue),
        lease=LeaseService(session_factory, queue),
        expiry=ExpiryService(session_factory, settings),
        notifications=NotificationDeliveryService(session_factory, settings),
        queue=queue,
        interval_seconds=settings.scheduler_interval_seconds,
        batch_size=settings.scheduler_batch_size,
    )


async def _run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    scheduler = build_scheduler(settings)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, scheduler.request_stop)
    await scheduler.run()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
