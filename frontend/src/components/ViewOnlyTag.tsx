import { Lock } from "iconoir-react";

interface ViewOnlyTagProperties {
  /** Required so every rendered element is uniquely targetable (CLAUDE.md).
   *  The icon span is `${id}-icon`; the label span is `${id}-label`. */
  id: string;
}

// The persistent "VIEW ONLY" posture tag for the Read-Only persona (Guide §2.4).
// A small inline lock-tag chip — a `Lock` glyph beside a "View only" label — that
// the masthead renders in its left cluster while the Read-Only persona is active,
// so the constrained posture is unmistakable on every /app screen. It is a *cue*,
// never the gate: RBAC stays server-enforced (the visitor literally is the seeded
// read-only user); this is the visible mirror of that fact.
//
// Mirrors the Platform-Admin "OUTSIDE TENANT SCOPE" posture label's shape, but a
// posture tag flags deviation from the normal editable/in-tenant state, so only
// the constrained personas carry one — Agent and Tenant Admin (the normal working
// state) get none (the deliberate Guide §2.4 asymmetry).
//
// NOT built on StampTag: that component is a *status-hue* stamp (the §2.2 signal
// colors). This posture tag is keyed to the Read-Only *persona container* tokens
// (a warm-gray ground), so it deliberately uses its own persona-toned styling
// rather than reusing a status component (recorded so review doesn't flag it).
//
// Styling (styles/app-shell.css) is the Guide's Stamp type on the read-only
// persona-container tokens. Read-Only is always tenant-scoped, so this only ever
// renders on the normal paper masthead (never the inverted Platform-Admin one) —
// no on-ink variant is needed. Pure, presentational, non-interactive (no focusable
// control, no focus-order change); the glyph is `aria-hidden` and the always-present
// text label is what conveys meaning (Guide §7 — never by icon/color alone).
export default function ViewOnlyTag({ id }: ViewOnlyTagProperties) {
  return (
    <span id={id} className="masthead-view-only">
      <span
        id={`${id}-icon`}
        className="masthead-view-only-icon"
        aria-hidden="true"
      >
        <Lock />
      </span>
      <span id={`${id}-label`} className="masthead-view-only-label">
        View only
      </span>
    </span>
  );
}
