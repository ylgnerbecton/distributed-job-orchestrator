import signal
import time
import uuid

from redis.exceptions import RedisError

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import session_factory
from app.queue.redis_queue import JobQueue, create_queue
from app.services.job_execution_service import JobExecutionService
from app.workers.identity import generate_worker_id

_logger = get_logger()


class Worker:
    def __init__(
        self,
        queue: JobQueue,
        execution_service: JobExecutionService,
        poll_timeout_seconds: int,
        error_backoff_seconds: float,
        worker_id: str,
    ) -> None:
        self._queue = queue
        self._execution_service = execution_service
        self._poll_timeout_seconds = poll_timeout_seconds
        self._error_backoff_seconds = error_backoff_seconds
        self._worker_id = worker_id
        self._running = True

    def request_stop(self, *_args: object) -> None:
        self._running = False

    def run(self) -> None:
        _logger.info("worker.started", worker_id=self._worker_id)
        while self._running:
            try:
                job_id = self._queue.consume(self._poll_timeout_seconds)
            except RedisError as error:
                _logger.warning("worker.queue_unavailable", error=str(error))
                time.sleep(self._error_backoff_seconds)
                continue
            if job_id is None:
                continue
            self._process(job_id)
        _logger.info("worker.stopped", worker_id=self._worker_id)

    def _process(self, job_id: str) -> None:
        try:
            self._execution_service.execute(uuid.UUID(job_id))
        except ValueError:
            _logger.warning("worker.invalid_job_id", value=job_id)
        except Exception as error:
            _logger.error("worker.execute_failed", job_id=job_id, error=str(error))


def build_worker(settings: Settings) -> Worker:
    queue = create_queue()
    worker_id = generate_worker_id()
    execution_service = JobExecutionService(session_factory, queue, settings, worker_id)
    return Worker(
        queue,
        execution_service,
        settings.worker_poll_timeout_seconds,
        settings.worker_error_backoff_seconds,
        worker_id,
    )


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    worker = build_worker(settings)
    signal.signal(signal.SIGINT, worker.request_stop)
    signal.signal(signal.SIGTERM, worker.request_stop)
    worker.run()


if __name__ == "__main__":
    main()
