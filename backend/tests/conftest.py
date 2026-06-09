from collections.abc import Iterator

import psycopg
import pytest
from fakeredis import FakeStrictRedis
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.models import Base
from app.main import create_app
from app.queue.redis_queue import JobQueue
from app.services.dispatch_service import DispatchService
from app.services.expiry_service import ExpiryService
from app.services.job_execution_service import JobExecutionService
from app.services.lease_service import LeaseService
from app.services.notification_service import NotificationDeliveryService
from app.services.retry_service import RetryService

settings = get_settings()
TEST_URL = settings.test_database_url
_TABLES = "notification_outbox, dispatch_outbox, job_events, job_attempts, jobs"
WORKER_ID = "test-worker"


def _ensure_database() -> None:
    url = make_url(TEST_URL)
    connection = psycopg.connect(
        host=url.host, port=url.port, user=url.username, password=url.password, dbname="postgres", autocommit=True
    )
    try:
        exists = connection.execute("SELECT 1 FROM pg_database WHERE datname = %s", (url.database,)).fetchone()
        if exists is None:
            connection.execute(f'CREATE DATABASE "{url.database}"')
    finally:
        connection.close()


@pytest.fixture(scope="session")
def engine() -> Iterator:
    _ensure_database()
    instance = create_engine(TEST_URL, pool_pre_ping=True)
    Base.metadata.drop_all(instance)
    Base.metadata.create_all(instance)
    yield instance
    instance.dispose()


@pytest.fixture
def session_factory(engine) -> sessionmaker:
    return sessionmaker(engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
def clean_tables(engine) -> None:
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE TABLE {_TABLES} RESTART IDENTITY CASCADE"))


@pytest.fixture
def session(session_factory) -> Iterator[Session]:
    instance = session_factory()
    yield instance
    instance.close()


@pytest.fixture
def queue() -> JobQueue:
    return JobQueue(FakeStrictRedis(), "test_orchestrator")


@pytest.fixture
def app(session_factory, queue):
    application = create_app(settings=settings, session_factory=session_factory, queue=queue)
    application.config.update(TESTING=True)
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def _noop_sleeper(_seconds: float) -> None:
    return None


@pytest.fixture
def execution_service(session_factory, queue) -> JobExecutionService:
    return JobExecutionService(session_factory, queue, settings, worker_id=WORKER_ID, sleeper=_noop_sleeper)


@pytest.fixture
def dispatch_service(session_factory, queue) -> DispatchService:
    return DispatchService(session_factory, queue, settings)


@pytest.fixture
def retry_service(session_factory, queue) -> RetryService:
    return RetryService(session_factory, queue)


@pytest.fixture
def lease_service(session_factory, queue) -> LeaseService:
    return LeaseService(session_factory, queue)


@pytest.fixture
def expiry_service(session_factory) -> ExpiryService:
    return ExpiryService(session_factory, settings)


@pytest.fixture
def notification_service(session_factory) -> NotificationDeliveryService:
    return NotificationDeliveryService(session_factory, settings)
