"""The `tasks` package — the agent task-queue HTTP surface for P2.4 Epic 10.

`router.py` mounts `GET /api/tasks` (the role-scoped, session-scoped queue read)
and `POST /api/tasks/{id}/complete` (the guarded two-state open→completed write)
over the existing polymorphic `Task` entity (`app.models.task`). It surfaces both
the seeded/conversion `note` tasks and the `renewal_review` tasks the sweeps create,
adding no new persistence of its own.
"""
