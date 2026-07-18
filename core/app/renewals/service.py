"""The renewal generation core — `generate_renewals` (P2.4 / TDD §5.4–5.5).

One sweep of one renewal rule over one tenant, in one request transaction. Given a
rule (`"aep"` / `"anniversary"`) and the caller's demo session, it finds the
session-visible **active** policies on that rule's product lines, skips any already
renewed this cycle (the idempotency key, ADR 0001), and for each remaining one
creates a **Renewal Opportunity**, a **renewal-review Task**, and **two** outbox
events — then flips a *session-owned* policy's status to *Renewal Due* (baseline
policies stay untouched; the read-time overlay handles those, ADR 0005). It returns
`{generated, skipped}`.

Like `convert_lead` / `change_opportunity_stage`, this core runs on the caller's
request session and **does not commit**: every row it writes and every event it
enqueues land or roll back together (the transactional outbox). The sweep endpoints
(Epic 6/8) own the scoped write session and the commit.

It owns the **single call to the real clock** (`datetime.now(timezone.utc).date()`,
the codebase's UTC clock convention), passing `today` down to the pure predicates in
`.rules` so those stay clock-free; the
parameter is injectable so tests pin an exact anniversary window. The renewal
opportunity's owner / contact / household are copied from the policy's **originating
opportunity** (`policy.opportunity_id`) — a policy carries no owner or household of
its own. Each renewal is a **new flow**: both events share a fresh `correlation_id`
(uuid4) with `causation_id=None`, emitted by the **system actor** (the sweep is
automation, not attributed to the triggering admin as the record's actor).
"""

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..events.catalog import EventType as EventBusEventType
from ..events.envelope import build_envelope
from ..events.outbox import enqueue_event
from ..models.opportunity import Opportunity
from ..models.policy import Policy
from ..models.task import Task
from ..tenancy.registry import TenantConfig
from .rules import (
    anniversary_within,
    next_anniversary,
    renewal_cycle_key,
    renewal_deadline,
)

__all__ = ["generate_renewals"]

# A policy is a renewal candidate while it reads active — `Active`, or already
# `Renewal Due` from a session-owned flip (its renewal still lands in the skip
# check, so a re-run counts it as skipped rather than generating a second one).
_ACTIVE_POLICY_STATUSES = ("Active", "Renewal Due")

# The literal stage / origin every renewal opportunity writes (TDD §5.4): `stage`
# starts at `New` (no state machine pulled forward) and `origin` is `renewal` — the
# value migration 0020's partial unique index guards on, so setting it is what arms
# the DB idempotency backstop (ADR 0001/0004).
_INITIAL_OPPORTUNITY_STAGE = "New"
_RENEWAL_OPPORTUNITY_ORIGIN = "renewal"

# The renewal-review Task framing (TDD §5.5): a `renewal_review` task hanging off
# the new renewal opportunity, opened for the owning agent.
_RENEWAL_TASK_TYPE = "renewal_review"
_RENEWAL_TASK_RELATED_ENTITY_TYPE = "opportunity"
_OPEN_TASK_STATUS = "open"

# The policy status transition this core may take (TDD §5.2 / ADR 0005): only a
# session-owned policy reading `Active` is written forward to `Renewal Due`.
_ACTIVE_STATUS = "Active"
_RENEWAL_DUE_STATUS = "Renewal Due"


