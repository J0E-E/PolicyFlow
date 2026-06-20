// Pure presentation helpers for the lead detail page (Epic 21). They turn raw
// masked-lead fields into the short display strings the detail cards show. Kept
// JSX-free and separate from the page so each is unit-testable and the page
// component stays focused on layout + data flow (React philosophy). The list-page
// helpers (leadProductLineLabels / leadOwnerLabel / leadCreatedDate /
// isUnresolvedDuplicate) are reused verbatim from leadsListPresentation.ts — this
// module only holds what is new to the detail surface.

/** The human label for a stored preferred-contact-method value, or `null` when
 *  the lead set no preference. Mirrors the intake forms' CONTACT_METHOD_OPTIONS
 *  (schemas.py `_ALLOWED_CONTACT_METHODS`). An unknown value falls back to itself
 *  so the cell never blanks on registry drift. */
export function leadPreferredContactLabel(method: string | null): string | null {
  if (method === null) {
    return null;
  }
  const CONTACT_METHOD_LABELS: Record<string, string> = {
    email: "Email",
    phone: "Phone call",
    text: "Text message",
  };
  return CONTACT_METHOD_LABELS[method] ?? method;
}

/**
 * The fixed, locale-independent `YYYY-MM-DD` slice of an ISO timestamp — the same
 * stable date format the list uses, applied to detail timestamps (created /
 * updated / a matched lead's created date). The wire sends ISO 8601, so the date
 * portion is the first 10 characters.
 */
export function leadDate(isoTimestamp: string): string {
  return isoTimestamp.slice(0, 10);
}
