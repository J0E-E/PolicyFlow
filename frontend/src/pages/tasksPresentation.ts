// Pure presentation helpers for the task queue (Epic 11). These turn raw task
// wire fields into the short display strings the table cells show. Kept JSX-free
// and separate from the page so each is unit-testable and the page component
// stays focused on layout + data flow (React philosophy).

import type { Task } from "../api";

/**
 * The Type cell text — the raw `task_type` key humanized for display: underscores
 * become spaces and the first letter is capitalized (e.g. `renewal_review` →
 * `Renewal review`, `note` → `Note`). An empty type falls back to an em dash so
 * the cell never blanks.
 */
export function taskTypeLabel(taskType: string): string {
  if (taskType === "") {
    return "—";
  }
  const spaced = taskType.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/**
 * The Due cell text — a fixed, locale-independent `YYYY-MM-DD` slice of the ISO
 * timestamp, or an em dash when the task has no due date (every `note` task).
 * Deliberately a stable fixed date (no relative "in 2 days") so the column reads
 * the same on every render and in tests; the wire sends an ISO 8601 string, so
 * the date portion is the first 10 characters.
 */
export function taskDueDateLabel(dueDate: string | null): string {
  return dueDate === null ? "—" : dueDate.slice(0, 10);
}

/**
 * The Related-record label — the raw `related_entity_type` key humanized (first
 * letter capitalized), e.g. `opportunity` → `Opportunity`, `contact` → `Contact`.
 * Used as the link text for an opportunity task and the plain text for any other
 * related type.
 */
export function relatedRecordLabel(relatedEntityType: string): string {
  if (relatedEntityType === "") {
    return "—";
  }
  return relatedEntityType.charAt(0).toUpperCase() + relatedEntityType.slice(1);
}

/**
 * Whether a task's related record has a live detail surface to link to — only the
 * `opportunity` type does today (the `/app/opportunities/:id` page exists). A
 * `contact` task (no contact page until Epic 14) renders plain text instead of a
 * dead link (the honest-inert convention).
 */
export function isOpportunityTask(task: Task): boolean {
  return task.related_entity_type === "opportunity";
}
