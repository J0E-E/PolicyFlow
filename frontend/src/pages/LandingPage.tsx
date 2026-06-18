import ButtonLink from "../components/ButtonLink.tsx";
import ExplainerPopover from "../components/ExplainerPopover.tsx";
import PageLayout from "../components/PageLayout.tsx";
import SimulatedBadge from "../components/SimulatedBadge.tsx";
import { landingExplainer } from "../components/explainerContent.ts";

// Landing route (`/`). Real editorial orientation (Guide §6.13) in a calm,
// four-beat register: what PolicyFlow is and why, that everything is simulated and
// safe to explore, the time commitment, and one Filled CTA into tenant selection.
// Besley Display hero, an Oxford double rule beneath the title, Public Sans body
// registers, and the Epic 7 Filled button-link through to tenant selection
// (Guide §3, §4, §5). The lede retains the exact phrase "event-driven insurance
// operations platform" (the RequireSession redirect test matches it).
export default function LandingPage() {
  return (
    <PageLayout pageId="landing">
      <div id="landing-content" className="landing-content">
        <h1 id="landing-hero-title" className="landing-hero-title">
          PolicyFlow
        </h1>
        <hr id="landing-oxford-rule" className="oxford-double-rule" />
        <p id="landing-lede" className="landing-lede">
          An event-driven insurance operations platform — a working demonstration
          of how a regulated industry's everyday work holds together: multi-tenant
          isolation, role-based access, encrypted customer records, and the async
          event machinery that carries a lead through to a bound policy.{" "}
          <ExplainerPopover
            id="explainer-landing"
            surfaceLabel="event-driven operations"
            content={landingExplainer}
          />
        </p>
        <p id="landing-safe-note" className="landing-safe-note">
          Everything here is simulated and safe to explore — no real customer data,
          nothing you can break. Click into anything, switch roles, trigger the
          workflows.{" "}
          <SimulatedBadge
            id="simulated-landing"
            surfaceLabel="the whole demo"
          />
        </p>
        <p id="landing-time-commitment" className="landing-time-commitment">
          A guided walkthrough takes about 10–15 minutes, or pick a tenant and
          wander.
        </p>
        <ButtonLink
          id="landing-select-tenant-button"
          variant="filled"
          to="/select-tenant"
        >
          Choose a demo tenant
        </ButtonLink>
      </div>
    </PageLayout>
  );
}
