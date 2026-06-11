# PolicyFlow Requirements Document

## Project Overview

**PolicyFlow** is a multi-tenant **insurance workflow orchestration platform with CRM integrations**, designed to demonstrate business-process modeling, CRM domain modeling, event-driven integrations, tenant isolation, and secure handling of sensitive customer data.

The application models realistic insurance brokerage workflows and object relationships while integrating with a collection of sidecar services representing external systems commonly found in enterprise CRM ecosystems.

The goal is not to build a Salesforce clone. The goal is to build a realistic platform where insurance business processes are modeled explicitly — lifecycle states, decision points, and edge cases — with CRM-style objects recording their outcomes and integrations operating around them. CRM is a supporting capability within a broader workflow-orchestration system, not the primary objective.

Requirements in this document are tagged **[MUST]**, **[SHOULD]**, or **[COULD]**. Untagged statements inside a tagged section inherit the section's tag.

---

## Project Motivation

This project exists to demonstrate deep, hands-on command of insurance business-process orchestration, CRM object relationships, CRM-adjacent integration patterns, and multi-tenant application architecture — the skill set expected of a senior full-stack engineer working on enterprise CRM platforms.

The emphasis is the workflow layer: the deepest complexity in these systems lives in the business processes — the decision points, exception paths, and orchestration that carry a lead to a policy — more than in the objects themselves. PolicyFlow models that process layer explicitly; CRM object modeling and integration are the supporting capability around it.

It is built as a production-minded MVP: business processes orchestrated end-to-end, complex business relationships modeled explicitly, tenant data isolated by design, PII protected end-to-end, integrations designed behind clean adapter boundaries, background workflows processed reliably, and the whole experience walkable end-to-end by a visitor in minutes.

---

## Objectives

- Model insurance business processes explicitly — lifecycle states, decision points, and edge cases — as the platform's core
- Demonstrate workflow orchestration: human and automated decision points advancing long-running processes
- Demonstrate understanding of CRM domain modeling
- Showcase multi-tenant SaaS architecture patterns
- Simulate enterprise CRM integration patterns
- Implement event-driven workflows
- Demonstrate secure PII handling
- Build an interactive, **deterministic, repeatable** end-to-end portfolio experience
- Show realistic insurance brokerage business logic instead of simple CRUD screens
- Make the engineering legible in-app: the running application names its patterns, CRM parallels, and real-vs-simulated boundaries to a cold reviewer

---

## Out of Scope / Non-Goals

The following are explicitly **not** part of this project. The design must not include them, and the TDD step should not raise questions about them:

- **No real email delivery.** Notifications render in an in-app notification center and a simulated outbox page only.
- **No real OAuth/OIDC flow.** Username/password only, behind a pluggable `AuthProvider` interface (see Security Requirements). The seam is documented, not built.
- **No real external APIs.** CRM, enrichment, and carrier integrations are all simulated services behind adapter boundaries.
- **No tenant self-service signup or onboarding.** Exactly two tenants exist, created by seed scripts.
- **No general inbound CRM sync.** Outbound sync only, plus exactly one canned inbound-webhook scenario (**[SHOULD]**, Phase 4 — see CRM Sync Service); nothing more. Inbound record creation and full bidirectional sync remain out of scope.
- **No full contact merge.** Duplicate handling links or rejects leads (see Duplicate Handling); merging two Contacts with child re-parenting is out of scope.
- **No custom role builder.** Roles are fixed and platform-defined; tenants assign users to roles only.
- **No data-retention enforcement.** No purge/archival subsystem beyond the demo-session cleanup defined in Demo Experience.
- **No multi-household contact membership.** A Contact belongs to exactly one Household (documented simplification; many-to-many is a known real-world extension).
- **No real SSN, health, or Medicare data.** One *mock* high-sensitivity field (a fake Medicare ID) is modeled to demonstrate the handling pattern; everything else is synthetic low-sensitivity data. See PII Protection.
- **No billing, no mobile apps, no internationalization.**

---

## Glossary

| Term | Definition |
|---|---|
| **Tenant** | An insurance agency using the platform. All domain data is scoped to exactly one tenant. |
| **Product Line** | A category of insurance a tenant sells (e.g. Medicare Advantage, Life Insurance). |
| **Product** | A catalog entry under a Product Line, per tenant (e.g. a specific mock plan). |
| **Lead** | An unqualified prospect created by intake. Becomes frozen once converted. |
| **Contact** | A person record created by lead conversion. |
| **Household** | The grouping of Contacts at one address/family unit. PolicyFlow's only account-like entity (both demo tenants are B2C). Maps to the external CRM object "Account" during sync. |
| **Opportunity** | A potential sale of one product line to one Contact. Progresses through pipeline stages. |
| **Renewal Opportunity** | A regular Opportunity with `origin = renewal` and a link to the originating Policy. Not a separate entity. |
| **Quote** | A carrier's mock offer for an Opportunity (carrier, product, premium, status). |
| **Application** | The formal request to a carrier, created when an agent selects a Quote. |
| **Policy** | An issued, in-force insurance contract. |
| **Carrier** | A reference entity for a (mock) insurance company and the product lines it underwrites. |
| **Task** | A unit of agent work (e.g. renewal review) with an assignee, due date, and a polymorphic link to a Lead, Contact, Opportunity, or Policy. |
| **Workflow** | An orchestrated business process with explicit states, decision points, and edge cases (see Workflow Orchestration Model). |
| **Decision Point** | A workflow step where a named human actor or automated rule determines the path forward; where it changes records, the outcome is audited. |
| **Domain Event** | An immutable record that a business action occurred, published on the event bus. |
| **Sidecar Service** | A worker process that consumes domain events and performs simulated external-integration work. |
| **Demo Session** | A visitor's sandboxed walkthrough context; visitor-created records are tagged with its ID. |
| **Explainer** | A dismissible info popover/panel on a showcase surface naming the engineering pattern, how PolicyFlow implements it, and what is real vs simulated. |
| **CRM Parallel** | An explainer annotation naming the real-world CRM equivalent of a PolicyFlow pattern (e.g. Salesforce lead conversion). |
| **Simulated Badge** | A UI marker on simulated integration surfaces distinguishing what is mocked from the real machinery around it. |
| **How It's Built Page** | A persistent architecture-overview page indexing every showcase pattern with deep links, plus repository and author links. |

---

## Demo Tenants

PolicyFlow includes two pre-seeded demo tenants representing different insurance agency specializations. Tenants are created by seed scripts only.

### Tenant 1: Sunshine Senior Benefits

Specializes in senior-focused insurance products.

Supported product lines:

- Medicare Advantage
- Medicare Part D
- Hospital Indemnity

Example use case:

A senior customer submits interest in Medicare Advantage. The platform creates a lead, enriches the customer profile, checks for duplicates, qualifies the lead, creates an opportunity, passes the Medicare eligibility gate, simulates carrier quotes, generates an application from the selected quote, creates a policy, and schedules an AEP renewal-review workflow.

### Tenant 2: Florida Family Planning

Specializes in family, financial, and long-term planning products.

Supported product lines:

- Life Insurance
- Annuities
- Long Term Care

Example use case:

A customer submits interest in life insurance and long-term care planning. The platform creates a lead, links the contact to a household, creates one opportunity per product line of interest, simulates external enrichment, and syncs relevant updates through the CRM integration layer.

The two tenants must be **visibly different on the same screens**: branding, product lines, pipeline stage labels, and CRM field mappings all differ via seed configuration. This differentiation is itself a demo requirement (see Demo Experience).

---

## Users

### Tenant Administrator

- Manage tenant settings (view seed-driven configuration)
- Assign users to predefined roles
- Review analytics and audit logs
- Reassign leads and tasks between agents

### Agent

