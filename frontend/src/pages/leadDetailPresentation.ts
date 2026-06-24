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

// ---- Event-timeline timestamps (P1.9 Epic 1) --------------------------------
//
// The timeline shows each event's time twice: a full-words RELATIVE label inline
// ("just now" / "2 hours ago" / "3 days ago"), and a fixed-width UTC stamp on hover
// (the row's `title`). Both are pure and JSX-free so they unit-test on their own,
// beside the other detail-presentation helpers (React philosophy — keep the
// component focused on layout). The date-only `leadDate` won't do here: a timeline
// needs time-of-day precision, so these are separate.

// The thresholds, in seconds, for the relative label's coarse buckets. Kept full-word
// and calm (the Guide's natural-language register) — no "1m"/"2h" shorthand.
const SECONDS_PER_MINUTE = 60;
const SECONDS_PER_HOUR = 60 * 60;
const SECONDS_PER_DAY = 24 * 60 * 60;

/**
 * A full-words relative label for how long ago an ISO timestamp was, measured from
 * `now` (defaulting to the current time — passed explicitly only by tests for
 * determinism). Buckets, coarsest-readable: under a minute → "just now"; under an
 * hour → "N minute(s) ago"; under a day → "N hour(s) ago"; otherwise "N day(s) ago".
 * A future or unparseable timestamp falls back to "just now" so the cell never blanks
 * or shows a negative count. Singular/plural agree ("1 hour ago", "2 hours ago").
 */
export function leadEventRelativeTime(
  isoTimestamp: string,
  now: Date = new Date(),
): string {
  const occurredAtMilliseconds = Date.parse(isoTimestamp);
  if (Number.isNaN(occurredAtMilliseconds)) {
    return "just now";
  }

  const elapsedSeconds = Math.floor(
    (now.getTime() - occurredAtMilliseconds) / 1000,
  );
  if (elapsedSeconds < SECONDS_PER_MINUTE) {
    return "just now";
  }
  if (elapsedSeconds < SECONDS_PER_HOUR) {
    return pluralizedAgo(Math.floor(elapsedSeconds / SECONDS_PER_MINUTE), "minute");
  }
  if (elapsedSeconds < SECONDS_PER_DAY) {
    return pluralizedAgo(Math.floor(elapsedSeconds / SECONDS_PER_HOUR), "hour");
  }
  return pluralizedAgo(Math.floor(elapsedSeconds / SECONDS_PER_DAY), "day");
}

/** "1 hour ago" / "2 hours ago" — the count, the unit (pluralized when not 1), "ago". */
function pluralizedAgo(count: number, unit: string): string {
  const pluralUnit = count === 1 ? unit : `${unit}s`;
  return `${count} ${pluralUnit} ago`;
}

/**
 * A fixed-width, locale-independent UTC stamp `YYYY-MM-DD HH:MM:SS UTC` for the
 * event row's hover `title`. Time-of-day precision (the relative label is coarse),
 * tabular and stable across locales — every field is zero-padded from the UTC parts,
 * never a `toLocaleString`. An unparseable timestamp returns the input unchanged so
 * the title is never misleadingly blank.
 */
export function leadEventAbsoluteUtc(isoTimestamp: string): string {
  const occurredAt = new Date(isoTimestamp);
  if (Number.isNaN(occurredAt.getTime())) {
    return isoTimestamp;
  }

  const pad = (value: number): string => String(value).padStart(2, "0");
  const year = occurredAt.getUTCFullYear();
  const month = pad(occurredAt.getUTCMonth() + 1);
  const day = pad(occurredAt.getUTCDate());
  const hours = pad(occurredAt.getUTCHours());
  const minutes = pad(occurredAt.getUTCMinutes());
  const seconds = pad(occurredAt.getUTCSeconds());
  return `${year}-${month}-${day} ${hours}:${minutes}:${seconds} UTC`;
}
