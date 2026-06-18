import { useGuidedDocketContext } from "./GuidedDocketContext.ts";

interface GuidedWalkthroughHostProperties {
  /** Required base id for the host region (CLAUDE.md). Kept as the stable seam name
   *  `demo-home-stepper-host` that beat 3 of the demo home points at. */
  id?: string;
}

// The demo-home anchor for the guided walkthrough — beat 3's destination. Epic 17
// repurposed this from the placeholder host card into a slim one-line opener: the real
// 21-step docket now lives as a floating overlay mounted shell-wide in AppShell (so it
// persists across every /app screen and survives navigation), and this opener just
// opens/focuses that same shared docket via GuidedDocketContext.
//
// The stable id `demo-home-stepper-host` and beat 3's "guided walkthrough" reference
// are preserved so nothing that pointed here dead-links. The button reads the shared
// docket state, so its label reflects whether the docket is already open.
export default function GuidedWalkthroughHost({
  id = "demo-home-stepper-host",
}: GuidedWalkthroughHostProperties) {
  const { isOpen, open } = useGuidedDocketContext();

  return (
    // A plain block (not an aria-labelledby region) so the docket panel stays the
    // single "Guided walkthrough" landmark — this is just an anchor on the demo home.
    <div id={id} className="demo-home-stepper-host">
      <h2 id={`${id}-title`} className="demo-home-stepper-host-title">
        Guided walkthrough
      </h2>
      <p id={`${id}-note`} className="demo-home-stepper-host-note">
        A 21-step tour of the workspace — what you're seeing and how it's built —
        runs in a docket pinned to the corner of the screen.
      </p>
      <button
        id={`${id}-open`}
        type="button"
        className="button button-filled demo-home-stepper-host-open"
        onClick={open}
      >
        <span id={`${id}-open-label`} className="demo-home-stepper-host-open-label">
          {isOpen ? "Go to the guided walkthrough" : "Open the guided walkthrough"}
        </span>
      </button>
    </div>
  );
}
