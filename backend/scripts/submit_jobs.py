import requests

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger

_logger = get_logger()


def demo_jobs() -> list[dict]:
    return [
        {"type": "sleep", "priority": "normal", "payload": {"duration_seconds": 8, "steps": 8}},
        {"type": "sleep", "priority": "high", "payload": {"duration_seconds": 5, "steps": 5}},
        {"type": "report", "priority": "normal", "payload": {"pages": 4}},
        {"type": "flaky", "priority": "normal", "payload": {"fail_times": 2}},
        {
            "type": "llm_summary",
            "priority": "high",
            "payload": {"prompt": "Summarize the quarterly earnings report", "tokens": 180},
        },
        {
            "type": "llm_summary",
            "priority": "normal",
            "payload": {"prompt": "Draft the release notes", "tokens": 120, "simulate_rate_limit": True},
        },
        {"type": "always_fail", "priority": "low", "payload": {}},
    ]


def submit_demo_jobs(target_url: str, user_id: str, rounds: int) -> int:
    submitted = 0
    for _ in range(rounds):
        for job in demo_jobs():
            response = requests.post(f"{target_url}/jobs", json=job, headers={"X-User-Id": user_id}, timeout=10)
            response.raise_for_status()
            submitted += 1
            _logger.info(
                "demo.submitted",
                job_id=response.json()["job_id"],
                type=job["type"],
                priority=job["priority"],
            )
    return submitted


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    total = submit_demo_jobs(settings.demo_target_url, settings.demo_user_id, settings.demo_rounds)
    _logger.info("demo.completed", submitted=total)


if __name__ == "__main__":
    main()
