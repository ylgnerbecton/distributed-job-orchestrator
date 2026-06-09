import uuid

from helpers import get_job, make_job, set_job_columns
from sqlalchemy import func, select

from app.core.clock import now as clock_now
from app.core.config import get_settings
from app.db.models import NotificationOutbox
from app.domain.enums import JobStatus, JobType
from app.services.job_execution_service import JobExecutionService

_SETTINGS = get_settings()
_WORKER_ID = "test-worker"


async def test_cancel_queued_job_returns_200_cancelled(client) -> None:
    job_id = (await client.post("/jobs", json={"type": "report"})).json()["job_id"]
    response = await client.post(f"/jobs/{job_id}/cancel", json={"reason": "changed my mind"})
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


async def test_cancel_running_job_returns_202_cancelling(client, session_factory) -> None:
    job_id = await make_job(
        session_factory, status=JobStatus.RUNNING.value, locked_by="worker-1", lock_expires_at=clock_now()
    )
    response = await client.post(f"/jobs/{job_id}/cancel", json={"reason": "stop"})
    assert response.status_code == 202
    assert response.json()["status"] == "cancelling"
    job = await get_job(session_factory, job_id)
    assert job.status == JobStatus.CANCELLING.value
    assert job.cancellation_requested_at is not None


async def test_cancel_terminal_job_returns_409(client, session_factory) -> None:
    job_id = await make_job(session_factory, status=JobStatus.SUCCEEDED.value, completed_at=clock_now())
    assert (await client.post(f"/jobs/{job_id}/cancel", json={})).status_code == 409


async def test_cancel_missing_job_returns_404(client) -> None:
    assert (await client.post(f"/jobs/{uuid.uuid4()}/cancel", json={})).status_code == 404


async def test_cancel_other_user_job_returns_404(client, session_factory) -> None:
    job_id = await make_job(session_factory, user_id="alice", status=JobStatus.QUEUED.value)
    assert (await client.post(f"/jobs/{job_id}/cancel", json={}, headers={"X-User-Id": "bob"})).status_code == 404


async def test_cooperative_cancellation_finalizes_cancelled(session_factory, queue, session) -> None:
    job_id = await make_job(session_factory, type=JobType.SLEEP.value, payload={"duration_seconds": 1, "steps": 5})
    state = {"requested": False}

    async def cancelling_sleep(_seconds: float) -> None:
        if not state["requested"]:
            state["requested"] = True
            await set_job_columns(
                session_factory,
                job_id,
                status=JobStatus.CANCELLING.value,
                cancellation_requested_at=clock_now(),
            )

    service = JobExecutionService(session_factory, queue, _SETTINGS, worker_id=_WORKER_ID, sleep=cancelling_sleep)
    await service.execute(job_id)

    job = await get_job(session_factory, job_id)
    assert job.status == JobStatus.CANCELLED.value
    cancelled = (
        await session.execute(
            select(func.count())
            .select_from(NotificationOutbox)
            .where(NotificationOutbox.job_id == job_id, NotificationOutbox.event_type == "cancelled")
        )
    ).scalar_one()
    assert cancelled == 1
