from submit_jobs import submit_demo_jobs

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger

_logger = get_logger()


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    total = submit_demo_jobs(settings.demo_target_url, settings.demo_user_id, 1)
    _logger.info("seed.completed", submitted=total)


if __name__ == "__main__":
    main()