- Claim and manage assigned leads
- Qualify and convert leads
- Progress opportunities, request quotes, process applications
- Manage customer relationships
- Review CRM sync status for their records

### Read-Only User

A compliance/auditor persona, realistic for insurance agencies:

- View leads, contacts, households, opportunities, applications, and policies with **PII masked and no reveal action**
- View dashboards and audit logs
- No create/edit/delete capability anywhere (server-enforced)

### Platform Administrator

A single seeded super-user operating **outside tenant scope, on operational data only**:

- View the platform health page (queue depth, failed jobs, integration health across tenants — metadata and aggregates, never unmasked tenant PII)
- Trigger demo controls (data reset, renewal sweep, simulated CRM outage, simulated inbound CRM change)
- Review dead-letter queue items and replay or discard them

---

## Domain Model

**[MUST]** The system shall model the following tenant-scoped entities. One-line relationship notes are normative:

```text
Tenant
  -> Product Lines
       -> Products            (catalog entries under a product line)
  -> Carriers                 (reference data: carrier + product lines it underwrites)
  -> Users                    (with role assignments)
  -> Leads                    (lead_source field required; frozen on conversion)
  -> Contacts                 (belong to exactly one Household)
  -> Households               (the only account-like entity; has many Contacts, many Policies)
  -> Opportunities            (belong to a Contact, with Household rollup; carry an agent owner, estimated_annual_premium, and target_close_date; one per product line of interest)
       -> Quotes              (0..n per Opportunity; carrier, product, premium, status)
       -> Application         (at most one active per Opportunity; created by selecting a Quote)
            -> Policy         (0..1 per Application)
  -> Tasks                    (assignee, due date, type; polymorphic link to Lead/Contact/Opportunity/Policy)
  -> CRM Sync Events
  -> Audit Records
```

Happy-path conversion flow (**this is a flow, not entity cardinality** — cardinality is defined in Domain Model Decisions below):

```text
Lead -> Contact + Household -> Opportunity -> Quote -> Application -> Policy -> Renewal Opportunity
```

---

## Domain Model Decisions

**[MUST]** These decisions are normative and answer the core CRM relationship questions directly. The TDD derives the schema from this table.

| Question | Decision |
|---|---|
| When does a lead become a contact? | When an agent converts a qualified lead. Conversion creates (or matches) a Contact and a Household, and creates one Opportunity per product line of interest. The Lead is then frozen: status `Converted`, read-only, stamped with `converted_contact_id` and `converted_opportunity_ids`. |
| Can one contact belong to multiple households? | **No (MVP).** Exactly one Household per Contact. Many-to-many membership is a documented real-world extension, deliberately out of scope. |
| Can one household have multiple policies? | **Yes.** A Household aggregates all policies of its members. |
| Can one lead create multiple opportunities? | **Yes** — one Opportunity per product line of interest captured at intake. |
| Can one opportunity create multiple policies? | **No.** One Opportunity has at most one **active** Application (a declined Application may be superseded by selecting another Quote) and produces at most one Policy. Cross-selling creates additional Opportunities instead. |
| What happens when a duplicate lead is submitted? | Deterministic matching at intake flags it; an agent resolves it (link to existing Contact, proceed as new, or reject). See Duplicate Handling. |
| What happens when a policy nears expiration/renewal? | Per-product renewal rules generate a Renewal Opportunity plus an agent Task and a notification. See Renewal Management. |
| How do product-specific workflows differ? | Via per-product business rules (eligibility gates, required application steps). See Opportunity Management. |
| Which events trigger integrations? | Defined per-event in the Event Catalog's consumer column. |

### Lifecycle States

**[MUST]** Three entities carry explicit state machines:

- **Lead:** `New -> Working -> Qualified | Rejected`; `New -> Rejected` (duplicate resolution); `Qualified -> Converted` (terminal, frozen). Claiming or being assigned a lead transitions it `New -> Working`; reassignment preserves `Working`.
- **Application:** `Draft -> Submitted -> Approved | Declined`
- **Policy:** `Active -> Renewal Due -> Renewed | Lapsed`; `Active -> Cancelled`. Triggers: renewal generation sets *Renewal Due*; issuing a policy from the linked Renewal Opportunity sets *Renewed* (publishes `policy.renewed`); the daily job sets *Lapsed* when the expiration/anniversary date passes unrenewed (publishes `policy.lapsed`); an explicit cancel action (Agent or Tenant Admin) sets *Cancelled* (publishes `policy.cancelled`).

Transitions outside these machines are rejected server-side.

**Coupling rule:** Application status changes auto-advance the linked Opportunity's stage (`Submitted` → stage *Submitted*, `Approved` → stage *Approved*, Policy issuance → stage *Policy Active*). The Opportunity stage never drives Application status. A `Declined` application returns the Opportunity to *Quoted* (or *Qualified* where *Quoted* is disabled); the agent may then select a different Quote, which creates a new Application superseding the declined one.

---

## Workflow Orchestration Model

**[MUST]** PolicyFlow's center of gravity is the orchestration of insurance business processes. This section names those workflows and makes the process-first lens normative. **It adds no behavior:** every cell below reorganizes requirements defined elsewhere in this document, cited per row; the final rule adds one design directive to the TDD.

| Workflow | Trigger | Key states / stages | Decision points (actor) | Edge cases modeled |
|---|---|---|---|---|
| **Lead Intake & Triage** (Lead Intake, Lead Assignment, Duplicate Handling, Lead Qualification and Conversion) | Public form submission | Lead: `New -> Working -> Qualified \| Rejected` | Claim lead (agent); duplicate resolution — link / new / reject (agent); qualify or reject (agent) | Duplicate detected at intake; abuse-control rejection; enrichment arriving late — never blocks qualification |
| **Lead Conversion** (Lead Qualification and Conversion) | Agent converts a qualified lead | One transaction: Contact + Household + one Opportunity per product line; Lead frozen | Link to existing Household vs create new (agent) | Converting a duplicate-linked lead attaches new Opportunities to the existing Contact |
| **Opportunity-to-Policy** (Opportunity / Quote / Application / Policy Management sections) | Opportunity created | Canonical stages `New -> ... -> Policy Active`; Application `Draft -> Submitted -> Approved \| Declined` | Eligibility gate (automated rule); request quotes and select one (agent); product-specific steps + submission (agent); carrier decision (simulated rule) | Gate blocks quoting (Medicare age rule); declined Application returns the Opportunity to *Quoted* (or *Qualified*) and a superseding Application may be created; optional stages disabled per tenant; *Lost* from any stage |
| **Renewal** (Renewal Management) | AEP sweep (seasonal) or daily anniversary job | Policy: `Active -> Renewal Due -> Renewed \| Lapsed` | Renewal review Task (agent) | Per-product divergence — calendar-year AEP vs 60-day anniversary vs no renewal at all; lapse when unrenewed; explicit cancellation |
| **Cross-sell** (Policy Management) | Policy created | New Opportunity created in one click | Accept the suggestion (agent); the prompt may be left un-acted-on | No prompt when the Household is already covered in every tenant product line |
| **Integration Recovery** (CRM Sync Service) | Sync failure after final retry | Retries -> DLQ -> replay \| discard | Replay or discard (Tenant Admin; Platform Admin cross-tenant) | Simulated outage; per-record failure via magic input; final-failure notification fires once, on final failure (not per retry) |

Rules:

- Every workflow's states and transitions are explicit (the lifecycle state machines in Domain Model Decisions and the canonical stage machine in Opportunity Management); invalid transitions are rejected server-side.
- Every decision point is attributable — a named human actor or a named automated rule; decision outcomes that create or change records are captured per Audit Logging.
- Edge cases with deterministic triggers (duplicate, declined application, sync failure, outage, renewal sweeps) are one click away per Guided Demo; the remaining edge cases (abuse-control rejection, lapse-when-unrenewed, late-arriving enrichment) are modeled in the state machines and business rules and verified by automated tests.
- The TDD shall treat these workflows as first-class design units: orchestration logic explicit and testable, not implicit in controller or UI code.

