import signal
import threading

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import session_factory
from app.queue.redis_queue import create_queue
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
        interval_seconds: float,
        batch_size: int,
    ) -> None:
        self._dispatch = dispatch
        self._retry = retry
        self._lease = lease
        self._expiry = expiry
        self._notifications = notifications
        self._interval_seconds = interval_seconds
        self._batch_size = batch_size
        self._stop_event = threading.Event()

    def request_stop(self, *_args: object) -> None:
        self._stop_event.set()

    def run(self) -> None:
        _logger.info("scheduler.started")
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception as error:
                _logger.error("scheduler.tick_failed", error=str(error))
            self._stop_event.wait(self._interval_seconds)
        _logger.info("scheduler.stopped")

    def tick(self) -> None:
        self._dispatch.dispatch_pending(self._batch_size)
        self._retry.promote_due(self._batch_size)
        self._lease.reap_expired(self._batch_size)
        self._dispatch.redeliver_stuck(self._batch_size)
        self._expiry.expire_stale(self._batch_size)
        self._notifications.dispatch_due(self._batch_size)


def build_scheduler(settings: Settings) -> Scheduler:
    queue = create_queue()
    return Scheduler(
        dispatch=DispatchService(session_factory, queue, settings),
        retry=RetryService(session_factory, queue),
        lease=LeaseService(session_factory, queue),
        expiry=ExpiryService(session_factory, settings),
        notifications=NotificationDeliveryService(session_factory, settings),
        interval_seconds=settings.scheduler_interval_seconds,
        batch_size=settings.scheduler_batch_size,
    )


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    scheduler = build_scheduler(settings)
    signal.signal(signal.SIGINT, scheduler.request_stop)
    signal.signal(signal.SIGTERM, scheduler.request_stop)
    scheduler.run()


if __name__ == "__main__":
    main()
