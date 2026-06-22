import type { ReactNode } from "react";

/** The status vocabulary a stamp can carry (Guide §2.2 — the only hues that
 *  signal). The full set lands now (gate decision) so feature phases reuse it
 *  without reopening the component; only `warning` + `neutral` render in P1.6. */
export type StampStatus =
  | "success"
  | "pending"
  | "warning"
  | "error"
  | "neutral";

/** A colored status box: `status` is required, `variant` defaults to "status". */
interface StatusStampProperties {
  variant?: "status";
  status: StampStatus;
}

/** A plain section eyebrow (e.g. "EVENT TIMELINE") — same Stamp type, no box,
 *  no status. */
interface OverlineStampProperties {
  variant: "overline";
  status?: never;
}

type StampTagProperties = (StatusStampProperties | OverlineStampProperties) & {
  /** Required so every rendered element is uniquely targetable (CLAUDE.md).
   *  The label span is `${id}-label`; the optional icon is `${id}-icon`. */
  id: string;
  /** Optional leading glyph. Wrapped `aria-hidden` so the always-present text
   *  label is what conveys meaning (never by color/icon alone, Guide §7). */
  icon?: ReactNode;
  /** The label, authored natural-case — CSS uppercases it so screen readers
   *  read words, not spelled-out letters (Guide §7). */
  children: ReactNode;
  /** Optional native tooltip on the stamp wrapper (e.g. the demo "SHARED SAMPLE"
   *  tag's explanation). Omitted by default, so existing stamps are unchanged. */
  title?: string;
};

// The Guide's rubber-stamp status label (Guide §5, §3 Stamp type) — replaces
// pill chips. One component, two presentations: a colored status box, or a
// plain section overline (the same Stamp type used as an eyebrow). Pure and
// non-interactive; styling lives in styles/stamp-tag.css and the class is a
// plain template (no status→object map in JS), mirroring buttonClassName.
export default function StampTag({
  id,
  variant = "status",
  status,
  icon,
  children,
  title,
}: StampTagProperties) {
  const className =
    variant === "overline"
      ? "stamp-tag stamp-tag-overline"
      : `stamp-tag stamp-tag-${status}`;

  return (
    <span id={id} className={className} title={title}>
      {icon && (
        <span id={`${id}-icon`} className="stamp-tag-icon" aria-hidden="true">
          {icon}
        </span>
      )}
      <span id={`${id}-label`} className="stamp-tag-label">
        {children}
      </span>
    </span>
  );
}