---

## Multi-Tenancy Requirements

**[MUST]** Each tenant maintains complete logical isolation.

### Isolation Strategy

- Shared database, shared schema. Every domain entity carries `tenant_id`.
- Tenant context is derived **only** from the authenticated session — never from a request parameter — and injected by middleware into every query.
- Database-enforced row-level security (e.g. PostgreSQL RLS; final choice belongs to the TDD) enforces tenant scoping as defense-in-depth beneath the application layer.
- Every domain event and queue message carries `tenant_id`; sidecar services must scope all processing and field-mapping lookups by it.
- **Testable requirement:** automated tests shall verify that a user of Tenant A cannot read or modify any Tenant B record through any API endpoint.

### Platform Administrator Carve-Out

Platform Administrators operate outside tenant scoping **for operational data only**: cross-tenant aggregates, integration health, queue status, and failure metadata — never unmasked customer PII. Cross-tenant queries run through a dedicated platform-scoped path (separate DB role / explicit RLS bypass), and every cross-tenant read is itself audit-logged. Demo-data management (seed/reset) is the one sanctioned operation that touches tenant records.

### Tenant-Scoped Resources

Users, role assignments, leads, contacts, households, opportunities, quotes, applications, policies, tasks, audit records, product catalog, carriers, pipeline stage configuration, integration configurations, CRM field mappings, and metrics.

---

## Tenant Configuration

**[MUST]** Tenant configuration is **defined via seed configuration** — data-driven, not hard-coded — demonstrating the multi-tenant configuration model. Admin UIs for *editing* this configuration are a stretch goal (see Stretch Goals); the MVP renders configuration read-only in the Tenant Admin view.

Seed-configurable per tenant:

- Branding (name, logo, color scheme)
- Supported product lines and product catalog
- Pipeline stage labels and optional-stage toggles (see Opportunity Management for constraints)
- CRM field mappings
- Integration settings (e.g. simulated failure rate)
- Notification preferences: per-tenant toggles for each Notification-routed event type in the Event Catalog (renewal reminders, assignment alerts, duplicate alerts, application decisions, policy lifecycle, integration failures)

The two seeded tenants must differ visibly in every one of these dimensions.

---

## Core Application Features

### Lead Intake

**[MUST]** Public, tenant-specific intake forms.

**Intake fields** — required: first name, last name, email, phone, ZIP code, date of birth, product line(s) of interest (one or more). Optional: street address, preferred contact method, notes. Validation: email format, phone format, DOB plausible (age 18–110), field length limits, at least one product line.

**Execution order (normative, async by design):**

1. Validate the submission server-side.
2. Create the tenant-scoped Lead (status `New`, unassigned, `lead_source = public_form`).
3. Run deterministic duplicate matching (see Duplicate Handling) and flag if matched.
4. Publish `lead.created`.
5. The Enrichment sidecar processes asynchronously; the lead detail view shows an "enriching" state that resolves when results arrive (see Sidecar Services). The UI must visibly reflect this async progression — it is part of the demo, not a defect.

**Abuse controls** (the form is an unauthenticated internet-facing write endpoint): per-IP rate limiting, a honeypot field, strict server-side schema validation with length limits. Every submission belongs to a demo session: visitors arriving via tenant selection already have one; direct submissions without a session auto-create an anonymous demo session subject to the same 24-hour expiry — so all publicly submitted records are cleaned up via the demo-session lifecycle (see Demo Experience).

### Lead Assignment

**[MUST]** Every Lead and Opportunity has an `owner` field. New intake leads land in a tenant-wide **unassigned queue**; any agent claims them (one click). Tenant Admins can reassign. Claiming/reassignment publishes `lead.assigned`, which drives the assignment notification. Assignment governs task routing and dashboards — **not visibility** (see Authorization).

### Duplicate Handling

**[MUST]**

- **Match rule:** at intake, the core app matches on normalized email OR normalized phone (exact, via blind index — see PII Protection), scoped to the tenant. Matches flag the lead with `duplicate_of_contact_id` and publish `lead.duplicate_detected`.
- **Advisory score:** the Enrichment sidecar additionally returns a probabilistic `duplicate_probability` (fuzzy name + DOB), displayed as decision support only.
- **Resolution (agent action):** link the lead to the existing Contact (conversion then attaches new Opportunities to that Contact), proceed as a new person, or reject the lead.
- Full Contact merge with child re-parenting is **out of scope** (see Out of Scope).

### Lead Qualification and Conversion

**[MUST]** Agents qualify (`Qualified`) or reject (`Rejected`) working leads.

**Conversion rules:** converting a qualified lead, in one transaction:

- Creates a Contact (field mapping: first/last name, email, phone, address, DOB, lead_source → Contact; notes → a note-type Task attached to the new Contact).
- Creates a new Household or links to an existing one: the agent may search for and select an existing Household during conversion; otherwise a new one is created (no automatic address-based matching in the MVP). When resolving a duplicate, the existing Contact's Household is pre-selected.
- Creates one Opportunity per product line of interest, belonging to the Contact, with the converting agent as owner.
- Freezes the Lead: status `Converted`, read-only, stamped with `converted_contact_id` / `converted_opportunity_ids`.
- Publishes `lead.converted`, `contact.created`, `household.created` (if new), and `opportunity.created` per opportunity.

### Opportunity Management

**[MUST]** A fixed **canonical stage state machine**:

```text
New -> Qualified -> Quoted -> Application Started -> Submitted -> Approved -> Policy Active
(any stage) -> Lost
```

Tenant configurability is constrained to: renaming display labels and enabling/disabling the optional intermediate stages (*Quoted*, *Approved*). Anchor stages (*New*, *Application Started*, *Policy Active*, *Lost*) cannot be removed — lifecycle automation and cross-tenant reporting key off them. When an optional stage is disabled, transitions that would enter it leave the opportunity at its current stage until the next enabled stage's trigger fires (quotes attach while the opportunity remains at *Qualified*; an approved application leaves the stage at *Submitted* until policy issuance moves it to *Policy Active*). Stage changes publish `opportunity.stage_changed` (and `opportunity.lost` for *Lost*). Transitions outside this machine are rejected server-side.

