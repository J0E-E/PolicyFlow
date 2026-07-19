"""End-to-end endpoint proof for P2.4 Epic 10 — the agent task queue.

Drives `GET /api/tasks` and `POST /api/tasks/{id}/complete` over the real DB-backed
client (the shared `seeded` + `db_client` substrate), the same shape
`test_anniversary_sweep_endpoint` uses. The queue reads and completes the existing
polymorphic `Task` entity, surfacing the seeded baseline `note` tasks, live-session
conversion note-tasks, and the `renewal_review` tasks the sweeps create.

Seed facts (P2.4 Epic 5): Sunshine seeds two baseline `note` tasks (`demo_session_id
IS NULL`, `status='open'`) split `agent.one` / `agent.two`, and `agent.one` owns the
sole Sunshine MA policy — so an AEP sweep's `renewal_review` task is assigned
`agent.one`.

`pytest.ini` sets `asyncio_mode = auto`, so these async tests carry no
`@pytest.mark.asyncio` decorator. The `seeded` / `db_client` / `login_as` fixtures come
from `test_endpoints_db.py`, the `assume` helper + `DEMO_SESSION_COOKIE_NAME` from the
demo suite, and `cleanup_committed_renewals` from `conftest.py`. Tests that insert
session-scoped tasks directly use the local `cleanup_inserted_tasks` teardown.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.demo.session import DEMO_SESSION_COOKIE_NAME
from app.models.user import Role
from app.tenancy.registry import FLORIDA, SUNSHINE

from .test_demo_assume_persona import assume
from .test_endpoints_db import (  # noqa: F401 — `seeded` fixture is used by name
    login_as,
    seeded,
)

AGENT_ONE_USERNAME = f"agent.one@{SUNSHINE.email_domain}"
AGENT_TWO_USERNAME = f"agent.two@{SUNSHINE.email_domain}"

AGENT_ONE_NOTE_BODY = "Follow up on Margaret's Medicare Advantage plan questions."
AGENT_TWO_NOTE_BODY = "Confirm the supplement premium payment method."


# --- Direct-DB helpers (a fresh session; the endpoint's write already committed) ----


def _session_factory(database_engine):
    return async_sessionmaker(database_engine, expire_on_commit=False)


def _caller_session_id(db_client) -> uuid.UUID:
    """Read the raw demo-session UUID the `assume` dance set on the client cookie."""
    return uuid.UUID(db_client.cookies[DEMO_SESSION_COOKIE_NAME])


async def _login_username(client, username: str):
    """Log in via plain `/api/auth/login` (no demo session minted) for one username."""
    return await client.post(
        "/api/auth/login",
        json={"username": username, "password": settings.seed_user_password},
    )


async def _user_id(database_engine, username: str) -> uuid.UUID:
    """Resolve a seeded user's id from `platform.users`."""
    async with _session_factory(database_engine)() as session:
        return (
            await session.execute(
                text("SELECT id FROM platform.users WHERE username = :username"),
                {"username": username},
            )
        ).scalar_one()


async def _baseline_note_task_id(database_engine, assignee_username: str) -> uuid.UUID:
    """Return the id of the seeded baseline (`demo_session_id IS NULL`) note-task."""
    async with _session_factory(database_engine)() as session:
        return (
            await session.execute(
                text(
                    f"SELECT id FROM {SUNSHINE.schema_name}.tasks "
                    "WHERE task_type = 'note' AND demo_session_id IS NULL "
                    "AND assignee_username = :username"
                ),
                {"username": assignee_username},
            )
        ).scalar_one()


