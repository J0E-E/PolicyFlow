# QA Checklist — Agent Task Queue

> Manual test pass for the agent Task Queue page (the "Tasks" entry in the left nav): viewing the queue by role, the overdue flag, the related-record link, completing a task, and the permission and edge cases.

This checklist covers everything shipped in Section 2: the Task Queue page an Agent, Tenant Admin, or Read-Only user reaches from the "Tasks" nav entry, the role-shaped view (an Agent sees only their own tasks; a Tenant Admin or Read-Only sees everyone's, with an Assignee column), the one-click Complete that clears a task, and the edge cases around permissions and empty or expired states. Work through the sections in order — later sections assume you can open the queue and read a row.

Each item is a self-contained scenario. Follow the steps and confirm the **Expected:** result exactly.

## Preconditions / Setup

Before starting, get to a known-good state:

- [ ] **Know the personas you'll use.** Each tenant has two Agents ("agent.one" and "agent.two"), one Tenant Admin, and one Read-Only user; a Platform Admin runs the renewal sweeps. Use the masthead persona/tenant switcher to move between them. **Expected:** You can switch persona and tenant from the masthead, and the currently-selected persona and tenant are shown there.
- [ ] **Find the Task Queue.** Sign in as an Agent and look at the left navigation. **Expected:** A "Tasks" entry is present in the left nav; clicking it opens the Task Queue page with a "Tasks" page heading.
- [ ] **Start from a fresh demo session.** Use the workspace reset control in the masthead to reset the demo session. **Expected:** The reset completes and you are on a clean session.
- [ ] **Understand the seeded tasks.** On a fresh session the queue is populated from the seed: in Sunshine, agent.one has a "Follow up on Margaret's Medicare Advantage plan questions." note and agent.two has a "Confirm the supplement premium payment method." note; in Florida, agent.one has a "Review the Familia household's coverage after the new policy." note. **Expected:** These note tasks appear for the matching agent and tenant, and no other tasks are seeded.

Notes for the tester:
- The queue shows only non-completed tasks. Completing a task removes it from the list.
- Switching persona keeps the same demo session, so a task generated while acting as one persona is visible to another persona in the same session (used in "Completing a task").
- A "note" task has no due date and is never overdue; a "renewal review" task (created by a renewal sweep) carries a due date.

## Viewing the queue by role

- [ ] **An Agent sees only their own tasks.** Sign in as agent.one, select the "Sunshine" tenant, and open the Task Queue. **Expected:** The list shows agent.one's own tasks (including the "Follow up on Margaret's…" note) and none of agent.two's tasks; there is no "Assignee" column (every row is yours).
- [ ] **A Tenant Admin sees every task with an Assignee column.** Sign in as the Tenant Admin, select "Sunshine", and open the Task Queue. **Expected:** The list shows every agent's tasks (both agent.one's and agent.two's Sunshine notes), and an "Assignee" column shows each task's assignee username.
- [ ] **A Read-Only user sees every task with an Assignee column.** Sign in as the Read-Only user, select "Sunshine", and open the Task Queue. **Expected:** The list shows every task with the "Assignee" column, exactly like the Tenant Admin view (but with no Complete button — see Permissions & edge cases).
- [ ] **Tasks are ordered soonest-due first, undated last.** As a Tenant Admin on a session that has at least one renewal-review task (run a sweep first — see "Completing a task") alongside the seeded notes, open the queue. **Expected:** Tasks with a due date sort earliest-due first; note tasks (no due date) sort at the bottom of the list.

## Reading a task row

- [ ] **The Type column names the task kind.** Open the queue with both a note task and a renewal-review task present. **Expected:** A seeded or conversion note shows Type "Note"; a sweep-generated task shows Type "Renewal review".
- [ ] **The Due column shows a date or a dash.** Look at the Due column for a note task and for a renewal-review task. **Expected:** A note task shows "—" (no due date); a renewal-review task shows its due date as YYYY-MM-DD.
- [ ] **A renewal-review task links to its opportunity.** Find a renewal-review task and look at its "Related record" cell, then click it. **Expected:** The Related record reads "Opportunity" as a link; clicking it opens that opportunity's detail page.
- [ ] **A note task's related record is plain text.** Look at a seeded note task's "Related record" cell. **Expected:** It reads "Contact" as plain, non-clickable text — there is no contact page to link to yet.
- [ ] **No task is flagged Overdue on a fresh demo.** On a fresh session, open the queue (as any role) with the seeded notes and, optionally, a freshly generated renewal-review task. **Expected:** No row shows a red "Overdue" badge — note tasks have no due date and are never overdue, and a freshly generated renewal's due date is in the future. (A red "Overdue" badge appears on a row only once its due date has passed.)

## Completing a task

- [ ] **A renewal-review task appears for its assignee.** As Platform Admin on a fresh Sunshine session, run the AEP renewal sweep (it reports "Generated 1 renewal, skipped 0."). Then switch persona to agent.one (same session, Sunshine) and open the Task Queue. **Expected:** A new "Renewal review" task assigned to agent.one is in the queue, with a Complete button.
- [ ] **The Complete button clears the task.** From the previous step, click "Complete" on the renewal-review task. **Expected:** The button briefly shows a pending state, then the task disappears from the list (the queue refetches and the completed task no longer shows).
- [ ] **A Tenant Admin can complete anyone's task.** Regenerate a renewal-review task (fresh session, run the AEP sweep as Platform Admin), switch to the Tenant Admin (same session, Sunshine), and open the queue. Click "Complete" on the renewal-review task (assigned to agent.one). **Expected:** The task completes and leaves the list, even though the Tenant Admin is not the assignee.

## Permissions & edge cases

- [ ] **An empty queue shows a calm message.** Sign in as agent.two, select the "Florida" tenant (where no task is assigned to agent.two), and open the Task Queue on a fresh session. **Expected:** The page shows the empty-state message "Your queue is clear — no open tasks." and no task table.
- [ ] **A Read-Only user cannot complete tasks.** As the Read-Only user, open the Task Queue (Sunshine). **Expected:** Every row is visible but no "Complete" button appears on any row — a Read-Only user can view but not complete.
- [ ] **An Agent never sees another agent's task.** Sign in as agent.one (Sunshine) and open the queue; look for agent.two's "Confirm the supplement premium payment method." note. **Expected:** agent.one's queue contains only agent.one's tasks — another agent's task never appears, so there is no way for an Agent to complete it.
- [ ] **A seeded note task cannot be completed in a live session.** As agent.one (Sunshine) on a live session, click "Complete" on the seeded "Follow up on Margaret's…" note task. **Expected:** The completion is rejected — an inline error appears ("We couldn't complete that task — it may have already been completed. Please try again.") and the note stays in the list (seeded baseline tasks are shared and cannot be altered from a demo session).
- [ ] **An expired or absent demo session shows only the shared seeded tasks.** Get into a state with no active demo session (for example, after the session has expired), then open the Task Queue. **Expected:** The queue loads and shows only the shared seeded tasks — none of the session-specific tasks a sweep or conversion created in the previous session appear.
- [ ] **The load-error state offers a retry.** If the task list ever fails to load, look at the page. **Expected:** The page shows "We couldn't load your tasks. Please try again." with a "Retry" button that re-attempts the load.
