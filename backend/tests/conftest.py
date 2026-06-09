import asyncio
from collections.abc import AsyncIterator

import asyncpg
import fakeredis.aioredis
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.api.deps import get_db, get_queue
from app.core.config import get_settings
from app.db.models import Base
from app.main import app
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


async def _ensure_database() -> None:
    url = make_url(TEST_URL)
    admin = await asyncpg.connect(
        host=url.host, port=url.port, user=url.username, password=url.password, database="postgres"
    )
    try:
        exists = await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", url.database)
        if not exists:
            await admin.execute(f'CREATE DATABASE "{url.database}"')
    finally:
        await admin.close()


async def _create_schema() -> None:
    instance = create_async_engine(TEST_URL)
    async with instance.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await instance.dispose()


@pytest.fixture(scope="session", autouse=True)
def prepare_database() -> None:
    asyncio.run(_ensure_database())
    asyncio.run(_create_schema())


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    instance = create_async_engine(TEST_URL, pool_size=20, max_overflow=60, pool_pre_ping=True)
    yield instance
    await instance.dispose()


@pytest_asyncio.fixture(autouse=True)
async def clean_tables(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE TABLE {_TABLES} RESTART IDENTITY CASCADE"))


@pytest_asyncio.fixture
async def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def session(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with session_factory() as instance:
        yield instance


@pytest.fixture
def queue() -> JobQueue:
    return JobQueue(fakeredis.aioredis.FakeRedis(), "test_orchestrator")


@pytest_asyncio.fixture
async def client(session_factory: async_sessionmaker[AsyncSession], queue: JobQueue) -> AsyncIterator[AsyncClient]:
    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as instance:
            yield instance

    def override_get_queue() -> JobQueue:
        return queue

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_queue] = override_get_queue
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as instance:
        yield instance
    app.dependency_overrides.clear()


async def _noop_sleep(_seconds: float) -> None:
    return None


@pytest_asyncio.fixture
async def execution_service(session_factory: async_sessionmaker[AsyncSession], queue: JobQueue) -> JobExecutionService:
    return JobExecutionService(session_factory, queue, settings, worker_id=WORKER_ID, sleep=_noop_sleep)


@pytest_asyncio.fixture
async def dispatch_service(session_factory: async_sessionmaker[AsyncSession], queue: JobQueue) -> DispatchService:
    return DispatchService(session_factory, queue, settings)


@pytest_asyncio.fixture
async def retry_service(session_factory: async_sessionmaker[AsyncSession], queue: JobQueue) -> RetryService:
    return RetryService(session_factory, queue)


@pytest_asyncio.fixture
async def lease_service(session_factory: async_sessionmaker[AsyncSession], queue: JobQueue) -> LeaseService:
    return LeaseService(session_factory, queue)


@pytest_asyncio.fixture
async def expiry_service(session_factory: async_sessionmaker[AsyncSession]) -> ExpiryService:
    return ExpiryService(session_factory, settings)


@pytest_asyncio.fixture
async def notification_service(
    session_factory: async_sessionmaker[AsyncSession],
) -> NotificationDeliveryService:
    return NotificationDeliveryService(session_factory, settings)