async def _insert_task(
    database_engine,
    *,
    assignee_user_id: uuid.UUID,
    assignee_username: str,
    demo_session_id: uuid.UUID | None,
    status: str | None,
    due_date: datetime | None,
    body: str,
    task_type: str = "note",
) -> uuid.UUID:
    """Insert one Sunshine task directly and commit; return its id.

    The faithful stand-in for a live-session conversion note-task / a foreign task,
    without driving the whole conversion flow. Committed on its own session so the
    request path (a separate transaction) sees it.
    """
    task_id = uuid.uuid4()
    async with _session_factory(database_engine)() as session:
        await session.execute(
            text(
                f"INSERT INTO {SUNSHINE.schema_name}.tasks "
                "(id, related_entity_type, related_entity_id, task_type, body, "
                "assignee_user_id, assignee_username, due_date, status, "
                "correlation_id, demo_session_id) "
                "VALUES (:id, 'contact', :related_entity_id, :task_type, :body, "
                ":assignee_user_id, :assignee_username, :due_date, :status, "
                ":correlation_id, :demo_session_id)"
            ),
            {
                "id": task_id,
                "related_entity_id": uuid.uuid4(),
                "task_type": task_type,
                "body": body,
                "assignee_user_id": assignee_user_id,
                "assignee_username": assignee_username,
                "due_date": due_date,
                "status": status,
                "correlation_id": uuid.uuid4(),
                "demo_session_id": demo_session_id,
            },
        )
        await session.commit()
    return task_id


async def _task_status(database_engine, task_id: uuid.UUID) -> str | None:
    """Read one Sunshine task's committed `status` through a fresh session."""
    async with _session_factory(database_engine)() as session:
        return (
            await session.execute(
                text(
                    f"SELECT status FROM {SUNSHINE.schema_name}.tasks WHERE id = :id"
                ),
                {"id": task_id},
            )
        ).scalar_one()


@pytest_asyncio.fixture
async def cleanup_inserted_tasks(database_engine):
    """Delete every session-scoped `note` task a test inserted directly.

    The tests that prove the NULL-status / foreign-session / ordering paths insert
    `note` tasks carrying a non-null `demo_session_id` straight into the shared
    container (the seed's own note-tasks are all `demo_session_id IS NULL`, so this
    predicate never touches them). Renewal tasks a sweep commits are cleared by the
    separate `cleanup_committed_renewals`. Clearing across both schemas at teardown
    keeps the shared container clean for later tests' task counts.
    """
    yield
    session_factory = _session_factory(database_engine)
    async with session_factory() as session:
        for tenant in (SUNSHINE, FLORIDA):
            await session.execute(
                text(
                    f"DELETE FROM {tenant.schema_name}.tasks "
                    "WHERE task_type = 'note' AND demo_session_id IS NOT NULL"
                )
            )
        await session.commit()


def _bodies(response) -> list[str]:
    return [task["body"] for task in response.json()["tasks"]]


# --- GET /api/tasks: role-scoped visibility -----------------------------------


async def test_agent_sees_own_baseline_note_task_not_another_agents(
    seeded, db_client  # noqa: F811
):
    """An Agent's queue holds their own baseline note-task, never another agent's."""
    assert (await _login_username(db_client, AGENT_ONE_USERNAME)).status_code == 200

    response = await db_client.get("/api/tasks")

    assert response.status_code == 200
    bodies = _bodies(response)
    assert AGENT_ONE_NOTE_BODY in bodies
    assert AGENT_TWO_NOTE_BODY not in bodies


@pytest.mark.parametrize("role", [Role.TENANT_ADMIN, Role.READ_ONLY])
async def test_tenant_admin_and_read_only_see_all_tasks(
    seeded, db_client, role  # noqa: F811
):
    """Tenant Admin and Read-Only see every task, both agents' — no capability gate."""
    assert (await login_as(db_client, role)).status_code == 200

    response = await db_client.get("/api/tasks")

    assert response.status_code == 200
    bodies = _bodies(response)
    assert AGENT_ONE_NOTE_BODY in bodies
    assert AGENT_TWO_NOTE_BODY in bodies


async def test_assignee_filter_narrows_the_all_tasks_view(
    seeded, db_client  # noqa: F811
):
    """`?assignee=` narrows a Tenant Admin's all-tasks view to one assignee."""
    assert (await login_as(db_client, Role.TENANT_ADMIN)).status_code == 200

    response = await db_client.get(
        "/api/tasks", params={"assignee": AGENT_TWO_USERNAME}
    )

    assert response.status_code == 200
    bodies = _bodies(response)
    assert AGENT_TWO_NOTE_BODY in bodies
    assert AGENT_ONE_NOTE_BODY not in bodies


