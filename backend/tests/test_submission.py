import uuid

from sqlalchemy import func, select

from app.db.models import DispatchOutbox, Job, JobEvent


def test_submit_returns_202_with_status_url(client) -> None:
    response = client.post("/jobs", json={"type": "sleep", "payload": {"duration_seconds": 5, "steps": 5}})
    assert response.status_code == 202
    body = response.get_json()
    assert uuid.UUID(body["job_id"])
    assert body["status"] == "pending"
    assert body["status_url"] == f"/jobs/{body['job_id']}"


def test_submit_persists_job_outbox_and_event(client, session) -> None:
    job_id = uuid.UUID(client.post("/jobs", json={"type": "report", "payload": {"pages": 3}}).get_json()["job_id"])
    job = session.get(Job, job_id)
    assert job.status == "pending"
    assert job.payload == {"pages": 3}
    outbox_count = session.execute(
        select(func.count()).select_from(DispatchOutbox).where(DispatchOutbox.job_id == job_id)
    ).scalar_one()
    assert outbox_count == 1
    event_types = session.execute(select(JobEvent.event_type).where(JobEvent.job_id == job_id)).scalars().all()
    assert "submitted" in event_types


def test_submit_unknown_type_returns_422(client) -> None:
    assert client.post("/jobs", json={"type": "does_not_exist"}).status_code == 422


def test_submit_invalid_payload_param_returns_422(client) -> None:
    response = client.post("/jobs", json={"type": "sleep", "payload": {"steps": 0}})
    assert response.status_code == 422


def test_submit_payload_too_large_returns_413(client) -> None:
    response = client.post("/jobs", json={"type": "report", "payload": {"blob": "x" * 70000}})
    assert response.status_code == 413


def test_idempotency_key_returns_same_job(client) -> None:
    headers = {"Idempotency-Key": "idem-123"}
    first = client.post("/jobs", json={"type": "report", "payload": {"pages": 2}}, headers=headers)
    second = client.post("/jobs", json={"type": "report", "payload": {"pages": 2}}, headers=headers)
    assert first.get_json()["job_id"] == second.get_json()["job_id"]


def test_idempotency_key_creates_single_row(client, session) -> None:
    headers = {"Idempotency-Key": "idem-unique"}
    for _ in range(3):
        client.post("/jobs", json={"type": "report"}, headers=headers)
    count = session.execute(
        select(func.count()).select_from(Job).where(Job.idempotency_key == "idem-unique")
    ).scalar_one()
    assert count == 1
