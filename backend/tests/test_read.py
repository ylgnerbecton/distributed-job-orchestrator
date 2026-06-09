import uuid


def test_get_job_returns_full_record(client) -> None:
    job_id = client.post("/jobs", json={"type": "report", "payload": {"pages": 2}}).get_json()["job_id"]
    body = client.get(f"/jobs/{job_id}").get_json()
    assert body["job_id"] == job_id
    assert body["type"] == "report"
    assert body["status"] == "pending"
    assert body["max_attempts"] >= 1
    assert body["result"] is None


def test_get_job_other_user_returns_404(client) -> None:
    job_id = client.post("/jobs", json={"type": "report"}, headers={"X-User-Id": "alice"}).get_json()["job_id"]
    assert client.get(f"/jobs/{job_id}", headers={"X-User-Id": "bob"}).status_code == 404


def test_get_missing_job_returns_404(client) -> None:
    assert client.get(f"/jobs/{uuid.uuid4()}").status_code == 404


def test_summary_counts_by_status(client) -> None:
    for _ in range(3):
        client.post("/jobs", json={"type": "report"})
    body = client.get("/jobs/summary").get_json()
    assert body["total"] == 3
    assert body["counts"].get("pending") == 3


def test_events_include_submitted(client) -> None:
    job_id = client.post("/jobs", json={"type": "report"}).get_json()["job_id"]
    body = client.get(f"/jobs/{job_id}/events").get_json()
    assert "submitted" in [event["event_type"] for event in body["items"]]


def test_events_other_user_returns_404(client) -> None:
    job_id = client.post("/jobs", json={"type": "report"}, headers={"X-User-Id": "alice"}).get_json()["job_id"]
    assert client.get(f"/jobs/{job_id}/events", headers={"X-User-Id": "bob"}).status_code == 404
