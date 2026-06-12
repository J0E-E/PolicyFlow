"""Backend tests for the `/api/health` ok and degraded paths.

These are the first real health-endpoint tests. They monkeypatch the seam from
Epic 2 — `app.health.check_database` and `app.health.check_broker` — which
`get_health` looks up by module-level name at call time, so replacing them
swaps the probe results deterministically with no live Postgres/RabbitMQ.

Coverage: the all-ok path plus all three degraded combinations (db down,
broker down, both down).
"""

from app.config import settings
from app.health import CHECK_OK, CHECK_ERROR


def make_check_returning(status_to_return: str):
    """Build an async stub standing in for a real `check_*` probe.

    The real checks are `async` and return `CHECK_OK` / `CHECK_ERROR`, so the
    stub is an async function yielding the given fixed status.
    """

    async def check_stub() -> str:
        return status_to_return

    return check_stub


async def test_health_returns_ok_when_all_checks_pass(client, monkeypatch):
    """Both probes ok -> 200, status "ok", both checks "ok", version reported."""
    monkeypatch.setattr("app.health.check_database", make_check_returning(CHECK_OK))
    monkeypatch.setattr("app.health.check_broker", make_check_returning(CHECK_OK))

    response = await client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"] == {"db": CHECK_OK, "broker": CHECK_OK}
    assert body["version"] == settings.app_version


async def test_health_degraded_when_database_down(client, monkeypatch):
    """DB probe error, broker ok -> 503, "degraded", db "error" / broker "ok"."""
    monkeypatch.setattr("app.health.check_database", make_check_returning(CHECK_ERROR))
    monkeypatch.setattr("app.health.check_broker", make_check_returning(CHECK_OK))

    response = await client.get("/api/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"] == {"db": CHECK_ERROR, "broker": CHECK_OK}


async def test_health_degraded_when_broker_down(client, monkeypatch):
    """Broker probe error, db ok -> 503, "degraded", db "ok" / broker "error"."""
    monkeypatch.setattr("app.health.check_database", make_check_returning(CHECK_OK))
    monkeypatch.setattr("app.health.check_broker", make_check_returning(CHECK_ERROR))

    response = await client.get("/api/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"] == {"db": CHECK_OK, "broker": CHECK_ERROR}


async def test_health_degraded_when_both_down(client, monkeypatch):
    """Both probes error -> 503, "degraded", both checks "error"."""
    monkeypatch.setattr("app.health.check_database", make_check_returning(CHECK_ERROR))
    monkeypatch.setattr("app.health.check_broker", make_check_returning(CHECK_ERROR))

    response = await client.get("/api/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"] == {"db": CHECK_ERROR, "broker": CHECK_ERROR}
