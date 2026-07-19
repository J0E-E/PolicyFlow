# QA Checklist — Renewal Generation & Overlay

> Manual test pass for the two Platform-Admin renewal sweeps (AEP and anniversary), their idempotent re-runs, and the "Renewal Due" badge shown on a generated renewal's policy.

This checklist covers everything shipped in Section 1: the two renewal sweeps a Platform Admin can trigger from the top masthead, the "Generated N renewal(s), skipped M." result they report, the idempotency guarantee (re-running never double-generates), and the "Renewal Due" badge that appears on a policy after a sweep generates a renewal for it. Work through the sections in order — later sections assume you can run a sweep and read its result.

Each item is a self-contained scenario. Follow the steps and confirm the **Expected:** result exactly (result sentences are worded precisely — check singular vs. plural and the exact numbers).

## Preconditions / Setup

Before starting, get to a known-good state:

- [ ] **Log in as a Platform Admin.** Sign in and use the masthead persona/tenant switcher to select the Platform Admin persona. **Expected:** Two small renewal-sweep icon buttons are visible in the top masthead (next to the workspace reset control). A calendar-style icon opens the AEP sweep; a clock-style icon opens the anniversary sweep.
- [ ] **Start from a fresh demo session.** Use the workspace reset control in the masthead to reset the demo session. **Expected:** The reset completes and you are on a clean session with no previously generated renewals.
- [ ] **Know how to select a tenant.** Use the masthead persona/tenant switcher to choose between the two tenants, "Sunshine" and "Florida". **Expected:** You can switch the selected tenant, and the currently-selected tenant is shown in the masthead.

Notes for the tester:
- Each sweep only acts on your own demo session and the currently-selected tenant. Switching tenants or resetting the session changes what a sweep sees.
- A sweep popover always has a title, one explanatory sentence, a "Run sweep" button, and a "Close" button.
- The result sentence uses singular "renewal" only when the generated count is exactly 1; otherwise it reads "renewals".

## AEP sweep

- [ ] **Open the AEP sweep popover.** As Platform Admin, click the AEP sweep icon button in the masthead. **Expected:** A popover opens titled "Run AEP renewal sweep" with an explanatory sentence, a "Run sweep" button, and a "Close" button.
- [ ] **Run the AEP sweep on Sunshine (fresh session).** Reset the demo session, select the "Sunshine" tenant, open the AEP sweep popover, and click "Run sweep". **Expected:** The popover shows exactly: "Generated 1 renewal, skipped 0." (singular "renewal" because the count is 1).
- [ ] **Run the AEP sweep on Florida (fresh session).** Reset the demo session, select the "Florida" tenant, open the AEP sweep popover, and click "Run sweep". **Expected:** The popover shows exactly: "Generated 0 renewals, skipped 0." (Florida has no Medicare Advantage policy, so nothing is eligible and nothing is skipped.)
- [ ] **Close the AEP popover without running.** Open the AEP sweep popover and click "Close" without clicking "Run sweep". **Expected:** The popover closes and no renewal is generated (a subsequent AEP run on a fresh Sunshine session still reports "Generated 1 renewal, skipped 0.").

## Anniversary sweep

- [ ] **Open the anniversary sweep popover.** As Platform Admin, click the anniversary sweep icon button in the masthead. **Expected:** A popover opens titled "Run anniversary renewal sweep" with an explanatory sentence, a "Run sweep" button, and a "Close" button.
- [ ] **Run the anniversary sweep on Sunshine (fresh session).** Reset the demo session, select the "Sunshine" tenant, open the anniversary sweep popover, and click "Run sweep". **Expected:** The popover shows exactly: "Generated 1 renewal, skipped 0." The count is 1, not 2 — Sunshine has one anniversary-line policy inside its renewal window plus a final-expense policy that never renews, and the final-expense policy generates nothing.
- [ ] **Run the anniversary sweep on Florida (fresh session).** Reset the demo session, select the "Florida" tenant, open the anniversary sweep popover, and click "Run sweep". **Expected:** The popover shows exactly: "Generated 0 renewals, skipped 0." (Florida's anniversary-line policies fall outside the renewal window and its life policies never renew.)
- [ ] **Close the anniversary popover without running.** Open the anniversary sweep popover and click "Close" without clicking "Run sweep". **Expected:** The popover closes and no renewal is generated (a subsequent anniversary run on a fresh Sunshine session still reports "Generated 1 renewal, skipped 0.").

## Renewal Due overlay

- [ ] **See "Renewal Due" on a policy after an AEP sweep.** On a fresh session with "Sunshine" selected, run the AEP sweep (reports "Generated 1 renewal, skipped 0."), then open the newly generated renewal opportunity and view its linked policy. **Expected:** The linked policy shows a "Renewal Due" badge styled as a warning (amber) badge.
- [ ] **See "Renewal Due" on a policy after an anniversary sweep.** On a fresh session with "Sunshine" selected, run the anniversary sweep (reports "Generated 1 renewal, skipped 0."), then open the generated renewal opportunity and view its linked policy. **Expected:** The linked policy shows a "Renewal Due" warning (amber) badge.
- [ ] **The badge is scoped to the session that ran the sweep.** After generating a renewal in one session (badge shows "Renewal Due" on the opportunity's linked policy), reset the demo session (or switch to a different session where no sweep has run), then view that same seeded policy again. **Expected:** The policy shows "Active", not "Renewal Due" — proving the underlying seeded record was never altered and the badge is derived per session.
- [ ] **A final-expense (none-line) policy never shows "Renewal Due".** With "Sunshine" selected, run both sweeps on a fresh session, then open the final-expense policy's opportunity and view its linked policy. **Expected:** The final-expense policy shows "Active" and never shows "Renewal Due" (it never renews).
- [ ] **A life policy never shows "Renewal Due".** With "Florida" selected, run both sweeps on a fresh session, then open a life-line policy's opportunity and view its linked policy. **Expected:** The life policy shows "Active" and never shows "Renewal Due" (life policies never renew).

## Idempotency & re-runs

- [ ] **Immediate AEP re-run is idempotent.** With "Sunshine" selected on a fresh session, run the AEP sweep ("Generated 1 renewal, skipped 0."), then click "Run sweep" again without resetting. **Expected:** The second run reports exactly: "Generated 0 renewals, skipped 1." (the eligible policy is skipped because its renewal already exists).
- [ ] **Immediate anniversary re-run is idempotent.** With "Sunshine" selected on a fresh session, run the anniversary sweep ("Generated 1 renewal, skipped 0."), then click "Run sweep" again without resetting. **Expected:** The second run reports exactly: "Generated 0 renewals, skipped 1."
- [ ] **Re-running both sweeps after both have run skips everything.** With "Sunshine" selected on a fresh session, run the AEP sweep then the anniversary sweep (each "Generated 1 renewal, skipped 0."), then run the AEP sweep again and the anniversary sweep again. **Expected:** Both re-runs report their eligible policy as skipped ("Generated 0 renewals, skipped 1." each); no new renewals are created.
- [ ] **A workspace reset lets the sweep generate again.** After running a sweep to completion (renewals generated), use the workspace reset control, then re-select "Sunshine" and run the same sweep. **Expected:** The sweep generates again — "Generated 1 renewal, skipped 0." — because generation is scoped to the demo session and the reset cleared the prior session's renewals.
- [ ] **Re-run counts are per tenant.** Run the AEP sweep on "Sunshine" ("Generated 1 renewal, skipped 0."), switch to "Florida" and run the AEP sweep ("Generated 0 renewals, skipped 0."), then switch back to "Sunshine" and run the AEP sweep again. **Expected:** The Sunshine re-run reports "Generated 0 renewals, skipped 1." — the Florida run in between did not affect Sunshine's already-generated renewal.

## Permissions & error states

- [ ] **A non-Platform-Admin does not see the sweep buttons.** Using the persona/tenant switcher, switch to an agent persona. Then switch to a tenant-admin persona. **Expected:** In both cases, neither renewal-sweep icon button appears anywhere in the masthead — only a Platform Admin can see or trigger the sweeps.
- [ ] **Running a sweep with no tenant selected fails and stays open to retry.** As Platform Admin with no tenant selected, open a sweep popover and click "Run sweep". **Expected:** An inline error appears — "Could not run the sweep. Please try again." — and the popover stays open so you can select a tenant and retry.
- [ ] **Running a sweep with an expired or absent demo session fails and stays open.** As Platform Admin, get into a state with no active demo session (for example, after the session has expired). Open a sweep popover and click "Run sweep". **Expected:** The inline error "Could not run the sweep. Please try again." appears and the popover stays open, letting you re-establish a session and retry.
- [ ] **The popover stays open after a failure so the tester can retry.** From a failed run (inline error showing), correct the cause (select a tenant / restore a fresh session) and click "Run sweep" again. **Expected:** The popover was never forced closed by the failure; after correcting the cause the retry succeeds and shows the normal "Generated N renewal(s), skipped M." result.

## Seed integrity

- [ ] **Seeded policies read "Active" before any sweep.** On a completely fresh session (reset, no sweep run yet), with "Sunshine" selected, view the seeded policies through their opportunities. **Expected:** All seeded policies show "Active"; none shows "Renewal Due" until a sweep is run in the current session.
- [ ] **The seeded records are untouched by a sweep in another session.** Run a sweep in session A so a policy shows "Renewal Due" on its opportunity's linked policy, then reset to a fresh session B and view the same seeded policy. **Expected:** In session B the policy reads "Active", confirming the sweep only added a session-scoped overlay and never changed the seeded record itself.
- [ ] **Florida's seed produces no renewals from either sweep.** On a fresh session with "Florida" selected, run the AEP sweep and then the anniversary sweep. **Expected:** Both report "Generated 0 renewals, skipped 0." — Florida has no Medicare Advantage policy, its anniversary-line policies are outside the window, and its life policies never renew.
- [ ] **Sunshine's final-expense policy contributes nothing to the anniversary count.** On a fresh session with "Sunshine" selected, run the anniversary sweep. **Expected:** The result is "Generated 1 renewal, skipped 0." — exactly one, from the in-window anniversary-line policy; the final-expense policy is never counted as generated or skipped.
