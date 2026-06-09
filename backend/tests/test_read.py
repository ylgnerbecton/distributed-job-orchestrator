import uuid


async def test_get_job_returns_full_record(client) -> None:
    job_id = (await client.post("/jobs", json={"type": "report", "payload": {"pages": 2}})).json()["job_id"]
    body = (await client.get(f"/jobs/{job_id}")).json()
    assert body["job_id"] == job_id
    assert body["type"] == "report"
    assert body["status"] == "pending"
    assert body["max_attempts"] >= 1
    assert body["result"] is None


async def test_get_job_other_user_returns_404(client) -> None:
    job_id = (await client.post("/jobs", json={"type": "report"}, headers={"X-User-Id": "alice"})).json()["job_id"]
    response = await client.get(f"/jobs/{job_id}", headers={"X-User-Id": "bob"})
    assert response.status_code == 404


async def test_get_missing_job_returns_404(client) -> None:
    assert (await client.get(f"/jobs/{uuid.uuid4()}")).status_code == 404


async def test_summary_counts_by_status(client) -> None:
    for _ in range(3):
        await client.post("/jobs", json={"type": "report"})
    body = (await client.get("/jobs/summary")).json()
    assert body["total"] == 3
    assert body["counts"].get("pending") == 3


async def test_events_include_submitted(client) -> None:
    job_id = (await client.post("/jobs", json={"type": "report"})).json()["job_id"]
    body = (await client.get(f"/jobs/{job_id}/events")).json()
    assert "submitted" in [event["event_type"] for event in body["items"]]


async def test_events_other_user_returns_404(client) -> None:
    job_id = (await client.post("/jobs", json={"type": "report"}, headers={"X-User-Id": "alice"})).json()["job_id"]
    assert (await client.get(f"/jobs/{job_id}/events", headers={"X-User-Id": "bob"})).status_code == 404
