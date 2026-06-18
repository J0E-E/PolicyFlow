import type { ReactNode } from "react";
import { useSession } from "../session";
import { useIdentityTheming } from "./useIdentityTheming.ts";
import { useGuidedDocket } from "./useGuidedDocket.ts";
import { GuidedDocketContext } from "./GuidedDocketContext.ts";
import Masthead from "./Masthead.tsx";
import LeftNav from "./LeftNav.tsx";
import Footer from "./Footer.tsx";
import GuidedDocket from "./GuidedDocket.tsx";

interface AppShellProperties {
  /** The routed content rendered into the shell's `<main>`. */
  children: ReactNode;
}

// The branded chrome wrapping every guarded `/app` surface (Guide §4 — "App shell
// is a fixed left nav + top masthead; content scrolls"). It runs the identity →
// data-attribute theming effect (so the whole document re-themes to the active
// tenant/persona) and lays out: the sticky masthead full-width on top, with a
// fixed-width left-nav rail beside the scrolling `<main>` below it.
//
// The guard (RequireSession) only renders this on its signed-in branch, so
// `identity` is present here; a defensive null-guard renders just `<main>` so a
// stray null can never throw while the chrome awaits an identity (the rail also
// reads the identity, so it lives inside the same guard).
//
// It also holds the ONE guided-docket state (useGuidedDocket) and provides it through
// GuidedDocketContext, so the floating <GuidedDocket> mounted here (an overlay at
// --z-stepper, persistent over every /app surface) and the demo-home "Open the guided
// walkthrough" opener nested below it act on the same docket. Mounting the docket in
// the shell — not on one page — is what keeps it (and its corner reopen tab) present
// across /app screens (Epic 17 deliberately overrides Epic 16's "changes only
// GuidedWalkthroughHost.tsx" note: the docket is a shell overlay, not an inline card).
export default function AppShell({ children }: AppShellProperties) {
  const { identity, capabilities, assumePersona } = useSession();
  useIdentityTheming(identity);
  const guidedDocket = useGuidedDocket();

  return (
    <GuidedDocketContext.Provider value={guidedDocket}>
      <div id="app-shell" className="app-shell">
        {identity && (
          <Masthead identity={identity} assumePersona={assumePersona} />
        )}
        <div id="app-shell-body" className="app-shell-body">
          {identity && (
            <LeftNav role={identity.user.role} capabilities={capabilities} />
          )}
          <main id="app-shell-main" className="app-shell-main">
            {children}
          </main>
        </div>
        <Footer />
        {identity && <GuidedDocket />}
      </div>
    </GuidedDocketContext.Provider>
  );
}