async def test_live_session_conversion_note_with_null_status_still_lists(
    seeded, db_client, container_keys_session_factory, database_engine,  # noqa: F811
    cleanup_inserted_tasks,
):
    """A session-owned note-task with `status = NULL` still lists.

    Proves the non-completed filter is `IS DISTINCT FROM 'completed'`: a plain
    `<> 'completed'` would drop the NULL-status row (a live-session conversion
    note-task carries no status). Inserts one directly under the caller's session.
    """
    assert (
        await assume(db_client, tenant_slug=SUNSHINE.slug, role=Role.AGENT)
    ).status_code == 200
    session_id = _caller_session_id(db_client)
    agent_one_id = await _user_id(database_engine, AGENT_ONE_USERNAME)

    await _insert_task(
        database_engine,
        assignee_user_id=agent_one_id,
        assignee_username=AGENT_ONE_USERNAME,
        demo_session_id=session_id,
        status=None,
        due_date=None,
        body="Live-session conversion note with no status",
    )

    response = await db_client.get("/api/tasks")

    assert response.status_code == 200
    listed = next(
        task
        for task in response.json()["tasks"]
        if task["body"] == "Live-session conversion note with no status"
    )
    assert listed["status"] is None
    assert listed["is_overdue"] is False


async def test_ordering_soonest_due_first_and_is_overdue_flag(
    seeded, db_client, container_keys_session_factory, database_engine,  # noqa: F811
    cleanup_inserted_tasks,
):
    """Tasks order by due date ascending (overdue first), nulls last; `is_overdue` set."""
    assert (
        await assume(db_client, tenant_slug=SUNSHINE.slug, role=Role.AGENT)
    ).status_code == 200
    session_id = _caller_session_id(db_client)
    agent_one_id = await _user_id(database_engine, AGENT_ONE_USERNAME)
    now = datetime.now(timezone.utc)

    await _insert_task(
        database_engine,
        assignee_user_id=agent_one_id,
        assignee_username=AGENT_ONE_USERNAME,
        demo_session_id=session_id,
        status="open",
        due_date=now + timedelta(days=5),
        body="FUTURE due task",
    )
    await _insert_task(
        database_engine,
        assignee_user_id=agent_one_id,
        assignee_username=AGENT_ONE_USERNAME,
        demo_session_id=session_id,
        status="open",
        due_date=now - timedelta(days=5),
        body="OVERDUE task",
    )

    response = await db_client.get("/api/tasks")

    assert response.status_code == 200
    tasks = response.json()["tasks"]
    rows = {task["body"]: task for task in tasks}
    # Overdue (past due) sorts before the future-due task, which sorts before the
    # null-due baseline note-task.
    order = [task["body"] for task in tasks]
    assert order.index("OVERDUE task") < order.index("FUTURE due task")
    assert order.index("FUTURE due task") < order.index(AGENT_ONE_NOTE_BODY)
    assert rows["OVERDUE task"]["is_overdue"] is True
    assert rows["FUTURE due task"]["is_overdue"] is False
    assert rows[AGENT_ONE_NOTE_BODY]["is_overdue"] is False


# --- POST /api/tasks/{id}/complete --------------------------------------------


