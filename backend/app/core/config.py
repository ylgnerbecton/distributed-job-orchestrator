from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_REPO_ROOT / ".env", _BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://orchestrator:orchestrator@localhost:5432/job_orchestrator"
    test_database_url: str = "postgresql+asyncpg://orchestrator:orchestrator@localhost:5432/job_orchestrator_test"
    redis_url: str = "redis://localhost:6379/0"
    redis_queue_namespace: str = "job_orchestrator"

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    frontend_origin: str = "http://localhost:5173"
    log_level: str = "info"

    db_pool_size: int = 20
    db_max_overflow: int = 40

    worker_concurrency: int = 4
    worker_lease_seconds: int = 60
    worker_heartbeat_seconds: int = 15
    worker_poll_timeout_seconds: int = 5
    worker_error_backoff_seconds: float = 1.0

    scheduler_interval_seconds: float = 2.0
    scheduler_batch_size: int = 100
    queue_stuck_seconds: int = 30

    job_default_max_attempts: int = 5
    job_max_payload_bytes: int = 65536
    job_queue_max_age_seconds: int = 3600
    max_in_flight_jobs_per_user: int = 200

    handler_progress_steps: int = 10
    handler_step_seconds: float = 1.0
    job_sleep_default_seconds: float = 10.0
    job_report_default_pages: int = 5
    job_llm_default_tokens: int = 200

    retry_base_seconds: float = 2.0
    retry_max_seconds: float = 1800.0
    retry_jitter_ratio: float = 0.25

    notification_max_attempts: int = 8
    notification_webhook_timeout_seconds: int = 5
    notification_signing_secret: str = "local-development-secret-change-me"

    demo_target_url: str = "http://localhost:8000"
    demo_user_id: str = "demo-user"
    demo_rounds: int = 3


@lru_cache
def get_settings() -> Settings:
    return Settings()
