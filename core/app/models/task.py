"""The `Task` ORM model — a polymorphic follow-up shell (P2.1).

Like ``Lead`` / ``PiiDemoRecord``, this model is **deliberately schema-less**: it
names the table ``tasks`` but binds it to no schema, so it resolves against the
active ``search_path`` and the one class serves every tenant. The table exists only
inside each tenant schema (migration ``0015``) and is excluded from ``alembic
check``, so the migration owns it and this model mirrors its columns.

A Task is a polymorphic shell: ``related_entity_type`` / ``related_entity_id`` point
it at whatever it hangs off (a ``'contact'`` for the conversion note-task), and
``task_type`` names its kind (``'note'``). The conversion action creates one only
when the lead has notes, carrying ``lead.notes`` verbatim into the plaintext
``body`` and assigning it to the converting agent. ``due_date`` and ``status`` are
nullable placeholders P2.4 fills; ``correlation_id`` / ``demo_session_id`` are the
usual trace columns. There is no ``task.created`` event — the BRD announces only the
four conversion event kinds.
"""

import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class Task(Base):
    """A single task, resolved via `search_path` into the active tenant schema."""

    __tablename__ = "tasks"
    # No schema binding (like `Lead`): resolved against the active `search_path`.
    # Surrogate uuid PK generated app-side. Polymorphic via
    # `related_entity_type` / `related_entity_id`. `pk_tasks` from `app.db`.

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    related_entity_type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    related_entity_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    task_type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    body: Mapped[str] = mapped_column(sa.Text, nullable=False)
    assignee_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.Uuid, nullable=True
    )
    assignee_username: Mapped[Optional[str]] = mapped_column(
        sa.Text, nullable=True
    )
    due_date: Mapped[Optional[datetime]] = mapped_column(
        sa.TIMESTAMP(timezone=True), nullable=True
    )
    status: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    correlation_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    demo_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.Uuid, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )
