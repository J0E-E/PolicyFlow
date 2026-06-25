# Lead Conversion (P2.1) — Business Requirements

## 1. Overview
Let an agent turn a **qualified** lead into a live customer record in one atomic action.
Converting creates a Contact, places that Contact in a Household (new or an existing one),
opens one sales Opportunity per product line of interest, carries the lead's notes over as
a follow-up Task, and freezes the original lead. This is Milestone 2's first phase: it
births the core CRM entities (Contact, Household, Opportunity, Task) that every later sales
workflow builds on, and it delivers the demo's "step 7" moment — a lead visibly becoming a
customer with an open pipeline.

## 2. Background & Problem
Through Milestone 1, agents can intake, claim, and qualify leads — but a qualified lead is a
dead end: there is no customer, no household, and no sales pipeline to act on. Nothing
downstream (opportunities, quotes, policies, renewals) can exist until a lead becomes a
Contact. Conversion is the hinge between *prospecting* and *selling*, and it must be a
single trustworthy action: all-or-nothing, irreversible, and leaving a clean trail.

## 3. Objectives
- An agent converts a qualified lead into a customer in **one atomic action** — either
  everything is created or nothing is.
- Every conversion yields a Contact, a Household (created or linked), and **at least one**
  Opportunity owned by the converting agent.
- The original lead is **frozen** after conversion — read-only, stamped with what it became.
- Conversion is **traceable**: the lead's correlation thread carries onto every created
  entity, and the act announces itself through the standard event stream.
- Everything created stays inside the right tenant and demo session — no cross-leakage.

## 4. Scope

Everything below is scoped to a single tenant and tagged to the active demo session.

- **In scope:**
  - A **review-and-confirm** conversion screen: the agent sees the lead's mapped details
    (read-only), chooses to create a new Household or link an existing one, confirms the
    product lines, and commits.
  - Creating a **Contact** from the lead's captured details (name, email, phone, address,
    date of birth, lead source).
  - Creating a **new Household** (auto-named from the contact's last name) **or linking** to
    an existing one via a name search; on a duplicate-flagged lead, the matched contact's
    household is **pre-selected**.
  - Creating **one Opportunity per product line of interest**, owned by the converting
    agent.
  - Carrying the lead's notes over as a **note-type Task** on the new Contact (only when
    notes exist).
  - **Freezing the lead**: status `Converted`, read-only, stamped with the new contact and
    opportunity references.
  - Announcing the conversion through the standard event stream: lead converted, contact
    created, household created (when new), and one opportunity-created per opportunity.

- **Out of scope:**
  - Rich Task management — queue, due dates, assignment routing *(later phase, P2.4)*.
  - Opportunity stage progression and per-tenant stage configuration *(later phase, P2.2)*.
  - Address-based household matching — the agent picks manually.
  - **Contact merge / dedup** — a duplicate lead still produces a *new* Contact; only the
    household is shared.
  - Editing the lead's field values during conversion, and renaming households.
  - Un-converting or reversing a conversion.

## 5. Users & Stakeholders
- **Primary:** the **agent** who owns (has claimed) the qualified lead — the only person who
  can convert it, and the owner of the resulting Opportunities.
- **Demo operator / stakeholders:** rely on the "step 7" walkthrough to show a lead becoming
  a customer cleanly and on the event trail being honest.
- **Downstream phases (P2.2–P2.5):** consume the Contact / Household / Opportunity / Task
  entities and the events this phase introduces.

## 6. Functional Requirements
1. An agent can open **Convert** on a lead **only when** the lead is `Qualified` and the
   agent is its current holder.
2. Conversion is **blocked unless at least one product line of interest** is selected; if the
   lead has none recorded, the agent must choose one on the conversion screen before
   committing.
3. The conversion screen shows the lead's mapped Contact details **read-only** (values are
   not editable during conversion).
4. The agent chooses, on that screen, to **create a new Household** or **link an existing
   one**:
   - Existing households are found by a **household-name search** within the tenant, with
     each match showing its members so the agent can recognize it.
   - If the lead was flagged a duplicate at intake, the matched contact's household is
     **pre-selected** (the agent may override).
   - A newly created household is **auto-named** "*<LastName>* Household".
5. On commit, the system **atomically**: creates the Contact; creates or links the Household;
   creates **one Opportunity per selected product line** (owned by the converting agent);
   creates a **note-Task** from the lead's notes **if notes exist**; and freezes the lead as
   `Converted` (read-only), stamped with the new contact and opportunity references.
6. On commit the system **announces**: lead converted, contact created, household created
   (only when a new one was made), and one opportunity-created per Opportunity — all as part
   of the same atomic action.
7. On a **duplicate-flagged** lead, conversion still creates a **new Contact**; only the
   existing household is reused.
8. If conversion **fails** for any reason, **nothing is created**, the lead remains
   `Qualified` and editable, and the agent is told it did not complete and can retry.

## 7. Constraints & Non-Functional Needs
- **Atomicity:** conversion is all-or-nothing — no partial customers, no orphaned entities,
  no events emitted on failure.
- **Irreversibility:** a converted lead is terminal and read-only; there is no un-convert in
  this phase.
- **Isolation:** every created entity and every emitted event stays within the converting
  agent's tenant and carries the active demo session, with nothing visible across tenants or
  sessions.
- **Traceability:** the originating lead's correlation thread is carried onto each created
  entity and stamped on every emitted event.

## 8. Assumptions
- Qualified leads, intake duplicate-flagging, and the event/announcement mechanism already
  exist from Milestone 1 (P1.7 and P1.5).
- A lead's captured details are sufficient to populate a Contact; what the lead holds is what
  converts (no enrichment or correction step here).
- Product lines of interest are captured on the lead at intake/qualification.
- A Contact belongs to exactly one Household (one-household-per-contact, per the domain
  model), and two Contacts may share a Household.

## 9. Success Criteria / Acceptance
- **Walkthrough step 7 passes:** an agent converts a qualified lead and, in one action, a
  Contact appears, a Household is created or linked, one Opportunity per product line is
  opened under the agent's ownership, the lead's notes (if any) appear as a Task on the
  Contact, and the lead is frozen `Converted` and read-only — stamped with what it became.
- The conversion announces lead-converted, contact-created, household-created (if new), and
  opportunity-created ×N.
- The duplicate path pre-selects the matched household and still yields a new Contact.
- A forced failure leaves the lead untouched and creates nothing.
- A second tenant / different demo session sees none of the above.

## 10. Open Questions
None outstanding at the business level. Technical decisions — entity schemas and migrations,
the transactional service design, the polymorphic Task model, event payloads, the household
search/picker implementation, and correlation/causation propagation — are deferred to
`2-requirements-to-tdd`.
