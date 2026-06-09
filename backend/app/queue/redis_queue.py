from redis import Redis

from app.core.config import get_settings
from app.domain.enums import JobPriority

_PRIORITY_ORDER: tuple[JobPriority, ...] = (JobPriority.HIGH, JobPriority.NORMAL, JobPriority.LOW)


class JobQueue:
    def __init__(self, client: Redis, namespace: str) -> None:
        self._client = client
        self._namespace = namespace
        self._priority_keys = [self._queue_key(priority) for priority in _PRIORITY_ORDER]
        self._dead_letter_key = f"{namespace}:dead_letter"

    def _queue_key(self, priority: JobPriority) -> str:
        return f"{self._namespace}:queue:{priority.value}"

    def publish(self, job_id: str, priority: JobPriority) -> None:
        self._client.lpush(self._queue_key(priority), job_id)

    def consume(self, timeout_seconds: int) -> str | None:
        result = self._client.brpop(self._priority_keys, timeout=timeout_seconds)
        if result is None:
            return None
        _key, value = result
        return value.decode() if isinstance(value, bytes) else str(value)

    def dead_letter(self, job_id: str) -> None:
        self._client.lpush(self._dead_letter_key, job_id)

    def depth(self) -> int:
        return sum(int(self._client.llen(key)) for key in self._priority_keys)

    def dead_letter_depth(self) -> int:
        return int(self._client.llen(self._dead_letter_key))

    def ping(self) -> bool:
        return bool(self._client.ping())


def create_redis_client(url: str) -> Redis:
    return Redis.from_url(url, socket_keepalive=True, health_check_interval=30)


def create_queue() -> JobQueue:
    settings = get_settings()
    return JobQueue(create_redis_client(settings.redis_url), settings.redis_queue_namespace)
