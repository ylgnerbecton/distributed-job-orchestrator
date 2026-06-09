import asyncio
import signal
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
        concurrency: int,
        worker_id: str,
    ) -> None:
        self._queue = queue
        self._execution_service = execution_service
        self._poll_timeout_seconds = poll_timeout_seconds
        self._error_backoff_seconds = error_backoff_seconds
        self._concurrency = concurrency
        self._worker_id = worker_id
        self._stop_event = asyncio.Event()

    def request_stop(self) -> None:
        self._stop_event.set()

    async def run(self) -> None:
        _logger.info("worker.started", worker_id=self._worker_id, concurrency=self._concurrency)
        consumers = [asyncio.create_task(self._consume_loop()) for _ in range(self._concurrency)]
        await self._stop_event.wait()
        for task in consumers:
            task.cancel()
        await asyncio.gather(*consumers, return_exceptions=True)
        await self._queue.close()
        _logger.info("worker.stopped", worker_id=self._worker_id)

    async def _consume_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                job_id = await self._queue.consume(self._poll_timeout_seconds)
            except RedisError as error:
                _logger.warning("worker.queue_unavailable", error=str(error))
                await asyncio.sleep(self._error_backoff_seconds)
                continue
            if job_id is None:
                continue
            await self._process(job_id)

    async def _process(self, job_id: str) -> None:
        try:
            await self._execution_service.execute(uuid.UUID(job_id))
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
        settings.worker_concurrency,
        worker_id,
    )


async def _run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    worker = build_worker(settings)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, worker.request_stop)
    await worker.run()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
