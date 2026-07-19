"""The agent task-queue API — the role-scoped queue read and the complete write.

Two endpoints under `/api/tasks`, both riding `get_tenant_db` so tenant isolation is
automatic (the caller's schema scopes every query — no tenant parameter). They read
and write the existing polymorphic `Task` entity, surfacing the seeded/conversion
`note` tasks and the `renewal_review` tasks the sweeps create alike:

- **`GET /api/tasks`** — the queue: an **Agent** sees their own non-completed tasks;
  a **Tenant Admin** / **Read-Only** sees every non-completed task, optionally filtered
  by `?assignee=<username>`. Guard: `require_authenticated` (any tenant user may read —
  the opportunities-read precedent, so Read-Only reads without a capability gate). Rows
  are session-scoped (seed baseline ∪ the caller's session) and ordered soonest-due /
  overdue-first, nulls last, each carrying a computed `is_overdue`.
- **`POST /api/tasks/{id}/complete`** — mark one task completed (two-state, D7). Guard:
  `require_capability(CREATE_EDIT_RECORDS)` (Read-Only → 403), then the handler applies
  its guards **in order**: load / `404`, demo-session write-isolation (foreign session
  `404`, shared seed row `409`), holder (assignee or Tenant Admin) / `403`. On success it
  sets `status='completed'` and rides `get_tenant_db`'s block-exit commit (the caller is a
  tenant user — no Platform-Admin scoped-write dance the sweeps needed). No audit record,
  no event (ADR 0006 / D7): the `status='completed'` write is the only trace.

The non-completed filter is `status IS DISTINCT FROM 'completed'`, **not** `<> 'completed'`:
conversion note-tasks carry `status = NULL` (`leads/conversion.py` never sets it), so a
plain inequality would silently hide every live-session conversion note-task.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import require_authenticated, require_capability
from ..auth.provider import Identity
from ..auth.rbac import Capability
from ..demo.session import current_demo_session
from ..models.task import Task
from ..models.user import Role
from ..tenancy.scoping import get_tenant_db

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

_COMPLETED_STATUS = "completed"


def _task_row(task: Task, *, now: datetime) -> dict:
    """Serialize one `Task` to the queue's wire row.

    `is_overdue` is a soft, read-time flag: `due_date < now` (UTC). A task with no
    `due_date` (every `note` task) is never overdue and sorts last. `status` is passed
    through verbatim — it may be `NULL` (a live-session conversion note-task) or `'open'`
    (a seeded note-task / a `renewal_review` task) or `'completed'`.
    """
    due_date = task.due_date
    is_overdue = due_date is not None and due_date < now
    return {
        "id": str(task.id),
        "task_type": task.task_type,
        "body": task.body,
        "due_date": due_date.isoformat() if due_date is not None else None,
        "is_overdue": is_overdue,
        "related_entity_type": task.related_entity_type,
        "related_entity_id": str(task.related_entity_id),
        "assignee_username": task.assignee_username,
        "status": task.status,
    }


def _scope_to_session(query, demo_session_id: uuid.UUID | None):
    """Scope a `Task` SELECT to the seed baseline plus the caller's session.

    Mirrors `opportunities.router._scope_to_session`: with a live session,
    `demo_session_id IS NULL OR demo_session_id = :session_id` (seed ∪ the caller's own
    rows); without one, just `demo_session_id IS NULL` (seed-only), so a session-less
    caller never sees a visitor's private tasks.
    """
    if demo_session_id is None:
        return query.where(Task.demo_session_id.is_(None))
    return query.where(
        Task.demo_session_id.is_(None)
        | (Task.demo_session_id == demo_session_id)
    )


async def _guard_task_for_session(
    task: Task, request: Request, db: AsyncSession
) -> uuid.UUID | None:
    """Enforce demo-session write-isolation on an already-loaded task.

    The mutation twin of `_scope_to_session`, mirroring
    `opportunities.router._guard_opportunity_for_session`: resolves the caller's demo
    session once and applies two guards in order — a task owned by **another** session is
    a `404` (indistinguishable from not-found, so a visitor can neither complete nor probe
    for another's), and a shared **seed** task (`demo_session_id IS NULL`) while the caller
    is in a live session is a `409` (a visitor must never alter a row every visitor sees).
    Returns the resolved session id.
    """
    demo_session = await current_demo_session(request, db)
    demo_session_id = demo_session.id if demo_session is not None else None

    if (
        task.demo_session_id is not None
        and task.demo_session_id != demo_session_id
    ):
        raise HTTPException(status_code=404, detail="task not found")

    if demo_session_id is not None and task.demo_session_id is None:
        raise HTTPException(status_code=409, detail="seed tasks cannot be modified")

    return demo_session_id


@router.get("")
async def list_tasks(
    request: Request,
    assignee: str | None = None,
    identity: Identity = Depends(require_authenticated),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Return the caller's non-completed task queue, soonest-due first, nulls last.

    Any authenticated tenant user may read, so the guard is `require_authenticated` (no
    capability gate — Read-Only reads, the opportunities-read precedent). There is **no
    tenant parameter** — `get_tenant_db` scopes to the caller's schema, and the inlined
    session-scope further limits rows to the shared seed baseline ∪ the caller's demo
    session.

    Role-scoping: an **Agent** sees only tasks assigned to them (`assignee_user_id ==
    caller`); a **Tenant Admin** / **Read-Only** sees every task, optionally narrowed to
    one assignee via `?assignee=<username>`. The non-completed filter is `status IS
    DISTINCT FROM 'completed'` so a conversion note-task's `NULL` status still lists.
    """
    demo_session = await current_demo_session(request, db)
    demo_session_id = demo_session.id if demo_session is not None else None

    query = _scope_to_session(
        select(Task).where(Task.status.is_distinct_from(_COMPLETED_STATUS)),
        demo_session_id,
    )

    if identity.role is Role.AGENT:
        # An Agent sees only their own queue.
        query = query.where(Task.assignee_user_id == identity.user_id)
    elif assignee is not None:
        # A Tenant Admin / Read-Only sees all, optionally narrowed to one assignee.
        query = query.where(Task.assignee_username == assignee)

    # Soonest-due first, overdue therefore first; note-tasks (null due_date) sort last.
    # `id` is a stable tiebreak so equal-due rows order deterministically.
    query = query.order_by(Task.due_date.asc().nulls_last(), Task.id.asc())
    tasks = (await db.execute(query)).scalars().all()

    now = datetime.now(timezone.utc)
    return {"tasks": [_task_row(task, now=now) for task in tasks]}


@router.post("/{task_id}/complete")
async def complete_task(
    task_id: uuid.UUID,
    request: Request,
    identity: Identity = Depends(
        require_capability(Capability.CREATE_EDIT_RECORDS)
    ),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Mark one task completed; return the updated row.

    The guard hands the route an `Identity` only when the caller holds
    `CREATE_EDIT_RECORDS` (Read-Only a 403, the anonymous caller a 401); `get_tenant_db`
    scopes to the caller's schema. The handler then guards **in order** (the
    `opportunities.change_stage` precedent):

    1. **Load** the task by id in the caller's schema; missing / cross-tenant is a `404`.
    2. **Demo-session write-isolation** — a foreign session's task is a `404`, a shared
       seed task (with a live session) a `409`.
    3. **Holder** — the assignee **or** any Tenant Admin may complete it; else `403`.

    On success `status` becomes `'completed'` and the change commits on `get_tenant_db`'s
    block exit. There is no audit record and no event (ADR 0006 / D7).
    """
    task = (
        await db.execute(select(Task).where(Task.id == task_id))
    ).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")

    # Demo-session write-isolation, before the holder guard: a foreign session's task is a
    # 404, a shared seed task a 409 (mirrors the opportunity write guard).
    await _guard_task_for_session(task, request, db)

    # Holder guard: the assignee or any Tenant Admin may complete the task.
    is_assignee = task.assignee_user_id == identity.user_id
    is_tenant_admin = identity.role is Role.TENANT_ADMIN
    if not (is_assignee or is_tenant_admin):
        raise HTTPException(
            status_code=403,
            detail="only the task's assignee or a tenant admin can complete it",
        )

    task.status = _COMPLETED_STATUS
    return {"task": _task_row(task, now=datetime.now(timezone.utc))}
