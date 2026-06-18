import type { Identity } from "../api";
import { useSession } from "../session";
import { ROLE_LABELS } from "../components/roleLabels.ts";
import GuidedWalkthroughHost from "../components/GuidedWalkthroughHost.tsx";

// The demo home behind the `/app` guard — the landing pad after a visitor picks a
// tenant (which passwordlessly assumed Agent) and the host the guided walkthrough
// mounts into. It is a brief welcome + what-to-do-next, deliberately NOT a re-pitch
// of the product (the landing page owns "what PolicyFlow is / simulated & safe /
// time commitment"); this surface only says where you are and how to proceed.
//
// Three beats: (1) a welcome headline; (2) a persona-aware grounding line that
// names the role + tenant (or, for the tenantless Platform Admin, the
// cross-platform posture); (3) a how-to-proceed line pointing at the guided
// walkthrough host below. Real chrome (masthead + theming) comes from the
// surrounding AppShell, so this page carries no header of its own.

export default function DemoHomePage() {
  const { identity } = useSession();

  // The route guard guarantees a signed-in identity before this renders, but the
  // session type is `Identity | null`; guard defensively so a stray null can
  // never throw.
  if (identity === null) {
    return (
      <div id="demo-home-content" className="demo-home-content">
        <p id="demo-home-empty" className="demo-home-empty">
          No active session.
        </p>
      </div>
    );
  }

  return (
    <div id="demo-home-content" className="demo-home-content">
      <h1 id="demo-home-title" className="demo-home-title">
        Welcome to the PolicyFlow demo
      </h1>

      <GroundingLine identity={identity} />

      <p id="demo-home-proceed" className="demo-home-proceed">
        Follow the guided walkthrough below to take the full tour, or explore on
        your own using the left navigation and the persona switcher up top.
      </p>

      <GuidedWalkthroughHost />
    </div>
  );
}

interface GroundingLineProperties {
  identity: Identity;
}

// Beat 2 — the persona-aware grounding line. Two shapes from one identity:
//
//   TENANT-SCOPED (Agent / Tenant Admin / Read-Only) — "You're signed in as a
//   <role label> at <tenant name> — a fully working insurance workspace running
//   on simulated data." The role + tenant read as the emphasized facts, carried
//   in the `demo-home-role` / `demo-home-tenant` spans.
//
//   TENANTLESS (Platform Admin — `tenant_name == null`) — a variant that names the
//   cross-platform posture instead of a tenant: "You're signed in as a Platform
//   Administrator — operating across the whole platform, outside any single tenant
//   (still fully simulated)."
//
// Role labels reuse `roleLabels.ts` so this never drifts from the masthead switcher.
function GroundingLine({ identity }: GroundingLineProperties) {
  const roleLabel = ROLE_LABELS[identity.user.role];

  // The tenantless Platform Admin reads the cross-platform variant; everyone else
  // is grounded in their tenant by display name (e.g. "Sunshine Senior Benefits").
  if (identity.user.tenant_name === null) {
    return (
      <p id="demo-home-grounding" className="demo-home-grounding">
        You're signed in as a{" "}
        <span id="demo-home-role" className="demo-home-role">
          {roleLabel}
        </span>{" "}
        — operating across the whole platform, outside any single tenant (still
        fully simulated).
      </p>
    );
  }

  return (
    <p id="demo-home-grounding" className="demo-home-grounding">
      You're signed in as a{" "}
      <span id="demo-home-role" className="demo-home-role">
        {roleLabel}
      </span>{" "}
      at{" "}
      <span id="demo-home-tenant" className="demo-home-tenant">
        {identity.user.tenant_name}
      </span>{" "}
      — a fully working insurance workspace running on simulated data.
    </p>
  );
}
