from httpx import AsyncClient


async def _submit(client: AsyncClient, **overrides) -> str:
    payload = {"type": "report", "payload": {"pages": 1}}
    payload.update(overrides)
    response = await client.post("/jobs", json=payload)
    return response.json()["job_id"]


async def test_list_pagination_covers_all_without_overlap(client) -> None:
    total = 25
    page_size = 10
    for _ in range(total):
        await _submit(client)

    collected: list[dict] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, object] = {"limit": page_size}
        if cursor is not None:
            params["cursor"] = cursor
        body = (await client.get("/jobs", params=params)).json()
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


async def test_invalid_cursor_returns_400(client) -> None:
    response = await client.get("/jobs", params={"cursor": "not-a-valid-cursor"})
    assert response.status_code == 400


async def test_filter_by_status(client) -> None:
    await _submit(client)
    pending = (await client.get("/jobs", params={"status": "pending"})).json()
    assert pending["items"]
    assert all(job["status"] == "pending" for job in pending["items"])
    succeeded = (await client.get("/jobs", params={"status": "succeeded"})).json()
    assert succeeded["items"] == []


async def test_filter_by_type(client) -> None:
    await _submit(client, type="report")
    await _submit(client, type="sleep", payload={"duration_seconds": 1, "steps": 1})
    body = (await client.get("/jobs", params={"type": "sleep"})).json()
    assert body["items"]
    assert all(job["type"] == "sleep" for job in body["items"])
