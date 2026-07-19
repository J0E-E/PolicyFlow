# QA Checklist — Household & Cross-sell

> Manual test pass for the Household pages (the "Households" entry in the left nav): the households index, a household's detail view (contacts, active policies, the "Renewal Due" badge), and the cross-sell prompt — opening a partially-covered household and creating an opportunity for an uncovered line, a fully-covered household showing no prompt, a household with no active policy, and the permission and edge cases.

This checklist covers everything shipped in Section 3: the Households index a user reaches from the "Households" nav entry, the household detail page it links to (contacts, the household's active policies with an overlay-aware "Renewal Due" badge, and the cross-sell prompt), the one-click "Create opportunity" action on each coverage-gap card, and the edge cases around coverage, permissions, and expired states. Work through the sections in order — later sections assume you can open the index and a household's detail page.

Each item is a self-contained scenario. Follow the steps and confirm the **Expected:** result exactly (result sentences are worded precisely — check the exact labels and messages).

## Preconditions / Setup

Before starting, get to a known-good state:

- [ ] **Know the personas you'll use.** Each tenant has two Agents ("agent.one" and "agent.two"), one Tenant Admin, and one Read-Only user; a Platform Admin runs the renewal sweeps. Use the masthead persona/tenant switcher to move between personas and between the two tenants, "Sunshine" and "Florida". **Expected:** You can switch persona and tenant from the masthead, and the currently-selected persona and tenant are shown there.
- [ ] **Find the Households index.** Sign in as an Agent and look at the left navigation. **Expected:** A "Households" entry is present in the left nav; clicking it opens the Households index with a "Households" page heading.
- [ ] **Start from a fresh demo session.** Use the workspace reset control in the masthead to reset the demo session. **Expected:** The reset completes and you are on a clean session.
- [ ] **Understand the seeded households.** On a fresh session each tenant seeds exactly one household: in **Sunshine**, the **Ramirez Household** (contact Margaret Ramirez) — covered for Medicare Advantage, Medicare Supplement, and Final Expense, but **not** for Dental, Vision & Hearing (a partially-covered household); in **Florida**, the **Familia Household** (contact Diego Familia) — covered for all four of its tenant's product lines (a fully-covered household). **Expected:** Each tenant's index lists its one seeded household, and no other household appears until you convert a lead.

Notes for the tester:
- The index and detail pages show the households visible to your demo session: the shared seeded households plus any you create by converting a lead in the current session.
- A cross-sell prompt card appears only for a product line the household has **no active policy** for. When every line is covered — or the household has no active policy at all — the "Cross-sell opportunities" block does not appear.
- "Creating an opportunity" for a cross-sell line makes an Opportunity, not a policy — so it does not itself close the coverage gap. What changes on screen is the card, which flips to a terminal "Opportunity created" state for the rest of your visit.

## Households index

- [ ] **The index lists the tenant's households.** Sign in as agent.one, select "Sunshine", and open the Households index from the nav. **Expected:** The page shows a "Households" heading and a list containing the "Ramirez Household" row; the row shows the household name and its member (Margaret Ramirez).
- [ ] **A row links to the household's detail page.** From the Sunshine index, click the "Ramirez Household" row. **Expected:** The household detail page opens, headed "Ramirez Household".
- [ ] **The index reflects the selected tenant.** Switch to "Florida" and open the Households index. **Expected:** The list now shows the "Familia Household" row (member Diego Familia) and not Sunshine's Ramirez Household.
- [ ] **The empty-state message.** (For reference — not reachable on a fresh seed, since each tenant seeds one household.) Were no household visible to your session, the index would show "No households yet — convert a lead to create one." **Expected:** On fresh seed data the list is never empty; confirm at least the one seeded household is always present.

## Opening a household

- [ ] **The detail page shows the household name and a back link.** Open the Ramirez Household detail page. **Expected:** The page is headed "Ramirez Household" and shows a "← Back to households" link at the top; clicking it returns you to the Households index.
- [ ] **The Contacts section lists the household's people.** On the Ramirez Household detail page, look at the "Contacts" section. **Expected:** The section is headed "Contacts" and lists Margaret Ramirez.
- [ ] **The Policies section lists the household's active policies.** On the Ramirez Household detail page, look at the "Policies" section. **Expected:** The section is headed "Policies" and shows the household's active policies (its Medicare Advantage, Medicare Supplement, and Final Expense policies), each with its status badge reading "Active" on a fresh session (before any sweep).
- [ ] **A not-found household shows a calm message.** In the address bar, open a household URL that doesn't exist (for example `/app/households/00000000-0000-0000-0000-000000000000`). **Expected:** The page shows "This household could not be found." (no error dump).
- [ ] **The load-error state offers a retry.** If the household detail ever fails to load, look at the page. **Expected:** The page shows "We couldn't load this household. Please try again." with a "Retry" button that re-attempts the load.

## Cross-sell prompt — a partially-covered household

- [ ] **A partially-covered household shows one prompt card per uncovered line.** As agent.one on Sunshine, open the Ramirez Household detail page and look at the "Cross-sell opportunities" section. **Expected:** The section is headed "Cross-sell opportunities" and shows exactly one card reading "This household has no Dental, Vision & Hearing coverage." with a "Create opportunity" button (the household's other three lines are covered, so no card appears for them).
- [ ] **Creating an opportunity flips the card to a terminal state.** On the Ramirez Household detail page (as agent.one), click "Create opportunity" on the Dental, Vision & Hearing card. **Expected:** The button briefly shows a pending state, then the card's action is replaced by the text "Opportunity created" — the "Create opportunity" button is gone and does not reappear for the rest of this visit.
- [ ] **The created opportunity is real.** After the previous step, open the Opportunities board (or the agent's task/opportunity surfaces) for Sunshine in the same session. **Expected:** A new Dental, Vision & Hearing opportunity exists for the Ramirez Household — creating the cross-sell opportunity really created an Opportunity record.
- [ ] **The gap is not "closed" by accepting — the card is terminal client-side only.** After creating the opportunity (card shows "Opportunity created"), reload the household detail page. **Expected:** The Dental, Vision & Hearing card reappears with its "Create opportunity" button — because a cross-sell creates an Opportunity, not a policy, the coverage gap is still open, so the suggestion returns on a fresh load. (Within a single visit the card stays terminal; a reload starts the visit over.)

## Cross-sell prompt — no prompt cases

- [ ] **A fully-covered household shows no cross-sell block.** As agent.one on Florida, open the Familia Household detail page. **Expected:** There is **no** "Cross-sell opportunities" section anywhere on the page — every one of the household's product lines is already covered by an active policy, so the whole prompt block is suppressed.
- [ ] **A household with no active policy shows no cross-sell block.** Create a fresh household with no policies yet: as agent.one on Sunshine, convert a lead (which creates a new household and contact but no issued policy). Open that new household's detail page. **Expected:** The "Policies" section reads "This household has no active policies.", and there is **no** "Cross-sell opportunities" section — the prompt requires at least one active policy, so a household with none shows no suggestions.

## Renewal Due badge on a household policy

- [ ] **A swept policy shows "Renewal Due" on the household detail page.** On a fresh session with "Sunshine" selected, sign in as Platform Admin and run the AEP renewal sweep (it reports "Generated 1 renewal, skipped 0."). Then switch persona to agent.one (same demo session, Sunshine) and open the Ramirez Household detail page. **Expected:** In the "Policies" section, the Medicare Advantage policy shows a "Renewal Due" badge styled as a warning (amber) badge; the other policies still read "Active".
- [ ] **The renewal does not remove the cross-sell prompt.** On the same Ramirez Household detail page (after the AEP sweep, with the MA policy showing "Renewal Due"), look at the "Cross-sell opportunities" section. **Expected:** The Dental, Vision & Hearing cross-sell card still appears — a "Renewal Due" policy still counts as covering its own line, and the dental gap is unchanged.
- [ ] **The badge is scoped to the session that ran the sweep.** After the AEP sweep shows "Renewal Due" on the Ramirez MA policy, use the workspace reset control to start a fresh session, then reopen the Ramirez Household detail page. **Expected:** The Medicare Advantage policy reads "Active" again — the badge is derived per session from the sweep, and the underlying seeded policy was never changed.

## Permissions & edge cases

- [ ] **A Read-Only user sees the prompt but cannot create an opportunity.** Sign in as the Read-Only user, select "Sunshine", and open the Ramirez Household detail page. **Expected:** The "Cross-sell opportunities" section and the Dental, Vision & Hearing card are visible, but there is **no** "Create opportunity" button on the card — a Read-Only user can view suggestions but not act on them.
- [ ] **An Agent who does not own the household's policies cannot create the opportunity.** Sign in as agent.two, select "Sunshine", and open the Ramirez Household detail page (agent.one, not agent.two, owns Ramirez's policies). Click "Create opportunity" on the Dental, Vision & Hearing card. **Expected:** An inline error message appears in the "Cross-sell opportunities" section and no opportunity is created; the "Create opportunity" button re-enables so nothing is lost.
- [ ] **Creating an opportunity with no active demo session fails.** Get into a state with no active demo session (for example, after the session has expired). Open the Ramirez Household detail page (the shared seeded household is still visible) and click "Create opportunity" on the Dental, Vision & Hearing card. **Expected:** An inline error message appears in the "Cross-sell opportunities" section and no opportunity is created — a cross-sell opportunity must belong to a demo session.
- [ ] **An already-covered line is never offered.** On the Ramirez Household detail page, confirm the cross-sell section only ever lists lines the household has no active policy for. **Expected:** Cards appear only for uncovered lines (just Dental, Vision & Hearing on Ramirez); a covered line (Medicare Advantage, Medicare Supplement, Final Expense) never gets a card, so there is no way from this page to create a duplicate opportunity for an already-covered line.
