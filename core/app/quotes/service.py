"""The carrier-quote round-trip actions (P2.3 §5.4).

Two halves of the one new event-driven flow:

- **`request_quotes`** (request side) — writes a `quote_requests` row `pending` and
  enqueues `quote.requested` on the **caller's** request transaction (the
  transactional outbox), exactly like the P2.2 stage action. The endpoint owns the
  guards; this assumes an already-guarded, already-loaded opportunity.
- **`complete_quote_request`** (consumer side) — the **non-terminal**
  `carrier.quote` consumer's effect. Because it writes domain rows *and* enqueues a
  completion event as the **tenant** role, it cannot reuse the terminal `_consume`
  core (hardwired to the `event_consumer` role + a no-output effect). It is a
  **parallel** consume path on its **own** session: resolve the tenant role from the
  registry, dedupe on the `quote_requests` status (an already-`completed` request is
  a no-op on redelivery — idempotent), generate the options from the registry
  catalog, INSERT the `quotes` rows, mark the request `completed`, and enqueue
  `quote.completed` — all in one transaction, propagating `correlation_id` /
  `demo_session_id` from the round-trip. (TDD D2 / D2b / C1.)
"""

import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import session_factory
from ..events.catalog import EventType
from ..events.envelope import EventEnvelope, build_envelope
from ..events.outbox import enqueue_event
from ..models.opportunity import Opportunity
from ..models.quote import Quote
from ..models.quote_request import QuoteRequest
from ..models.user import Role
from ..opportunities.state import OpportunityStage
from ..tenancy.registry import ProductLine, tenant_by_schema

# The two round-trip statuses the `quote_requests.status` column moves through.
STATUS_PENDING = "pending"
STATUS_COMPLETED = "completed"


class UnknownProductLine(LookupError):
    """Raised when a quote request names a product line the tenant does not offer.

    The request endpoint validates the opportunity's product line against the
    registry, so this only fires on corrupt data; the consumer lets it propagate so
    the message dead-letters rather than silently writing no options.
    """

    def __init__(self, schema_name: str, product_line_key: str) -> None:
        self.schema_name = schema_name
        self.product_line_key = product_line_key
        super().__init__(
            f"tenant schema {schema_name} offers no product line {product_line_key!r}"
        )


class UnknownQuoteRequest(LookupError):
    """Raised when the `quote.requested` event references no `quote_requests` row.

    The request row and the outbox event are written in the same transaction, so by
    the time the relay publishes the event the row is committed and visible. A
    missing row is therefore a real fault; the consumer lets it propagate so the
    message dead-letters.
    """

    def __init__(self, quote_request_id: uuid.UUID) -> None:
        self.quote_request_id = quote_request_id
        super().__init__(f"no quote_requests row for id {quote_request_id}")


async def request_quotes(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    opportunity_id: uuid.UUID,
    product_line: str,
    correlation_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    actor_role: Role | None,
    demo_session_id: uuid.UUID | None,
) -> QuoteRequest:
    """Open a quote round-trip — write the `pending` row and enqueue `quote.requested`.

    Runs on the caller's request session and **does not commit**, so the row write
    and the event enqueue land or roll back together (the transactional outbox). The
    event's payload is non-PII and `entity_id`-keyed (the request id), carrying the
    opportunity and product line the consumer reads. Returns the new, flushed
    `QuoteRequest`.
    """
    quote_request = QuoteRequest(
        id=uuid.uuid4(),
        opportunity_id=opportunity_id,
        status=STATUS_PENDING,
        product_line=product_line,
        correlation_id=correlation_id,
        demo_session_id=demo_session_id,
    )
    db.add(quote_request)
    await db.flush()

    await enqueue_event(
        db,
        build_envelope(
            event_type=EventType.QUOTE_REQUESTED,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            payload={
                "entity_id": str(quote_request.id),
                "opportunity_id": str(opportunity_id),
                "product_line": product_line,
            },
            correlation_id=correlation_id,
            causation_id=None,
            demo_session_id=demo_session_id,
        ),
    )
    return quote_request