async def generate_renewals(
    db: AsyncSession,
    tenant_config: TenantConfig,
    *,
    tenant_id: uuid.UUID,
    rule: str,
    demo_session_id: uuid.UUID,
    today: date | None = None,
) -> dict:
    """Run the ``rule`` renewal sweep over ``tenant_config``; return counts.

    Selects the session-visible active policies whose originating opportunity is on
    a ``renewal_rule == rule`` product line (baseline ∪ the caller's session), then
    for each:

    1. Filters by the rule's window — anniversary policies must fall inside
       `anniversary_within` (the rolling 60-day check); AEP takes **no** date gate
       (the on-demand button bypasses the seasonal calendar, ADR 0004).
    2. Computes the cycle key and **skips** (counting it) when a renewal opportunity
       already exists for this policy + cycle in the session (any stage — a closed
       or lost prior renewal still blocks a duplicate, ADR 0001).
    3. Otherwise creates the Renewal Opportunity + renewal-review Task + the
       `opportunity.created` and `policy.renewal_due` events (one new correlation),
       and — only for a **session-owned** `Active` policy — writes `Renewal Due`.

    Runs on the caller's request session and does **not** commit. Returns
    ``{"generated": <int>, "skipped": <int>}``. ``today`` defaults to the real
    clock; pass it to pin the anniversary window in a test.
    """
    today = today or datetime.now(timezone.utc).date()

    # The rule's product lines, straight from the trusted registry. A line's label
    # is copied into the Task body; a rule with no lines on this tenant (e.g. no
    # Medicare line) sweeps nothing.
    line_labels = {line.key: line.label for line in tenant_config.product_lines}
    rule_line_keys = [
        line.key for line in tenant_config.product_lines if line.renewal_rule == rule
    ]
    if not rule_line_keys:
        return {"generated": 0, "skipped": 0}

    candidates = (
        await db.execute(
            select(Policy, Opportunity)
            .join(Opportunity, Policy.opportunity_id == Opportunity.id)
            .where(
                Policy.status.in_(_ACTIVE_POLICY_STATUSES),
                Opportunity.product_line.in_(rule_line_keys),
                # Session-visible: the shared baseline (NULL) plus the caller's own
                # rows — the `leads.visible_to_session` shape, inlined here because
                # that helper is bound to `Lead`.
                Policy.demo_session_id.is_(None)
                | (Policy.demo_session_id == demo_session_id),
            )
            .order_by(Policy.issued_at, Policy.id)
        )
    ).all()

    generated = 0
    skipped = 0
    for policy, origin_opportunity in candidates:
        issued_on = policy.issued_at.date()

        if rule == "anniversary":
            if not anniversary_within(issued_on, today):
                continue
            anniversary_date = next_anniversary(issued_on, today)
            cycle_year = anniversary_date.year
        else:
            # AEP: no date gate, cycle keyed by the current calendar year. The
            # `anniversary_date` argument is unused for AEP; `today` is a valid
            # placeholder date to satisfy the pure predicate's signature.
            anniversary_date = today
            cycle_year = today.year

        cycle_key = renewal_cycle_key(rule, cycle_year)
        deadline = renewal_deadline(rule, cycle_year, anniversary_date)

        already_renewed = await db.scalar(
            select(Opportunity.id)
            .where(
                Opportunity.source_policy_id == policy.id,
                Opportunity.renewal_cycle == cycle_key,
                Opportunity.demo_session_id == demo_session_id,
            )
            .limit(1)
        )
        if already_renewed is not None:
            skipped += 1
            continue

        # A fresh flow: the renewal opportunity, its task, and both events share this
        # new correlation id (TDD §5.3 / §5.5).
        correlation_id = uuid.uuid4()

        renewal_opportunity = Opportunity(
            contact_id=origin_opportunity.contact_id,
            household_id=origin_opportunity.household_id,
            product_line=origin_opportunity.product_line,
            stage=_INITIAL_OPPORTUNITY_STAGE,
            origin=_RENEWAL_OPPORTUNITY_ORIGIN,
            owner_user_id=origin_opportunity.owner_user_id,
            owner_username=origin_opportunity.owner_username,
            source_lead_id=None,
            source_policy_id=policy.id,
            renewal_cycle=cycle_key,
            target_close_date=deadline,
            correlation_id=correlation_id,
            demo_session_id=demo_session_id,
        )
        db.add(renewal_opportunity)
        await db.flush()

        # The renewal-review Task. `target_close_date` is a `date`; the Task's
        # `due_date` column is a timestamptz, so store it as midnight UTC.
        db.add(
            Task(
                related_entity_type=_RENEWAL_TASK_RELATED_ENTITY_TYPE,
                related_entity_id=renewal_opportunity.id,
                task_type=_RENEWAL_TASK_TYPE,
                body=(
                    f"Review renewal for {policy.policy_number} "
                    f"({line_labels[origin_opportunity.product_line]})"
                ),
                assignee_user_id=origin_opportunity.owner_user_id,
                assignee_username=origin_opportunity.owner_username,
                due_date=datetime(
                    deadline.year, deadline.month, deadline.day, tzinfo=timezone.utc
                ),
                status=_OPEN_TASK_STATUS,
                correlation_id=correlation_id,
                demo_session_id=demo_session_id,
            )
        )
        await db.flush()

        await _emit(
            db,
            event_type=EventBusEventType.OPPORTUNITY_CREATED,
            tenant_id=tenant_id,
            payload={
                "entity_id": str(renewal_opportunity.id),
                "contact_id": str(origin_opportunity.contact_id),
                "household_id": str(origin_opportunity.household_id),
                "origin": _RENEWAL_OPPORTUNITY_ORIGIN,
                "source_policy_id": str(policy.id),
            },
            correlation_id=correlation_id,
            demo_session_id=demo_session_id,
        )
        await _emit(
            db,
            event_type=EventBusEventType.POLICY_RENEWAL_DUE,
            tenant_id=tenant_id,
            payload={
                "entity_id": str(policy.id),
                "opportunity_id": str(renewal_opportunity.id),
                "contact_id": str(origin_opportunity.contact_id),
                "household_id": str(origin_opportunity.household_id),
                "renewal_kind": rule,
                "due_date": deadline.isoformat(),
            },
            correlation_id=correlation_id,
            demo_session_id=demo_session_id,
        )

        # A session-owned policy takes the real, guarded `Active → Renewal Due`
        # write; a baseline policy (NULL session) is never written — its status is
        # derived at read time from the session's renewal opportunity (ADR 0005).
        if (
            policy.demo_session_id == demo_session_id
            and policy.status == _ACTIVE_STATUS
        ):
            policy.status = _RENEWAL_DUE_STATUS
            await db.flush()

        generated += 1

    return {"generated": generated, "skipped": skipped}


async def _emit(
    db: AsyncSession,
    *,
    event_type: EventBusEventType,
    tenant_id: uuid.UUID,
    payload: dict,
    correlation_id: uuid.UUID,
    demo_session_id: uuid.UUID,
) -> None:
    """Enqueue one renewal event onto this tenant's outbox on the request session.

    A thin wrapper over `build_envelope` + `enqueue_event` that pins the renewal
    invariants (TDD §5.3): each event carries the renewal's fresh `correlation_id`,
    `causation_id=None`, and the **system actor** (both actor fields `None`, since
    the sweep is automation), and rides the caller's request transaction so it lands
    or rolls back with the row writes.
    """
    await enqueue_event(
        db,
        build_envelope(
            event_type=event_type,
            tenant_id=tenant_id,
            actor_user_id=None,
            actor_role=None,
            payload=payload,
            correlation_id=correlation_id,
            causation_id=None,
            demo_session_id=demo_session_id,
        ),
    )
