import Card from "./Card.tsx";

interface GuidedWalkthroughHostProperties {
  /** Required base id for the host region (CLAUDE.md). Epic 17 swaps the real
   *  21-step docket into this stable id, so it lives in one place. Defaults to
   *  `demo-home-stepper-host` — the seam name the plan fixed. */
  id?: string;
}

// Beat 3's destination — the titled "Guided walkthrough" host region on the demo
// home. Built on the Epic 8 Card so it reads as a real section of the page, with a
// stable id (`demo-home-stepper-host`) that Epic 17 mounts the real 21-step docket
// into. Until then it carries the established "available in a later step" voice
// (the Epic 12 left-nav coming-soon register) so beat 3 never dead-links.
//
// Split out as its own focused component (React philosophy): the demo home owns the
// orientation copy, this owns the walkthrough host, and Epic 17 changes only this
// file when it lands the docket.
export default function GuidedWalkthroughHost({
  id = "demo-home-stepper-host",
}: GuidedWalkthroughHostProperties) {
  return (
    <Card id={id} title="Guided walkthrough" headingLevel={2}>
      <p id={`${id}-note`} className="demo-home-stepper-host-note">
        The step-by-step tour lands here in a later step. For now, look around
        using the left navigation and switch personas up top to see how the
        workspace changes.
      </p>
    </Card>
  );
}