**Pipeline value fields:** every Opportunity carries an `estimated_annual_premium` (seeded or agent-entered at creation; automatically updated to the selected Quote's annualized premium when an Application is created) and a `target_close_date` (defaulted at creation, e.g. +30 days; for renewal opportunities, the renewal/AEP deadline). These mirror the universal CRM `Amount` / `CloseDate` pipeline convention and are named as such in the CRM-parallel annotation (see Engineering Explainers).

**Product-specific business rules** (this is the substance of per-tenant workflow differentiation):

- **Medicare Advantage / Part D:** an eligibility gate (age ≥ 65, computed from the stored DOB via the derived age band) must pass before the opportunity may reach *Quoted*; quote requests are blocked until it passes. The enrichment Medicare-eligibility flag is corroborating decision support only — the gate never waits on enrichment.
- **Life Insurance:** the Application requires beneficiary information (name, relationship) before submission.
- **Long Term Care:** the Application includes a simulated health-questions step (3–5 mock yes/no questions) before submission.
- Hospital Indemnity and Annuities follow the default flow.

### Quote Management

**[MUST]** Quotes precede applications. From an opportunity at *Qualified*, the agent requests quotes: core publishes `quote.requested`; the Carrier Quote sidecar returns options asynchronously via `quote.completed` (target latency: results within ~5 seconds; the UI shows a pending state). Quote records (carrier, product, monthly premium, status) attach to the Opportunity, which moves to *Quoted*. **Selecting a quote is what creates the Application** (status `Draft`) and moves the opportunity to *Application Started*, publishing `application.started`.

### Application Management

**[MUST]**

- Track application status per the lifecycle state machine (`Draft -> Submitted -> Approved | Declined`).
- Capture product-specific steps (beneficiary, health questions) per the rules above.
- The application stores a **mock Medicare ID** (Tenant 1) — a fake, clearly-synthetic identifier used as the PII-handling centerpiece (encrypted at rest, always rendered masked, e.g. `***-**-1234`).
- Submission simulates carrier submission and publishes `application.submitted`; the simulated carrier responds with `application.approved` or `application.declined`. Demo determinism: applications are approved by default; a magic input (applicant email containing `deny`) deterministically forces `application.declined`, mirroring the CRM-failure trigger.
- Approval enables policy issuance; trigger CRM sync events throughout.

### Policy Management

**[MUST]** The system shall track: carrier, product line, policy number, effective date, expiration/anniversary date, policy status (per lifecycle states), associated Contact, associated Household, and owning agent (copied at issuance from the originating Opportunity's owner). Policy creation publishes `policy.created`; an explicit cancel action (Agent or Tenant Admin) sets status *Cancelled* and publishes `policy.cancelled`.

**Cross-sell prompt:** when a Policy is created, if the Household lacks coverage in another tenant-supported product line, the Household record surfaces a "suggested cross-sell" prompt that can create a new Opportunity in one click. The prompt shows one suggestion per uncovered product line; the created Opportunity belongs to the Contact on the triggering Policy, with that Policy's owning agent as owner.

### Renewal Management

**[MUST]** Renewal behavior is **per product line** — modeling this correctly is a core domain signal:

| Product line | Renewal rule |
|---|---|
| Medicare Advantage / Part D | Calendar-year plans; no per-policy expiration. A seasonal **AEP sweep** (modeled on the Oct 15 – Dec 7 Annual Enrollment Period) generates an "AEP Review" Renewal Opportunity for every active policy. |
| Hospital Indemnity / Long Term Care | A daily job generates a Renewal Opportunity 60 days before the policy anniversary date. |
| Life Insurance / Annuities | No renewal opportunities generated. |

For each generated renewal: create the Renewal Opportunity (a standard Opportunity with `origin = renewal`, linked to the originating Policy), create an agent Task assigned to the policy's owning agent, publish `policy.renewal_due`, and send a notification.

**Demo time controls** (required — renewals must be observable live): seed data includes policies already inside renewal windows, and the Platform Admin has "run renewal sweep now" and "run AEP sweep now" actions that execute the jobs on demand within the visitor's demo session scope. Sweeps never mutate seeded policies: they generate session-tagged Renewal Opportunities, Tasks, and notifications, with the seeded policy's *Renewal Due* status presented via a session-scoped overlay; real status transitions apply only to session-created policies.

---

## Event-Driven Architecture

**[MUST]** The system publishes domain events as business actions occur. Sidecar services consume them asynchronously.

### Event Envelope

Every event carries: `event_id` (unique), `event_type`, `schema_version`, `tenant_id`, `occurred_at`, `correlation_id` (constant across one lead's end-to-end lifecycle — this powers the demo's event-trace view), optional `causation_id` and `actor` (user vs system), and an optional `demo_session_id` (present on events originating in a demo session; sidecars tag records derived from such events with it).

**Payload convention:** entity reference plus key non-PII fields — never full PII snapshots (this also satisfies "no raw PII in logs"). **Documented exception:** events that drive sidecar processing (`lead.created` for Enrichment; the events CRM Sync consumes) additionally carry the whitelisted PII fields that processing requires, delivered over the broker only and never logged — sidecars never query the core database. Core evaluates demo magic inputs at publish time and sets flags (e.g. `simulate_failure`) so sidecars never inspect raw PII.

### Event Catalog

| Event | Publisher | Consumers |
|---|---|---|
| `lead.created` | Core | Enrichment, CRM Sync, Metrics |
| `lead.enrichment.completed` | Enrichment | Core |
| `lead.enriched` | Core | CRM Sync, Metrics |
| `lead.duplicate_detected` | Core | Notification, Metrics |
| `lead.assigned` | Core | Notification, Metrics |
| `lead.qualified` / `lead.rejected` | Core | CRM Sync, Metrics |
| `lead.converted` | Core | CRM Sync, Metrics |
| `contact.created` / `household.created` | Core | CRM Sync, Metrics |
| `opportunity.created` | Core | CRM Sync, Metrics |
| `opportunity.stage_changed` / `opportunity.lost` | Core | CRM Sync, Metrics |
| `quote.requested` | Core | Carrier Quote |
| `quote.completed` | Carrier Quote | Core, Metrics |
| `application.started` / `application.submitted` | Core | CRM Sync, Metrics |
| `application.approved` / `application.declined` | Core | CRM Sync, Notification, Metrics |
| `policy.created` / `policy.renewed` / `policy.lapsed` / `policy.cancelled` | Core | CRM Sync, Notification, Metrics |
| `policy.renewal_due` | Core | Notification, Metrics |
| `pii.revealed` | Core | Audit (sensitive-operation log), Metrics |
| `crm.sync.requested` / `crm.sync.completed` / `crm.sync.failed` | CRM Sync | Core, Notification (failures), Metrics |

**Publisher rule:** the core app publishes all domain events; sidecars publish only their own integration/completion events.

### Delivery Semantics

- Delivery is **at-least-once**; all consumers must be idempotent (deduplicate on `event_id`).
- Ordering is **not guaranteed**; consumers must tolerate out-of-order delivery.
- Events **fan out**: each sidecar holds an independent subscription with its own retry and dead-letter handling (a single shared work queue is not acceptable).
- The broker/transport choice is deferred to the TDD, but must support durable delivery, multi-consumer fan-out, per-consumer retry, and observable queue depth.
- **Consistency:** domain events must not be lost relative to committed state changes (mechanism — e.g. transactional outbox — is a TDD decision).

---

## Sidecar Services

**[MUST]** Four sidecar services surround the core application:

```text
PolicyFlow Core App
  -> CRM Sync Service
  -> Enrichment Service
  -> Carrier Quote Service
  -> Notification Service
```

(Analytics is **not** a sidecar: an in-app, event-sourced metrics read model powers the dashboards. See Observability.)

**Data ownership:** sidecars do not access the core database. Each owns its own state (CRM Sync: mock CRM records and sync activity; Notification: rendered notifications/outbox) and interacts with core only via events; the data a sidecar needs arrives in event payloads per the Event Envelope's documented exception. Sidecar records derived from demo-session events carry the session's `demo_session_id` and are purged with the session. Core audit logging records business-level outcomes (e.g. "sync failed"); per-attempt integration detail lives with the sidecar.

**Result flow:** all sidecar interaction is asynchronous. Request/reply flows (enrichment, quotes) are modeled as request events answered by completion events that core consumes, with the UI showing pending states.

### CRM Sync Service

- Consume domain events; transform internal objects into CRM-style records using **tenant-specific field mappings**.
- **Field mapping defined:** a field mapping is per-tenant, per-object configuration covering at minimum four transformation types: **field rename** (internal name → CRM-style API name, e.g. `first_name` → `FirstName`), **picklist translation** (e.g. canonical stage → CRM `StageName` values, differing per tenant), **format transform** (e.g. date or phone normalization), and **constant/default injection** (e.g. `Account.Type = "Household"`). CRM-style payloads use Salesforce-flavored API names, including at least one custom object (`Policy__c`) and custom fields (`__c` suffix).
- **Mapping visibility:** the mock CRM record viewer renders a side-by-side view — internal record, mapping rules applied, resulting CRM-style payload. The same internal record synced under each tenant's mappings must produce visibly different payloads (walkthrough step 13).
- **External-ID correlation (upsert semantics):** on the first successful sync of an entity, the service stores the mock CRM record's external ID keyed to the internal entity in sidecar-owned state (per the data-ownership rule); subsequent events for that entity update the existing CRM record by external ID — never create a second one. The sync activity log labels each operation **Create** or **Update** and shows the external CRM record ID; the per-record timeline and CRM record viewer surface it, so one internal record traces to exactly one mock CRM record across retries and DLQ replays.
- Mapping rule: the internal **Household maps to the external CRM "Account" object** (type Household), per standard B2C CRM convention; Lead→Lead, Contact→Contact, Opportunity→Opportunity, Policy→Policy (custom object).
- Simulate sync success and failure. **Retry policy:** max 3 attempts with exponential backoff in seconds (demo-friendly), then move to the dead-letter queue. `crm.sync.failed` and the admin notification fire **once, on final failure**; per-attempt detail is recorded in the sync activity log.
- DLQ items appear in the integration health dashboard. Tenant Admins can **replay** or **discard** their own tenant's items; the Platform Admin can do so across tenants from the platform health page. A minimal DLQ list with these actions ships in Phase 3; the full dashboard arrives in Phase 4.
- **Deterministic failure trigger:** a Platform Admin "simulate CRM outage" toggle (session-scoped in demo sessions), plus a magic input — an intake email containing `fail` — which core detects at publish time, setting `simulate_failure` on that record's sync-triggering events. Seeded history includes a low background failure rate so dashboards are pre-populated.
- **[SHOULD]** **Inbound webhook scenario (Phase 4):** a Platform Admin demo control ("simulate inbound CRM change") makes the mock CRM emit one canned update type (contact phone change); the system applies it last-write-wins with an audit entry and a sync-activity record; loop prevention = ignore self-originated changes; inbound record creation excluded. Session-scoped like all demo controls; the inbound update flows over the broker as a CRM Sync-published event per the publisher rule (event naming defers to the TDD).
- Whether or not the inbound scenario ships, the CRM sync explainer (see Engineering Explainers) **[MUST]** describe the bidirectional-sync design space — conflict-resolution strategies, loop prevention, source-of-truth assignment — and state why inbound sync was scoped out of the MVP and how the adapter boundary accommodates it.

### Enrichment Service

Simulates **consumer-data enrichment** (Experian/Acxiom-style — both tenants are B2C):

- Returns: age band and DOB verification, household composition, homeowner status, estimated income band, address normalization, a **Medicare-eligibility flag** (age ≥ 65) for Tenant 1, lead quality score, risk score, and duplicate probability.
- Input: the `lead.created` payload carries the lead's submitted fields plus core-selected candidate-match summaries (normalized name, DOB) used to score duplicate probability; the service never queries core data.
- Publishes `lead.enrichment.completed`; core applies results and publishes `lead.enriched`.
- **Consumers of the output (required):** enrichment results display on the Lead detail view; the lead quality score appears in the lead list and qualification screen as non-blocking decision support; the eligibility flag is displayed alongside the Medicare eligibility gate as corroboration (the gate itself computes from the stored DOB).

### Carrier Quote Service

- Generates mock quotes and simulates eligibility checks per tenant product lines.
- Product-line → carrier mapping (every product line has at least one quoting carrier):

| Product line | Mock carrier |
|---|---|
| Medicare Advantage / Part D | Mock Medicare Carrier |
| Hospital Indemnity | Mock Hospital Indemnity Carrier |
| Life Insurance | Mock Life Carrier |
| Annuities | Mock Annuity Carrier |
| Long Term Care | Mock Long Term Care Carrier |

### Notification Service

- Consumes events per the catalog and the tenant's notification preferences.
- **Surfaces (required):** an in-app notification center (bell icon, per user) and a demo-visible **simulated outbox** page listing rendered email payloads per tenant. No real email is sent.
- Covers renewal reminders, assignment alerts, application decisions, and integration-failure alerts to admins.

---

## Integration Requirements

**[MUST]** The system shall demonstrate: outbound CRM sync, external enrichment, carrier quote retrieval, background retry processing, dead-letter queue handling with human replay, tenant-specific field mappings, external-ID upsert correlation, and integration audit logs.

A clear adapter boundary allows mock services to be replaced with real integrations:

```text
CRMAdapter
  -> MockCRMAdapter
  -> (future: SalesforceAdapter, HubSpotAdapter)
```

General inbound CRM sync is out of scope (see Out of Scope); exactly one canned inbound-webhook scenario is a Phase 4 **[SHOULD]** (see CRM Sync Service).

---

## Security Requirements

### Authentication

**[MUST]** Authentication is implemented behind a pluggable `AuthProvider` interface. The MVP ships username/password with session/JWT issuance; the user model includes an external-identity field so an OIDC provider could be added later without schema or API changes. No OAuth flow is implemented in the MVP.

### Authorization

**[MUST]** Fixed, platform-defined RBAC roles, enforced server-side on every API request from Phase 1 onward:

| Capability | Agent | Tenant Admin | Read-Only | Platform Admin |
|---|---|---|---|---|
| View tenant records (leads → policies) | ✓ | ✓ | ✓ (PII masked, no reveal) | ✗ |
| Create / edit tenant records | ✓ | ✓ | ✗ | ✗ |
| Claim leads / manage own tasks | ✓ | ✓ | ✗ | ✗ |
| Reassign leads & tasks | ✗ | ✓ | ✗ | ✗ |
| Reveal masked PII (audited) | ✓ | ✓ | ✗ | ✗ |
| Replay / discard DLQ items | ✗ | ✓ (own tenant) | ✗ | ✓ (cross-tenant) |
| View tenant config (read-only) | ✗ | ✓ | ✗ | ✗ |
| View audit logs | ✗ | ✓ | ✓ | ✗ |
| View funnel / integration dashboards | ✓ | ✓ | ✓ | ✗ |
| Platform health page, demo controls | ✗ | ✗ | ✗ | ✓ |

**Ownership rule:** all agents in a tenant can view all tenant records; lead/opportunity assignment governs task routing, notifications, and dashboards — not visibility. (Owner-scoped visibility is a documented possible extension, not built.)

---

## PII Protection

**[MUST]** PII handling is a core showcase; the controls are specific:

### Field Protection Matrix

| Field | At-rest protection | Notes |
|---|---|---|
| First / Last Name | Database-at-rest encryption only | Kept searchable for list views and name search |
| Email / Phone | Application-layer encryption + **HMAC blind index** of the normalized value | Blind index supports exact-match duplicate detection without decryption |
| Address | Application-layer encryption | |
| Date of Birth | Application-layer encryption; derived `age_band` stored in plaintext | Age band feeds eligibility and enrichment display |
| Policy Number | Application-layer encryption | |
| Mock Medicare ID | Application-layer encryption; **always rendered masked** (`***-**-1234`) | The PII-handling centerpiece |
| Application details (beneficiary, health answers) | Application-layer encryption | |

### Key Management

Envelope encryption: a per-tenant data key wraps field-level encryption, and a master key supplied via environment configuration wraps the data keys (KMS-ready). Per-tenant keys reinforce the tenant-isolation story.

### Masking Matrix

| Field | Agent / Tenant Admin | Read-Only | Platform Admin |
|---|---|---|---|
| Email, Phone, DOB, Address, Policy Number | Masked by default; **click-to-reveal** publishes an audited `pii.revealed` event | Always masked, no reveal | No access to tenant PII |
| Mock Medicare ID | Always masked (no full reveal in any UI) | Always masked | No access |

### Additional Controls

- Tenant-scoped access control on every read/write.
- Audit logging of sensitive operations (including every reveal).
- No raw PII in application logs or event payloads (enforced by the event payload convention).
- All seeded and visitor-entered data is synthetic; no real SSN, health, or Medicare data exists anywhere in the system (see Out of Scope).

---

## Audit Logging

**[MUST]** Capture: user actions, record modifications, lead conversions and duplicate resolutions, application submissions, policy creation, CRM sync outcomes, integration failures, authentication events, role-assignment changes, PII reveals, and Platform Admin cross-tenant reads.

Audit records include: timestamp, tenant, user, event type, entity type, entity reference, and outcome.

Rules:

- Audit records store entity references and the **names** of changed fields — never raw PII values.
- Audit records are **append-only**.
- Viewing or exporting audit logs is itself an audited sensitive operation.
- The audit log view renders no unmasked PII (safe for the demo walkthrough).

---

## Observability

**[MUST]** An in-app, event-sourced **metrics read model** (counters/aggregates built from domain events) powers all dashboards. There is no separate analytics sidecar or warehouse export.

Track: queue depth, integration success/failure rates, retry counts, event throughput, lead conversion funnel, and policy creation metrics.

**Dashboards (exactly three):**

1. **Funnel progression** (per tenant), keyed off events: `lead.created` → `lead.qualified` → `lead.converted` → `quote.completed` → `application.started` → `policy.created`. The quote step is omitted for tenants that disable the *Quoted* stage. **[SHOULD]** Adds pipeline value by stage (sum of `estimated_annual_premium` per canonical stage); the opportunity list supports sorting by value and target close date.
2. **Integration health** (per tenant): sync success rates, retries, failed jobs, and the DLQ (replay/discard actions for Tenant Admins; read-only for Agents and Read-Only users).
3. **Platform health page** (Platform Admin only): queue depth, failure counts, event throughput, and the cross-tenant DLQ with replay/discard — aggregates and metadata only, no tenant PII.

Agent-performance and tenant-activity dashboards are out of MVP scope (stretch).

---

## Demo Experience

The demo must be **deterministic and repeatable** — every showcase moment observable on demand by a cold visitor.

### Landing & Orientation

**[MUST]** The application root renders a landing page **before tenant selection** that states, on one screen: what PolicyFlow is (a multi-tenant insurance workflow orchestration platform with CRM integrations, fully simulated), why it was built (the skills demonstrated: insurance workflow orchestration, CRM object relationships, multi-tenant isolation, event-driven integrations, PII handling), that everything is simulated and safe to click, the expected time commitment, and a single primary call-to-action into tenant selection. The tenant-selection screen describes each tenant's specialization and why two tenants exist (the differentiation and isolation proof). Built in Phase 1 as part of the demo shell (a minimal placeholder version is live from Phase 0 — see MVP Scope).

**[SHOULD]** The landing page offers two paths: the full walkthrough and a **"5-minute highlights"** express path (5–7 steps: intake + enrichment, duplicate resolution, PII reveal with audit, sync failure with DLQ replay, the correlation trace, and the cross-tenant isolation proof). *(P4, with guided-demo refinement)*

### Demo Access Model

**[MUST]** Selecting a demo tenant auto-creates a demo session signed in as a seeded **Agent** (no credentials typed). A visible **role switcher** lets the visitor flip between Agent, Tenant Admin, Read-Only, and Platform Admin personas within the session. RBAC remains fully enforced server-side per assumed role — the switcher changes identity, not enforcement. Seeded demo users per tenant: two Agents (so reassignment is demonstrable), one Tenant Admin, one Read-Only user; one global Platform Admin.

### Demo Sessions and Data Lifecycle

**[MUST]**

- Visitor-created records are tagged with a `demo_session_id`. Each visitor's lead-to-policy flow operates on their own session's records, layered on top of **shared read-only seed data** — concurrent visitors never collide.
- Demo-control actions (renewal sweeps, failure simulation, reset) triggered from a visitor's role-switched Platform Admin persona are **session-scoped** — "reset" purges only that session's records. The global canonical reset is not reachable through the demo role switcher.
- Sessions expire after 24 hours; expiry purges session-created records (cascading across the full object graph, including session-tagged sidecar records such as sync activity and rendered notifications). Seeded data, seeded history, and seeded audit/metrics records survive.
- Tenants also reset to canonical seed state nightly, and on demand by the real (non-demo) operator.
- **Session visibility:** a persistent session indicator (e.g. header badge "Demo session — expires in 23h") with an explainer describing the sandboxing model: session-tagged records layered over shared read-only seed data, concurrent-visitor isolation, session-scoped demo controls and reset, expiry purging across core and sidecar stores. Session-created records carry a subtle "created in your session" marker on lists and detail views; session-scoped overlays (e.g. a seeded policy presented as *Renewal Due*) are labeled as overlays.
- **Graceful expiry:** requests carrying an expired or unknown `demo_session_id` receive a friendly "your previous demo session ended — demo data resets every 24 hours" notice with a one-click fresh session (preserving the selected tenant where possible). Deep links to purged session records resolve to this notice, never a raw 404/500. Saved stepper progress restarts cleanly or is reset with the session — it never points at records that no longer exist.

### Seed Data Requirements

**[MUST]** Per tenant: 25–50 contacts across 15–30 households; opportunities distributed across **every** pipeline stage; 10–20 active policies with staggered dates **including several already inside renewal windows**; 60–90 days of historical domain events and CRM sync records with a realistic (~5%) failure rate; several unassigned leads awaiting qualification; and a designated **duplicate-bait contact** (e.g. Margaret Chen, `mchen@example.com`). Every dashboard and list view must render non-trivially from seed data alone.

### Guided Demo

**[MUST]** A persistent, dismissible guided-demo stepper overlays the app, tracking walkthrough progress with "next step" prompts and deep links. Built in Phase 1 as part of the demo shell, not an afterthought.

**Prefill buttons (intake form):** every deterministic trigger is one click away — no deterministic trigger may exist only in documentation:

| Button | Prefill | Expected outcome |
|---|---|---|
| "Typical lead" | A clean synthetic identity | Happy-path intake and enrichment |
| "Try a duplicate scenario" | The duplicate-bait identity | Duplicate flag + resolution flow |
| "Simulate a declined application" | An email containing `deny` | `application.declined` on submission; Opportunity returns to *Quoted*; superseding Application demoable |
| "Simulate a CRM sync failure" | An email containing `fail` | `simulate_failure` set on the record's sync events; retries → DLQ → replay |

Each button is labeled with what will happen; the magic-input buttons carry an explainer noting that core detects the magic input at publish time and sets a flag on the event envelope, so sidecars never inspect raw PII.

**Demo scenario reference:** a panel reachable from the stepper and from a persistent help icon lists every magic input, Platform Admin demo control, and demo time control with its exact trigger and expected observable outcome.

### Engineering Explainers

The demo must explain its own engineering. Features alone are insufficient: a reviewer must see *how* the system is built without leaving the app.

**[MUST]**

- **Explainer affordance:** every showcase surface — intake/enrichment, lead conversion, duplicate flag and resolution, masked-PII reveal, event timeline, end-to-end trace view, DLQ, CRM sync activity, dashboards, and the tenant switch — carries an info-icon affordance opening a dismissible popover/panel stating: (a) the pattern name, (b) how PolicyFlow implements it in 1–3 sentences referencing the actual mechanism (e.g. transactional outbox, RLS, blind index, envelope encryption, per-consumer retry), and (c) what in the visible behavior is real versus simulated. Explainers never block the workflow and render identically for every role.
- **Stepper notes:** every guided-stepper step carries a short "what you're seeing / how it's built" note linking to the relevant explainer.
- **CRM-parallel annotations:** screens embodying a standard CRM pattern name the real-world equivalent:
  - The conversion screen explains that conversion mirrors Salesforce lead conversion — Lead frozen read-only and stamped with converted-record IDs (the `ConvertedContactId` / `ConvertedAccountId` / `ConvertedOpportunityId` analog), with Contact/Household(Account)/Opportunities created atomically.
  - The Household page explains Household-as-Account (B2C person-account-style) modeling and why B2B account hierarchies were deliberately scoped out.
  - The Opportunity pipeline explains canonical stages vs tenant display labels as the analog of Salesforce stage API names vs labels.
  - The duplicate-resolution screen names its parallel to CRM duplicate/matching rules.

  These annotations lie on the guided walkthrough path; their visibility is part of the corresponding steps' how-it's-built notes.
- **Simulated badges:** every simulated integration surface — carrier quote results, enrichment results, CRM sync records and sync activity, simulated carrier application decisions, and the outbox — displays a "Simulated" badge whose popover states: (a) what is mocked, (b) what surrounding machinery is real (message broker, per-consumer retries, DLQ, field-level encryption, RLS, audit), and (c) the adapter seam where a production implementation would plug in (e.g. `CRMAdapter`: `MockCRMAdapter` today, `SalesforceAdapter`-shaped). The demo never presents a simulated integration as real, and never lets a real mechanism be mistaken for a mock.
- **"How it's built" page:** a persistent page — linked from the stepper's final step and from a header/footer link on every page — containing: an annotated system diagram (core, broker, four sidecars, mock CRM) marking real vs simulated; an entity-relationship rendering of the Domain Model Decisions with the deliberate simplifications and why; a workflow map rendering the Workflow Orchestration Model (processes, decision points, edge cases); an index of every Technical Showcase Goal pattern deep-linking to the screen and explainer demonstrating it; the project motivation; the author's name and contact/portfolio link; and links to the public repository, this requirements document, and the TDD. Repository and author links also appear in the global footer.
- **Phasing:** the explainer shell, badge component, and "How it's built" page shell ship in Phase 1 alongside the stepper shell; explainer copy, CRM-parallel annotations, and showcase-index entries are seed/content data delivered with each phase's demoable slice.

### Walkthrough

Each step is tagged with the phase in which it becomes demoable. Per Engineering Explainers, every step also carries a "what you're seeing / how it's built" note:

1. Land on the orientation page: what PolicyFlow is, why it was built, what is simulated; choose the full walkthrough or the "5-minute highlights" path; select a demo tenant (each described with its specialization); land signed in as a seeded Agent with the guided stepper active. *(P1; highlights path P4)*
2. View tenant-specific branding and product lines. *(P1)*
3. Submit a lead through the tenant's public intake form (or use a prefill button). *(P1)*
4. Watch the lead's **event timeline** update live as enrichment runs; see enrichment results and quality score appear on the lead. *(P1 with stub; P3 with real sidecar)*
5. Run the duplicate scenario; resolve it (link / new / reject). *(P1)*
6. Claim the lead from the unassigned queue; qualify it. *(P1)*
7. Convert the lead into Contact, Household, and one Opportunity per product line. *(P2)*
8. Progress an opportunity through the pipeline stages; for Tenant 1, observe the Medicare eligibility gate. *(P2)*
9. Request carrier quotes; review the returned options. *(P2 with stub; P3 real)*
10. Select a quote — observe it create the Application; complete the product-specific step; submit. *(P2)*
11. See the application approved and the Policy created, with policy number and mock Medicare ID rendered masked; try click-to-reveal and note it is audited. *(P2)*
12. Run the decline scenario: intake with the "simulate a declined application" prefill, fast-track it to application submission, and observe `application.declined`, the Opportunity returning to *Quoted*, and selecting a different Quote creating a superseding Application. *(P2; the decline notification appears once the notification center ships in P3)*
13. Observe CRM sync activity for the new records: open the mock CRM record viewer's side-by-side mapping view (internal record → mapping rules → CRM-style payload) and note the external CRM record ID with Create vs Update labeling. *(P3)*
14. Trigger a simulated CRM outage — or use the "simulate a CRM sync failure" prefill for a single-record failure; watch retries execute, see the event land in the DLQ, and (as Tenant Admin) replay it — from the minimal DLQ view in P3, the full integration health dashboard in P4. *(P3)*
15. Run the renewal/AEP sweep; observe the generated Renewal Opportunity and agent Task. *(P2; the notification appears once the notification center ships in P3)*
16. Open the notification center and the simulated outbox to see rendered notifications. *(P3)*
17. Switch to the Read-Only role and observe PII masking with no reveal; switch to Tenant Admin and view the audit log (conversions, reveals, sync attempts — no raw PII). *(P1 role switch; P4 audit viewer UI)*
18. Switch to the second tenant: different branding, product lines, stage labels, and field mappings on the same screens — and confirm the records just created in Tenant 1 are absent (**isolation proof**). *(P1–P2)*
19. View the funnel and integration health dashboards. *(P4)*
20. Open the end-to-end event trace: every event from `lead.created` to `crm.sync.completed`, tied by `correlation_id`. *(P2 onward, growing richer per phase)*
21. End on the **"How it's built" page** (linked from the stepper's final step and the global footer): annotated system diagram, domain-model ER view, the showcase-pattern index deep-linking back into the app, and links to the repository and the author. *(P1 shell; content grows per phase)*

### Async Visibility

**[MUST]** Two UI surfaces make event-driven processing observable: (a) a **per-record event timeline** on lead/opportunity/policy detail pages showing each domain event and sidecar reaction with status and timestamps, updating live (polling or websocket); (b) the correlation-ID **end-to-end trace view** (step 20). Without these, async work is invisible — they are requirements, not polish.

---

## Technical Constraints

- The remaining application-level stack decisions (broker choice, database engine, encryption libraries, ORM) are **deliberately deferred to the TDD** — this document constrains behavior, not application technology. **The application language/framework and deployment/infrastructure decisions are the exception:** they are committed below, and the TDD must design within them.

### Application Stack

**[MUST]** These decisions are committed at the requirements level:

- **Frontend:** **React** single-page application, served by nginx and reverse-proxied per the Deployment & Infrastructure stack diagram.
- **Backend:** **Python** with **FastAPI** for the core application and all four sidecar services. The event-driven boundary between core and sidecars (separate worker processes within one repository, communicating over a real message broker) is unchanged; FastAPI is the in-process web/service framework on each.
- Hard constraints the TDD must honor:
  - The entire system runs locally with a single command (e.g. `docker-compose up`), fully seeded.
  - Sidecars are separate worker processes/modules **within one repository**, communicating over a real message broker. The event-driven boundary is the requirement — separate deployments/repos are not.

### Deployment & Infrastructure

**[MUST]** These decisions are committed at the requirements level:

- **Containerized stack:** every runtime component is a container in a single Docker stack definition — `nginx -> frontend -> core app + sidecar services -> message broker + database(s)` — with nginx as the sole public entry point, reverse-proxying to the frontend and API. The same stack definition runs locally and in the cloud (local/production parity); the single-command local run uses it. Scheduled jobs (nightly reset, session expiry, renewal sweeps) run inside the stack — no host cron or external schedulers — preserving parity.
- **Hosting:** one always-on AWS **EC2** instance (small instance class — the footprint stays inexpensive) hosts the production Docker stack. Always-on means the demo link never cold-starts. There is no deployed dev environment: **dev is the local Docker stack** via the single-command run.
- **Infrastructure as code:** every AWS resource (EC2, networking/security groups, IAM, Route 53 records, pipeline resources, artifact storage) is provisioned via **Terraform**. No console-managed resources, with two sanctioned, documented exceptions: the pre-existing Route 53 hosted zone (referenced by Terraform — data source or import — never created), and one-time interactive bootstrap steps Terraform cannot perform (e.g. authorizing the CodePipeline GitHub connection).
- **Secrets:** secret values (the master encryption key, database and broker credentials) live in **AWS SSM Parameter Store** as SecureStrings, read by the stack at deploy/boot. The parameter resources are Terraform-provisioned, but the values are injected out-of-band — they never appear in the repository, the Terraform code, or Terraform state.
- **DNS & TLS:** production is served over HTTPS on the registered domain **`policyflow.joeyshub.com`** (a subdomain of the author's existing `joeyshub.com`) through the existing **Route 53** hosted zone — Terraform adds the record but never creates the zone. The whole platform lives behind this one hostname; the single nginx entry point reverse-proxies both the SPA and the API, and no feature requires additional subdomains (sidecars communicate over the internal broker, and tenants are selected in-app, not per-subdomain). Prerequisite: `joeyshub.com` must be resolvable from Route 53 — either the apex zone lives there, or `policyflow.joeyshub.com` is delegated to a Route 53 hosted zone via NS records. TLS terminates at nginx with a single certificate for this host; the certificate mechanism is a TDD decision.
- **CI/CD:** pushes to GitHub trigger **AWS CodePipeline**, which builds the stack and deploys to the EC2 host via **CodeDeploy** (which branch triggers a production deploy is a TDD decision). Every deploy is hands-off end-to-end — schema migrations and seed/configuration updates run as deploy steps, never manually (mechanism is a TDD decision). Deploys may reset the database: re-seeding to canonical state on deploy is acceptable, and nothing requires data to survive a deploy before go-live.

---

## Technical Showcase Goals

Business-process orchestration (explicit lifecycle state machines, attributable decision points, modeled edge cases), CRM domain modeling, object relationship complexity, multi-tenant design with a committed isolation strategy, tenant-specific business configuration, event-driven architecture with explicit delivery semantics, integration sidecar patterns, background job processing, secure PII handling (field-level encryption, blind indexes, masking, audited reveals), auditability, observability, and production-minded system design.

---

## MVP Scope

This section is **normative**.

**[MUST]** Build order and decomposition rules (binding on the TDD and the epic plan):

- The project is decomposed **first into the phases below, then each phase into epics**. Epics never span phases.
- **Skeleton first:** Phase 0 puts the thinnest end-to-end slice live — provisioned infrastructure, working pipeline, minimal pages — before any feature work. Every later phase layers features onto a system that is already running and deployable — the Phase 0 skeleton live in production, subsequent work verified on the local stack.
- **Physically testable phases:** each phase ends in a demoable slice (see walkthrough step tags; Phase 0's slice is defined by its exit test) exercisable by hand in a browser on the local stack — the dev environment. The pipeline keeps production deployable at any time (proven by the Phase 0 exit test); pushing to production before go-live is at the author's discretion.
- Epics within a phase are ordered so the system remains runnable and deployable after every epic.

### Phase 0: Walking Skeleton & Deployment Pipeline [MUST]

The entire delivery path is proven before features exist:

- Repository + Docker stack definition (nginx, frontend, core-app placeholder, broker, database) running locally via the single command
- Terraform provisioning of all AWS resources (EC2, networking, IAM, Route 53 records, pipeline resources)
- CodePipeline + CodeDeploy wired to GitHub pushes, deploying to production
- Minimal landing page and minimal tenant-selection screen (placeholder versions of the Landing & Orientation screens) served over HTTPS on the production domain
- **Exit test:** a change pushed to GitHub appears at the production URL with no manual steps

### Phase 1: Foundations & Core Platform [MUST]

Foundations cannot be retrofitted; they precede all feature work (only the Phase 0 skeleton comes before them):

- Authentication (username/password, seeded users, `AuthProvider` interface) and server-side RBAC enforcement
- Tenant-scoping middleware + RLS policies; `tenant_id` on every entity
- Field-level encryption + blind indexes (the schema decisions), masking rendering
- Audit-event emission from day one
- Event bus with envelope + **inline stub consumers** (enrichment stub returning canned results, sync-logger stub) behind the same events Phase 3 will serve
- Per-record event timeline on the lead detail view
- Landing & orientation page; tenant selection with tenant descriptions; branding; demo access model + role switcher; guided stepper shell with the prefill row and demo scenario reference panel
- Engineering-explainer shell, "Simulated" badge component, and "How it's built" page shell (explainer copy, CRM-parallel annotations, and showcase-index entries ship as content with each phase's demoable slice)
- Lead intake (fields, validation, abuse controls), unassigned queue + claiming, qualification (qualify/reject), deterministic duplicate detection + resolution
- Seed data + demo session sandboxing + reset; session indicator, session-record markers, and graceful expired-session handling

### Phase 2: Domain Workflow [MUST]

- Lead conversion (Contact/Household/Opportunity creation)
- Opportunity pipeline with canonical stages + product-specific rules (eligibility gate, beneficiary, health questions); pipeline value fields (`estimated_annual_premium`, `target_close_date`)
- Quotes (stubbed quote generation), quote-selection → Application, application lifecycle, policy creation
- Renewal generation (anniversary job + AEP sweep) with demo time controls; cross-sell prompt
- Event timeline extended to opportunities and policies + correlation-ID trace view

### Phase 3: Integration Sidecars [MUST]

Real sidecar services replace the Phase 1–2 stubs behind the same events:

- CRM Sync Service (tenant field mappings with the side-by-side mapping viewer, external-ID upsert correlation, retry, DLQ, replay, failure simulation)
- Enrichment Service (consumer-data outputs, quality score, eligibility flag)
- Carrier Quote Service (carrier mapping table)
- Notification Service (notification center + simulated outbox)
- Minimal DLQ list with replay/discard actions (the full dashboard arrives in Phase 4)

### Phase 4: Observability & Polish [MUST]

- Funnel and integration health dashboards (full DLQ replay UI); platform health page
- Audit log viewer UI
- Pipeline value by stage on the funnel dashboard; opportunity list sorting by value and target close date **[SHOULD]**
- Inbound CRM webhook demo control ("simulate inbound CRM change" — see CRM Sync Service) **[SHOULD]**
- Seed/demo polish: guided-demo refinement, the "5-minute highlights" express path, dashboard-ready historical data **[SHOULD]**

---

## Stretch Goals [COULD]

- Tenant Admin **editing** UIs for branding, pipeline labels, and field mappings (MVP renders config read-only)
- **Richer inbound CRM sync** beyond the canned phone-change scenario (now a Phase 4 **[SHOULD]** — see CRM Sync Service): additional inbound update types, inbound record creation, configurable conflict-resolution strategies
- Contact merge with survivorship rules and child re-parenting
- Agent-performance and tenant-activity dashboards
- Owner-scoped record visibility mode

---

## Success Criteria

The project succeeds if a cold visitor, guided by the app itself, can experience:

```text
Tenant-specific lead intake (deterministic duplicate + enrichment moments)
  -> CRM-style object relationships with committed cardinality
  -> Orchestrated workflows with product-specific rules, decision points, and edge cases
  -> Quote -> Application -> Policy -> observable Renewal generation
  -> Sidecar integrations (sync, retry, DLQ replay) on demand
  -> Secure PII handling (masking, audited reveal) visible per role
  -> Audit logging without raw PII
  -> Funnel + integration health dashboards rendered from real events
  -> Visible tenant differentiation AND an isolation proof across both tenants
  -> In-app engineering explanations (pattern names, CRM parallels,
     real-vs-simulated boundaries) ending on the "How it's built" page
```

The final demo should make it clear that the project is not a UI mockup, but a functional system designed around realistic insurance workflow orchestration, CRM complexity, and enterprise integration patterns — with every claim in this document observable in the running application. Engineering transparency is itself a success criterion: a cold visitor must be able to name the pattern behind every showcase moment without leaving the app, and must end the walkthrough one click from the repository, the design documents, and the author.
