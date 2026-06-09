def _submit(client, **overrides) -> str:
    payload = {"type": "report", "payload": {"pages": 1}}
    payload.update(overrides)
    return client.post("/jobs", json=payload).get_json()["job_id"]


def test_list_pagination_covers_all_without_overlap(client) -> None:
    total = 25
    page_size = 10
    for _ in range(total):
        _submit(client)

    collected: list[dict] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, object] = {"limit": page_size}
        if cursor is not None:
            params["cursor"] = cursor
        body = client.get("/jobs", query_string=params).get_json()
        collected.extend(body["items"])
        pages += 1
        if not body["has_more"]:
            assert body["next_cursor"] is None
            break
        cursor = body["next_cursor"]
        assert cursor is not None
        assert pages < total

    ids = [job["job_id"] for job in collected]
    assert len(ids) == total
    assert len(set(ids)) == total
    created_at_values = [job["created_at"] for job in collected]
    assert created_at_values == sorted(created_at_values, reverse=True)


def test_invalid_cursor_returns_400(client) -> None:
    assert client.get("/jobs", query_string={"cursor": "not-a-valid-cursor"}).status_code == 400


def test_filter_by_status(client) -> None:
    _submit(client)
    pending = client.get("/jobs", query_string={"status": "pending"}).get_json()
    assert pending["items"]
    assert all(job["status"] == "pending" for job in pending["items"])
    succeeded = client.get("/jobs", query_string={"status": "succeeded"}).get_json()
    assert succeeded["items"] == []


def test_filter_by_type(client) -> None:
    _submit(client, type="report")
    _submit(client, type="sleep", payload={"duration_seconds": 1, "steps": 1})
    body = client.get("/jobs", query_string={"type": "sleep"}).get_json()
    assert body["items"]
    assert all(job["type"] == "sleep" for job in body["items"])
