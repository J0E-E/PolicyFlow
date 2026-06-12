"""Trivial smoke test proving the backend harness is wired end-to-end.

This asserts only that pytest + asyncio + httpx + the FastAPI app are connected
and that `/api/health` is reachable (a real HTTP status code comes back). It
deliberately does NOT assert the ok vs degraded body — that is Epic 3. Without
a live Postgres/RabbitMQ the endpoint answers 503 "degraded", which is still a
valid reachable response for this reachability check.
"""


async def test_health_endpoint_is_reachable(client):
    """GET /api/health and confirm a real HTTP response comes back."""
    response = await client.get("/api/health")

    # Reachability only: any valid HTTP status proves the app responded.
    assert isinstance(response.status_code, int)
    assert 100 <= response.status_code <= 599
