import { InfoCircle } from "iconoir-react";

interface ExplainerIconProperties {
  /** Required so the glyph is uniquely targetable (CLAUDE.md). */
  id: string;
}

// The info glyph that signals an explainer affordance (Guide §6.2 — an info-icon
// on every showcase surface). A thin wrapper over iconoir's InfoCircle, pinned to
// a compact 16px so it sits inline with body text and the masthead controls (the
// same size-pinning idiom the persona-chip / view-only glyphs use). It is purely
// decorative: aria-hidden, because the wrapping ExplainerPopover trigger carries
// the accessible name ("Explain: …"). Styling lives in styles/explainer.css.
export default function ExplainerIcon({ id }: ExplainerIconProperties) {
  return (
    <span id={id} className="explainer-icon" aria-hidden="true">
      <InfoCircle width={16} height={16} aria-hidden="true" />
    </span>
  );
}
