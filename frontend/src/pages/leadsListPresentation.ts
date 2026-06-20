// Pure presentation helpers for the leads list (Epic 20). These turn raw masked
// lead fields into the short display strings the table cells show. Kept JSX-free
// and separate from the page so each is unit-testable and the page component
// stays focused on layout + data flow (React philosophy).

import type { LeadSource, MaskedLead, ProductLine } from "../api";

/** The human label for a lead's source — `Public` for a self-served Shopper
 *  intake, `Agent` for an agent-entered lead (Guide-plain, not the wire token). */
export function leadSourceLabel(source: LeadSource): string {
  return source === "public_form" ? "Public" : "Agent";
}

/** The owner cell text — the owning agent's username, or an em dash when the
 *  lead is unowned (a queue lead). */
export function leadOwnerLabel(ownerUsername: string | null): string {
  return ownerUsername ?? "—";
}

/**
 * The created-date cell text — a fixed, locale-independent `YYYY-MM-DD` slice of
 * the ISO timestamp. Deliberately a stable fixed date (no relative "2 days ago")
 * so the column reads the same on every render and in tests; the wire already
 * sends an ISO 8601 string, so the date portion is the first 10 characters.
 */
export function leadCreatedDate(createdAt: string): string {
  return createdAt.slice(0, 10);
}

/**
 * The product-line cell text — the lead's selected keys mapped to their human
 * labels via the tenant registry, joined with commas. An unknown key (registry
 * drift) falls back to the raw key so the cell never blanks. Mirrors the
 * created-lead panel's label lookup.
 */
export function leadProductLineLabels(
  lead: MaskedLead,
  productLines: ProductLine[],
): string {
  const labelForKey = new Map(
    productLines.map((productLine) => [productLine.key, productLine.label]),
  );
  return lead.product_lines_of_interest
    .map((key) => labelForKey.get(key) ?? key)
    .join(", ");
}

/**
 * Whether a lead is flagged as a possible duplicate that no one has resolved yet
 * — it points at a matched prior lead (`duplicate_of_lead_id` set) and carries no
 * resolution (`duplicate_resolution` null). The list shows a warning stamp on
 * these; resolving the flag lives on the Epic 21 detail page.
 */
export function isUnresolvedDuplicate(lead: MaskedLead): boolean {
  return (
    lead.duplicate_of_lead_id !== null && lead.duplicate_resolution === null
  );
}

/**
 * Whether a lead can be claimed — it is unowned and still `New` (the queue
 * condition the claim endpoint accepts). A claimed/worked/terminal lead, or one
 * already owned, is not claimable, so its row shows no Claim button.
 */
export function isClaimable(lead: MaskedLead): boolean {
  return lead.owner_user_id === null && lead.status === "New";
}
