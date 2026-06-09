def test_health_reports_database_and_queue(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["queue"] == "ok"