async def complete_quote_request(envelope: EventEnvelope, schema_name: str) -> None:
    """Generate the options, complete the request, and enqueue `quote.completed`.

    The `carrier.quote` consumer's effect, run on its **own** session as the tenant
    `db_role` resolved from `schema_name` (already whitelist-validated by the
    consumer). Dedupes on the request status — an already-`completed` request short
    circuits, so a redelivery is a no-op. Otherwise it generates one `Quote` per
    registry option template for the request's product line, marks the request
    `completed`, and enqueues `quote.completed` (non-PII, `entity_id`-keyed),
    propagating the round-trip's `correlation_id` / `demo_session_id`. All in one
    transaction.
    """
    quote_request_id = uuid.UUID(envelope.payload["entity_id"])
    db_role = tenant_by_schema(schema_name).db_role

    async with session_factory() as session:
        await session.begin()
        # `db_role` and `schema_name` are a registry constant and a whitelist
        # validated schema name (never user input), so this identifier
        # interpolation is safe — the `relay.py` / `consumers.py` idiom.
        await session.execute(text(f"SET LOCAL ROLE {db_role}"))
        await session.execute(text(f"SET LOCAL search_path TO {schema_name}"))

        quote_request = (
            await session.execute(
                select(QuoteRequest).where(QuoteRequest.id == quote_request_id)
            )
        ).scalar_one_or_none()
        if quote_request is None:
            raise UnknownQuoteRequest(quote_request_id)
        if quote_request.status == STATUS_COMPLETED:
            # Idempotent: an already-completed request means this event was already
            # processed, so writing the options again would duplicate them. No-op.
            return

        for template in _product_line(schema_name, quote_request.product_line).quote_options:
            session.add(
                Quote(
                    id=uuid.uuid4(),
                    quote_request_id=quote_request.id,
                    opportunity_id=quote_request.opportunity_id,
                    carrier=template.carrier,
                    product_label=template.product_label,
                    coverage_amount=template.coverage_amount,
                    premium_monthly=template.premium_monthly,
                    premium_annual=template.premium_annual,
                    correlation_id=quote_request.correlation_id,
                    demo_session_id=quote_request.demo_session_id,
                )
            )

        quote_request.status = STATUS_COMPLETED

        await enqueue_event(
            session,
            build_envelope(
                event_type=EventType.QUOTE_COMPLETED,
                tenant_id=envelope.tenant_id,
                actor_user_id=envelope.actor_user_id,
                actor_role=envelope.actor_role,
                payload={
                    "entity_id": str(quote_request.id),
                    "opportunity_id": str(quote_request.opportunity_id),
                },
                correlation_id=quote_request.correlation_id,
                causation_id=None,
                demo_session_id=quote_request.demo_session_id,
            ),
        )

        await _attach_to_opportunity(session, envelope, quote_request)
        await session.commit()


async def _attach_to_opportunity(
    session: AsyncSession, envelope: EventEnvelope, quote_request: QuoteRequest
) -> None:
    """Move the opportunity to *Quoted* on the round-trip's first completion.

    The completion is what "attaches" the quotes (TDD §5.4.4), so the *Quoted* move
    rides the consumer's completing transaction rather than the poll endpoint: the
    poll then stays a pure read (a Read-Only viewer polling never triggers a
    mutation — TDD §5.9), and the move happens exactly once because the request is
    deduped on its status. *Quoted* is a normal forward stage (not automation-owned),
    and the Medicare gate was already cleared at request time, so this advances the
    stage directly and emits `opportunity.stage_changed` for observability — only
    when the opportunity is still at *Qualified* (any later stage means the move
    already happened or was overtaken, so it is left untouched).
    """
    opportunity = (
        await session.execute(
            select(Opportunity).where(Opportunity.id == quote_request.opportunity_id)
        )
    ).scalar_one_or_none()
    if opportunity is None or OpportunityStage(opportunity.stage) != OpportunityStage.QUALIFIED:
        return

    from_stage = opportunity.stage
    opportunity.stage = OpportunityStage.QUOTED.value

    await enqueue_event(
        session,
        build_envelope(
            event_type=EventType.OPPORTUNITY_STAGE_CHANGED,
            tenant_id=envelope.tenant_id,
            actor_user_id=envelope.actor_user_id,
            actor_role=envelope.actor_role,
            payload={
                "entity_id": str(opportunity.id),
                "from_stage": from_stage,
                "to_stage": OpportunityStage.QUOTED.value,
                "contact_id": str(opportunity.contact_id),
                "household_id": str(opportunity.household_id),
            },
            correlation_id=opportunity.correlation_id,
            causation_id=None,
            demo_session_id=opportunity.demo_session_id,
        ),
    )


def _product_line(schema_name: str, product_line_key: str) -> ProductLine:
    """Return the tenant's `ProductLine` for `product_line_key`, or raise.

    Reads the registry catalog the stub generates options from — the single source
    of truth for which options a product line offers (TDD D4). Raises
    `UnknownProductLine` when the tenant offers no such line.
    """
    tenant = tenant_by_schema(schema_name)
    for product_line in tenant.product_lines:
        if product_line.key == product_line_key:
            return product_line
    raise UnknownProductLine(schema_name, product_line_key)
