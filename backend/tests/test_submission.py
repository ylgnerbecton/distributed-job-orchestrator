import uuid

from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.models import DispatchOutbox, Job, JobEvent


async def test_submit_returns_202_with_status_url(client) -> None:
    response = await client.post("/jobs", json={"type": "sleep", "payload": {"duration_seconds": 5, "steps": 5}})
    assert response.status_code == 202
    body = response.json()
    assert uuid.UUID(body["job_id"])
    assert body["status"] == "pending"
    assert body["status_url"] == f"/jobs/{body['job_id']}"


async def test_submit_persists_job_outbox_and_event(client, session) -> None:
    response = await client.post("/jobs", json={"type": "report", "payload": {"pages": 3}})
    job_id = uuid.UUID(response.json()["job_id"])
    job = await session.get(Job, job_id)
    assert job.status == "pending"
    assert job.payload == {"pages": 3}
    outbox_count = (
        await session.execute(select(func.count()).select_from(DispatchOutbox).where(DispatchOutbox.job_id == job_id))
    ).scalar_one()
    assert outbox_count == 1
    event_types = (await session.execute(select(JobEvent.event_type).where(JobEvent.job_id == job_id))).scalars().all()
    assert "submitted" in event_types


async def test_submit_unknown_type_returns_422(client) -> None:
    response = await client.post("/jobs", json={"type": "does_not_exist"})
    assert response.status_code == 422


async def test_submit_invalid_payload_param_returns_422(client) -> None:
    response = await client.post("/jobs", json={"type": "sleep", "payload": {"steps": 0}})
    assert response.status_code == 422


async def test_submit_payload_too_large_returns_413(client) -> None:
    response = await client.post("/jobs", json={"type": "report", "payload": {"blob": "x" * 70000}})
    assert response.status_code == 413


async def test_idempotency_key_returns_same_job(client) -> None:
    headers = {"Idempotency-Key": "idem-123"}
    first = await client.post("/jobs", json={"type": "report", "payload": {"pages": 2}}, headers=headers)
    second = await client.post("/jobs", json={"type": "report", "payload": {"pages": 2}}, headers=headers)
    assert first.json()["job_id"] == second.json()["job_id"]


async def test_idempotency_key_creates_single_row(client, session) -> None:
    headers = {"Idempotency-Key": "idem-unique"}
    for _ in range(3):
        await client.post("/jobs", json={"type": "report"}, headers=headers)
    count = (
        await session.execute(select(func.count()).select_from(Job).where(Job.idempotency_key == "idem-unique"))
    ).scalar_one()
    assert count == 1


async def test_admission_control_rejects_over_quota(client, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "max_in_flight_jobs_per_user", 2)
    assert (await client.post("/jobs", json={"type": "report"})).status_code == 202
    assert (await client.post("/jobs", json={"type": "report"})).status_code == 202
    over_quota = await client.post("/jobs", json={"type": "report"})
    assert over_quota.status_code == 429
    assert "limit" in over_quota.json()["message"]
