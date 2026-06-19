import ButtonLink from "./ButtonLink.tsx";
import ExplainerPopover from "./ExplainerPopover.tsx";
import { surfaceToggleExplainer } from "./explainerContent.ts";

interface SurfaceToggleProperties {
  /** Required so every rendered element is uniquely targetable (CLAUDE.md). The
   *  ButtonLink derives `${id}-label`; the explainer derives `${id}-explainer-*`. */
  id: string;
  /** The in-app route the toggle navigates to (the other surface). */
  to: string;
  /** The worded label — NO arrow. The arrow is decorative chrome added here. */
  label: string;
  /** Which side the decorative arrow sits on: "forward" → trailing "→"
   *  (agent → public site), "back" → leading "←" (site → agent workspace). */
  direction: "forward" | "back";
}

// The persistent surface toggle (Epic 24) — the clearly-marked demo control that
// flips between the Shopper storefront and the Agent workspace, carrying the demo
// session + tenant across (the `pf_session` cookie rides along, so toggling lands
// you still signed-in). It is presentational: the caller supplies the route, the
// worded label, and the arrow direction; this component is mounted in both the
// agent Masthead and the consumer ShopperMasthead.
//
// The toggle reads as a real brand control (Epic 7 `ButtonLink`, "tonal" variant),
// not a plain text link, and is followed by its own "demo convenience" explainer
// (Epic 19 `ExplainerPopover`) — the foundational copy stating the two surfaces are
// genuinely separate front ends in production, and that flipping surface never
// changes who you are. The arrow glyph is decorative (`aria-hidden`), so the
// link's accessible name is just the words.
export default function SurfaceToggle({
  id,
  to,
  label,
  direction,
}: SurfaceToggleProperties) {
  const arrow = (
    <span
      id={`${id}-arrow`}
      className="surface-toggle-arrow"
      aria-hidden="true"
    >
      {direction === "forward" ? "→" : "←"}
    </span>
  );

  return (
    <span id={id} className="surface-toggle">
      <ButtonLink id={`${id}-link`} variant="tonal" to={to}>
        {direction === "back" && arrow}
        {label}
        {direction === "forward" && arrow}
      </ButtonLink>
      <ExplainerPopover
        id={`${id}-explainer`}
        surfaceLabel="the surface toggle"
        content={surfaceToggleExplainer}
      />
    </span>
  );
}