async def test_complete_session_owned_renewal_task_happy_path(
    seeded, db_client, container_keys_session_factory, database_engine,  # noqa: F811
    cleanup_committed_renewals,
):
    """An Agent completes their own session-owned renewal task; it commits `completed`.

    Runs an AEP sweep first (as Platform Admin, reusing the Agent's demo session) to
    mint a `renewal_review` task owned by `agent.one`, then re-assumes `agent.one` and
    completes it. The completion commits, so `cleanup_committed_renewals` clears it.
    """
    assert (
        await assume(db_client, tenant_slug=SUNSHINE.slug, role=Role.AGENT)
    ).status_code == 200
    assert (
        await assume(db_client, tenant_slug=SUNSHINE.slug, role=Role.PLATFORM_ADMIN)
    ).status_code == 200

    sweep = await db_client.post("/api/renewals/aep-sweep")
    assert sweep.status_code == 200
    assert sweep.json() == {"generated": 1, "skipped": 0}

    # Re-assume the owning Agent (agent.one) in the same demo session to complete it.
    assert (
        await assume(db_client, tenant_slug=SUNSHINE.slug, role=Role.AGENT)
    ).status_code == 200

    queue = await db_client.get("/api/tasks")
    assert queue.status_code == 200
    renewal_task = next(
        task
        for task in queue.json()["tasks"]
        if task["task_type"] == "renewal_review"
    )
    assert renewal_task["status"] == "open"

    completed = await db_client.post(f"/api/tasks/{renewal_task['id']}/complete")
    assert completed.status_code == 200
    assert completed.json()["task"]["status"] == "completed"

    # The write committed on block exit, and a completed task drops out of the queue.
    assert await _task_status(
        database_engine, uuid.UUID(renewal_task["id"])
    ) == "completed"
    requeried = await db_client.get("/api/tasks")
    assert renewal_task["id"] not in [
        task["id"] for task in requeried.json()["tasks"]
    ]


async def test_read_only_cannot_complete_a_task(seeded, db_client):  # noqa: F811
    """Read-Only lacks `CREATE_EDIT_RECORDS` → 403 before the handler even loads."""
    assert (await login_as(db_client, Role.READ_ONLY)).status_code == 200

    response = await db_client.post(f"/api/tasks/{uuid.uuid4()}/complete")

    assert response.status_code == 403
    assert response.json() == {"detail": "insufficient permissions"}


async def test_agent_completing_another_agents_task_is_403(
    seeded, db_client, database_engine  # noqa: F811
):
    """An Agent completing a task assigned to a different agent → 403.

    `agent.two` (plain login, no demo session) tries to complete `agent.one`'s baseline
    note-task: both the caller session and the seed task's session are null, so the
    write-isolation guard passes and the holder guard fires the 403.
    """
    assert (await _login_username(db_client, AGENT_TWO_USERNAME)).status_code == 200
    task_id = await _baseline_note_task_id(database_engine, AGENT_ONE_USERNAME)

    response = await db_client.post(f"/api/tasks/{task_id}/complete")

    assert response.status_code == 403


async def test_completing_baseline_seed_task_in_a_live_session_is_409(
    seeded, db_client, container_keys_session_factory, database_engine  # noqa: F811
):
    """Completing a baseline (`demo_session_id IS NULL`) seed task in a live session → 409."""
    assert (
        await assume(db_client, tenant_slug=SUNSHINE.slug, role=Role.AGENT)
    ).status_code == 200
    task_id = await _baseline_note_task_id(database_engine, AGENT_ONE_USERNAME)

    response = await db_client.post(f"/api/tasks/{task_id}/complete")

    assert response.status_code == 409
    assert response.json() == {"detail": "seed tasks cannot be modified"}


async def test_completing_a_foreign_session_task_is_404(
    seeded, db_client, container_keys_session_factory, database_engine,  # noqa: F811
    cleanup_inserted_tasks,
):
    """A task owned by another demo session → 404 (indistinguishable from not-found)."""
    assert (
        await assume(db_client, tenant_slug=SUNSHINE.slug, role=Role.AGENT)
    ).status_code == 200
    agent_one_id = await _user_id(database_engine, AGENT_ONE_USERNAME)
    foreign_task_id = await _insert_task(
        database_engine,
        assignee_user_id=agent_one_id,
        assignee_username=AGENT_ONE_USERNAME,
        demo_session_id=uuid.uuid4(),  # a different session
        status="open",
        due_date=None,
        body="A task owned by a foreign session",
    )

    response = await db_client.post(f"/api/tasks/{foreign_task_id}/complete")

    assert response.status_code == 404
    assert response.json() == {"detail": "task not found"}


async def test_completing_an_unknown_task_is_404(seeded, db_client):  # noqa: F811
    """An unknown task id → 404."""
    assert (await _login_username(db_client, AGENT_ONE_USERNAME)).status_code == 200

    response = await db_client.post(f"/api/tasks/{uuid.uuid4()}/complete")

    assert response.status_code == 404
    assert response.json() == {"detail": "task not found"}
