import random

from app.core.config import Settings


def compute_backoff_seconds(attempt_count: int, settings: Settings) -> float:
    geometric = settings.retry_base_seconds * (2 ** max(0, attempt_count - 1))
    capped = min(geometric, settings.retry_max_seconds)
    jitter = capped * settings.retry_jitter_ratio
    return max(0.0, capped + random.uniform(-jitter, jitter))
